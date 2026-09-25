import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import * as authApi from '@/api/endpoints/auth'
import { ForbiddenError, NetworkError, UnauthorizedError } from '@/api/errors'
import { makeTokenPair } from '../helpers/fixtures'

/**
 * authStore（FE-04 / FE-12 §2）。
 *
 * 关注点不在"登录页长什么样"，而在**状态机**：
 * 登录成功 / 卡在 MFA 挑战 / 登出 / 令牌持久化。
 * 其中最容易写错的是"MFA 挑战 ≠ 已登录" —— 挑战阶段没有会话令牌，
 * 把这个状态当成已登录会让后续所有请求都带上不存在的 Authorization。
 */

vi.mock('@/api/endpoints/auth', () => ({
  login: vi.fn(),
  verifyMfa: vi.fn(),
  refresh: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  changePassword: vi.fn(),
  getMfaStatus: vi.fn(),
  setupMfa: vi.fn(),
  enableMfa: vi.fn(),
  disableMfa: vi.fn(),
}))

const api = vi.mocked(authApi)

/**
 * 令牌是 authStore 的**模块级内存变量**，不随 pinia 实例走 ——
 * setup.ts 只重置 pinia 与 localStorage，清不掉它。不在这里显式清一次，
 * 上一个用例留下的令牌会渗进下一个用例（实测"挑战态不建立会话"
 * 拿到的是上一条用例的 access-A，看起来像实现 bug，其实是夹具脏）。
 */
beforeEach(() => {
  useAuthStore().clearSession()
})

function loginOk(mustChangePassword = false) {
  return {
    ...makeTokenPair('access-A', 'refresh-A'),
    must_change_password: mustChangePassword,
    user: { id: '7001', username: 'admin', display_name: '管理员' },
  }
}

describe('登录', () => {
  beforeEach(() => {
    vi.mocked(authApi.login).mockReset()
  })

  it('成功登录写入用户、令牌与强制改密标记', async () => {
    api.login.mockResolvedValue(loginOk(true))

    const store = useAuthStore()
    await expect(store.login({ username: 'admin', password: 'pw' })).resolves.toBe('ok')

    expect(store.isAuthenticated).toBe(true)
    expect(store.user?.username).toBe('admin')
    expect(store.mustChangePassword).toBe(true)
    expect(store.peekAccessToken()).toBe('access-A')
    expect(store.peekRefreshToken()).toBe('refresh-A')
    // 令牌同时落到 localStorage，刷新页面后可以续上会话。
    expect(window.localStorage.getItem('vctn.access_token')).toBe('access-A')
  })

  it('口令不进任何前端持久化介质（FE-11 §2）', async () => {
    api.login.mockResolvedValue(loginOk())

    const store = useAuthStore()
    await store.login({ username: 'admin', password: 'super-secret' })

    const persisted = JSON.stringify(window.localStorage)
    expect(persisted).not.toContain('super-secret')
    expect(persisted).not.toContain('password')
  })

  it('后端要求 MFA 时进入挑战态，**不建立会话**', async () => {
    api.login.mockResolvedValue({
      mfa_required: true,
      mfa_token: 'mfa-tmp',
      expires_at: '2026-01-01T00:10:00Z',
      provider: 'TOTP',
    })

    const store = useAuthStore()
    await expect(store.login({ username: 'admin', password: 'pw' })).resolves.toBe('mfa_required')

    expect(store.isAuthenticated).toBe(false)
    expect(store.pendingMfa).toEqual({
      mfa_token: 'mfa-tmp',
      expires_at: '2026-01-01T00:10:00Z',
      provider: 'TOTP',
    })
    expect(store.peekAccessToken()).toBeNull()
  })

  it('登录失败保留错误信息并向上抛出', async () => {
    api.login.mockRejectedValue(new UnauthorizedError(401001, '口令错误', 401))

    const store = useAuthStore()
    await expect(store.login({ username: 'admin', password: 'wrong' })).rejects.toBeInstanceOf(
      UnauthorizedError,
    )
    expect(store.error).toBe('口令错误')
    expect(store.isAuthenticated).toBe(false)
    // loading 必须收敛，否则登录按钮会一直转圈。
    expect(store.loading).toBe(false)
  })
})

