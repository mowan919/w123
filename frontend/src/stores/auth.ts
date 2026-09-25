import { defineStore } from 'pinia'
import type { LoginRequest, LoginResponse, TokenPair } from '@/types'
import * as authApi from '@/api/endpoints/auth'

/**
 * authStore（FE-04）。
 *
 * 职责边界：只管**认证状态与令牌**。权限集合在 permissionStore，
 * 动态路由在 router —— 在这里塞进第三份状态，是"三个地方都要同步清理"
 * 的经典来源，Logout 时最容易漏一个。
 */

const TOKEN_KEY = 'vctn.access_token'
const REFRESH_KEY = 'vctn.refresh_token'

/** 令牌落在内存变量里；刷新页面后为空，由 `/auth/refresh` 或重新登录建立。 */
let accessToken: string | null = null
let refreshToken: string | null = null

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

/**
 * 会话级清理钩子，由 `router/index.ts` 注册。
 *
 * 用钩子而不是在 store 里 import router：`router` 已经 import 了这个 store，
 * 反向依赖会形成 ESM 循环，且在单测里必须构造整棵应用树。
 */
type SessionCleanupHook = () => void
let sessionCleanupHook: SessionCleanupHook | null = null

/** 安装会话清理钩子（幂等，重复安装以最后一次为准）。 */
export function setSessionCleanupHook(hook: SessionCleanupHook | null): void {
  sessionCleanupHook = hook
}

function safeSet(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // 隐私模式 / 配额耗尽：令牌只存在于内存，会话仍可用，只是不跨刷新存活。
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as {
      id: string
      username: string
      display_name: string
      must_change_password: boolean
    } | null,
    /** 登录流程中卡在 MFA 挑战阶段。此时**没有**会话令牌。 */
    pendingMfa: null as {
      mfa_token: string
      expires_at: string
      provider: string
    } | null,
    /** 由于 `must_change_password` 未解除，受保护接口会返回 403。 */
    mustChangePassword: false,
    loading: false,
    error: null as string | null,
  }),

  getters: {
    isAuthenticated: (state): boolean => state.user !== null,
    accessTokenValue: (): string | null => accessToken,
    refreshTokenValue: (): string | null => refreshToken,
  },

  actions: {
    /** 供 HTTP Client 的 AuthBridge 读取。 */
    peekAccessToken(): string | null {
      return accessToken
    },

    peekRefreshToken(): string | null {
      return refreshToken
    },

    setTokens(pair: TokenPair): void {
      accessToken = pair.access_token
      refreshToken = pair.refresh_token
      safeSet(TOKEN_KEY, pair.access_token)
      safeSet(REFRESH_KEY, pair.refresh_token)
    },

    /**
     * 清空认证所需的全部状态。
     *
     * 动态路由与权限集合属于**别的 store**，这里不直接 import router（会成环），
     * 而是调由 router 注册的清理钩子。只清 token 的后果是"看起来登出了、
     * 菜单和路由还在" —— 下一轮登录前用户甚至能点进上一个账号的页面。
     */
    clearSession(): void {
      accessToken = null
      refreshToken = null
      safeSet(TOKEN_KEY, null)
      safeSet(REFRESH_KEY, null)
      this.user = null
      this.pendingMfa = null
      this.mustChangePassword = false
      this.error = null
      sessionCleanupHook?.()
    },

    /**
     * 登录。
     *
     * 返回 'mfa_required' 表示后端要求二次校验 —— 此时**还没有**会话，
     * 调用方应展示 MFA 输入，不要跳首页。
     */
    async login(payload: LoginRequest): Promise<'ok' | 'mfa_required'> {
      this.loading = true
      this.error = null
      try {
        const result = await authApi.login(payload)
        if ('mfa_required' in result && result.mfa_required === true) {
          this.pendingMfa = {
            mfa_token: result.mfa_token,
            expires_at: result.expires_at,
            provider: result.provider,
          }
          return 'mfa_required'
        }
        const ok = result as LoginResponse
        this.setTokens(ok)
        this.mustChangePassword = ok.must_change_password
        this.user = {
          id: ok.user.id,
          username: ok.user.username,
          display_name: ok.user.display_name,
          must_change_password: ok.must_change_password,
        }
        return 'ok'
      } catch (error) {
        this.error = error instanceof Error ? error.message : '登录失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    /** 提交 MFA 动态码，成功后建立会话。 */
    async verifyMfa(code: string): Promise<void> {
      const pending = this.pendingMfa
      if (pending === null) throw new Error('当前没有待完成的 MFA 挑战')
      this.loading = true
      try {
        const pair = await authApi.verifyMfa({ mfa_token: pending.mfa_token, code })
        this.pendingMfa = null
        this.setTokens(pair)
        this.mustChangePassword = false
        const me = await authApi.getMe()
        this.user = {
          id: me.id,
          username: me.username,
          display_name: me.display_name,
          must_change_password: me.must_change_password,
        }
        this.mustChangePassword = me.must_change_password
      } finally {
        this.loading = false
      }
    },

    /** 供 HTTP Client 的 AuthBridge 使用。 */
    async doRefresh(rt: string): Promise<TokenPair> {
      // `refreshOnUnauthorized: false`：刷新请求自己 401 时不能再触发刷新，
      // 否则就是"刷新请求去刷新自己"的无限递归。
      const pair = await authApi.refresh({ refresh_token: rt })
      this.setTokens(pair)
      return pair
    },

    /** 登出：先告诉后端，再清状态（顺序不能反，否则后端撒不掉会话）。 */
    async logout(): Promise<void> {
      try {
        await authApi.logout()
      } catch {
        // 后端登出失败也要本地清理：让用户卡在"看起来已登出但令牌还在"的
        // 状态里，比"重登一次"更糟。
      } finally {
        this.clearSession()
      }
    },

    async loadMe(): Promise<void> {
      const me = await authApi.getMe()
      this.user = {
        id: me.id,
        username: me.username,
        display_name: me.display_name,
        must_change_password: me.must_change_password,
      }
      this.mustChangePassword = me.must_change_password
    },

    /** 恢复刷新前的令牌（通常来自 localStorage）。 */
    restorePersistedTokens(): { access: string | null; refresh: string | null } {
      accessToken = safeGet(TOKEN_KEY)
      refreshToken = safeGet(REFRESH_KEY)
      return { access: accessToken, refresh: refreshToken }
    },
  },
})