describe('MFA 校验', () => {
  beforeEach(() => {
    vi.mocked(authApi.login).mockReset()
    vi.mocked(authApi.verifyMfa).mockReset()
    vi.mocked(authApi.getMe).mockReset()
  })

  it('校验成功后建立会话并拉取用户信息', async () => {
    api.login.mockResolvedValue({
      mfa_required: true,
      mfa_token: 'mfa-tmp',
      expires_at: '2026-01-01T00:10:00Z',
      provider: 'TOTP',
    })
    api.verifyMfa.mockResolvedValue(makeTokenPair('access-M', 'refresh-M'))
    api.getMe.mockResolvedValue({
      id: '7001',
      username: 'admin',
      display_name: '管理员',
      department_id: null,
      status: 'ACTIVE',
      must_change_password: false,
      password_expired: false,
    })

    const store = useAuthStore()
    await store.login({ username: 'admin', password: 'pw' })
    await store.verifyMfa('123456')

    expect(store.pendingMfa).toBeNull()
    expect(store.isAuthenticated).toBe(true)
    expect(store.peekAccessToken()).toBe('access-M')
    expect(api.verifyMfa).toHaveBeenCalledWith({ mfa_token: 'mfa-tmp', code: '123456' })
  })

  it('没有待完成的挑战时直接报错（不假装成功）', async () => {
    const store = useAuthStore()
    await expect(store.verifyMfa('123456')).rejects.toThrow('当前没有待完成的 MFA 挑战')
    expect(store.isAuthenticated).toBe(false)
  })
})

describe('令牌读写', () => {
  it('令牌存在内存变量与 localStorage 两处', () => {
    const store = useAuthStore()
    store.setTokens(makeTokenPair())

    expect(store.accessTokenValue).toBe('access-1')
    expect(store.refreshTokenValue).toBe('refresh-1')
    expect(window.localStorage.getItem('vctn.access_token')).toBe('access-1')
  })

  it('clearSession 同时清内存与 localStorage', async () => {
    const store = useAuthStore()
    store.setTokens(makeTokenPair())
    store.clearSession()

    expect(store.isAuthenticated).toBe(false)
    expect(store.accessTokenValue).toBeNull()
    expect(store.refreshTokenValue).toBeNull()
    expect(window.localStorage.getItem('vctn.refresh_token')).toBeNull()
  })

  it('restorePersistedTokens 把令牌读回内存', () => {
    window.localStorage.setItem('vctn.access_token', 'access-old')
    window.localStorage.setItem('vctn.refresh_token', 'refresh-old')

    const store = useAuthStore()
    const restored = store.restorePersistedTokens()

    expect(restored).toEqual({ access: 'access-old', refresh: 'refresh-old' })
    expect(store.accessTokenValue).toBe('access-old')
  })

  it('localStorage 不可用时不抛异常（隐私模式）', () => {
    const store = useAuthStore()
    const getItem = vi.spyOn(window.localStorage.__proto__, 'getItem')
    getItem.mockImplementation(() => {
      throw new Error('localStorage denied')
    })

    expect(() => store.restorePersistedTokens()).not.toThrow()
    expect(store.accessTokenValue).toBeNull()
  })
})

describe('登出', () => {
  it('先调后端再清本地状态', async () => {
    api.logout.mockResolvedValue({ revoked: true, already_revoked: false })

    const store = useAuthStore()
    store.setTokens(makeTokenPair())
    store.user = { id: '7001', username: 'admin', display_name: '管理员', must_change_password: false }

    await store.logout()

    expect(api.logout).toHaveBeenCalledTimes(1)
    expect(store.isAuthenticated).toBe(false)
    expect(store.peekAccessToken()).toBeNull()
  })

  it('后端登出失败也要本地清理（不把用户卡在"看起来已登出"）', async () => {
    api.logout.mockRejectedValue(new NetworkError('网络请求失败', ''))

    const store = useAuthStore()
    store.setTokens(makeTokenPair())

    await expect(store.logout()).resolves.toBeUndefined()
    expect(store.isAuthenticated).toBe(false)
    expect(store.peekAccessToken()).toBeNull()
  })
})

describe('权限变更后的自我感知', () => {
  it('must_change_password 为 true 的会话受保护接口会拿到 403（FE-05 / RISK-001）', async () => {
    api.login.mockResolvedValue(loginOk(true))

    const store = useAuthStore()
    await store.login({ username: 'admin', password: 'pw' })

    // 这条断言锁的是"状态如实反映后端约束"：前端不得为了好体验而自我豁免。
    expect(store.mustChangePassword).toBe(true)
    expect(store.user?.must_change_password).toBe(true)

    api.getMe.mockRejectedValue(new ForbiddenError(403001, '必须修改初始口令', 403))
    await expect(store.loadMe()).rejects.toBeInstanceOf(ForbiddenError)
  })
})
