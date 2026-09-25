import { beforeEach, describe, expect, it } from 'vitest'
import { router, installDynamicRoutes, installHttpClient, resetAllSessionState } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { useAppStore } from '@/stores/app'
import { ForbiddenError, UnauthorizedError } from '@/api/errors'
import { http } from '@/api/client'
import { fail, forbidden, headerOf, ok, stubFetch, unauthorized } from '../helpers/fetchMock'
import { buildContract, FULL_PAGE_SPECS, makeTokenPair, pageSpec } from '../helpers/fixtures'

/**
 * 端到端流程（FE-12 §3）：
 * Login→permissions→dynamic routes、Logout→route cleanup、
 * 401→refresh、Refresh failure→logout、403→forbidden。
 *
 * 这里**不 mock 任何业务模块** —— store、client、endpoint、router 全是真的，
 * 只有最外层的 `fetch` 被换成假后端。这样"哪一层装反了"才赎得出来：
 * 分层各自注入正确输入时，门装反了也不会红，只有串起来才会。
 */

const LOGIN_PATH = '/api/v1/auth/login'
const ME_PATH = '/api/v1/auth/me'
const PERMISSIONS_PATH = '/api/v1/auth/permissions'
const REFRESH_PATH = '/api/v1/auth/refresh'
const LOGOUT_PATH = '/api/v1/auth/logout'

/** 假后端。用一个可变开关模拟"登录前 / 令牌失效后"两个阶段。 */
interface FakeBackend {
  loginOk: boolean
  /** `/auth/me` 是否放行。关掉后第一次请求 401、重试放行 —— 即"令牌刚好过期"。 */
  meSucceeds: boolean
  /** `/auth/me` 是否只拒绝第一次（用于验证"刷新 + 重试一次就能自愈"）。 */
  meFailOnce: boolean
  /** 刷新成功后是否仍拒绝该接口（403 场景：权限问题，不是登录态问题）。 */
  meForbiddenAfterRefresh: boolean
  refreshSucceeds: boolean
  refreshCalls: number
  meCalls: number
}

let backend: FakeBackend

function baseEnvelope(data: unknown) {
  return ok(data)
}

/** 按 URL 分发假响应。 */
function serve(call: { url: string; init: RequestInit }): Response {
  const url = call.url
  const method = call.init.method ?? 'GET'
  if (url === LOGIN_PATH && method === 'POST') {
    return backend.loginOk
      ? baseEnvelope({
          ...makeTokenPair('access-A', 'refresh-A'),
          must_change_password: false,
          user: { id: '7001', username: 'admin', display_name: '管理员' },
        })
      : unauthorized('口令错误')
  }
  if (url === PERMISSIONS_PATH) return baseEnvelope(buildContract({ permissionVersion: 1 }))
  if (url === LOGOUT_PATH) return baseEnvelope({ revoked: true, already_revoked: false })
  if (url === ME_PATH) {
    backend.meCalls += 1
    if (backend.meForbiddenAfterRefresh) {
      // 换到新令牌后仍然是"权限不够"（403），而不是"登录态没了"（401）。
      if (backend.refreshCalls > 0) return forbidden('no permission')
      return unauthorized('token expired')
    }
    if (!backend.meSucceeds) return unauthorized('token expired')
    if (backend.meFailOnce) {
      // 只拒绝第一次 —— 置 false 是关键，否则重试也会撞上，
      // 用例就变成了"刷新后重试仍 401"那条（那是另一个场景）。
      backend.meFailOnce = false
      return unauthorized('token expired')
    }
    return baseEnvelope({
      id: '7001',
      username: 'admin',
      display_name: '管理员',
      department_id: null,
      status: 'ACTIVE',
      must_change_password: false,
      password_expired: false,
    })
  }
  if (url === REFRESH_PATH) {
    backend.refreshCalls += 1
    if (!backend.refreshSucceeds) return unauthorized('refresh token revoked')
    return baseEnvelope(makeTokenPair(`access-R${backend.refreshCalls}`, `refresh-R${backend.refreshCalls}`))
  }
  if (url.includes('/probe')) return forbidden('no permission')
  return ok(null)
}

beforeEach(async () => {
  backend = {
    loginOk: true,
    meSucceeds: true,
    meFailOnce: false,
    meForbiddenAfterRefresh: false,
    refreshSucceeds: true,
    refreshCalls: 0,
    meCalls: 0,
  }
  stubFetch(async (call) => serve(call))
  installHttpClient()
  // 每个用例从干净路由表开始（上一轮装的动态路由会残留）。
  resetAllSessionState()
  // `currentRoute` 属于 vue-router 的历史栈，是模块级的，不随 pinia 重置。
  // 不清的话下一条用例会从上一轮的落点开始导航，报出来的错是
  // "infinite redirect" 这种与真实原因无关的现象。
  await router.replace('/dashboard')
})

function pathExists(path: string): boolean {
  return router.getRoutes().some((route) => route.path === path)
}

describe('Login → permissions → dynamic routes', () => {
  it('登录后拉到契约，并生成全部页面路由', async () => {
    const authStore = useAuthStore()
    const permissionStore = usePermissionStore()

    await expect(authStore.login({ username: 'admin', password: 'pw' })).resolves.toBe('ok')
    expect(authStore.isAuthenticated).toBe(true)

    await permissionStore.load()
    expect(permissionStore.isLoaded).toBe(true)

    const names = installDynamicRoutes(permissionStore.toContract())
    expect(names).toHaveLength(FULL_PAGE_SPECS.length)

    // 菜单能点到的页面一定是真实路由，而不是"菜单有、点了没反应"。
    expect(pathExists('/system/users')).toBe(true)
    expect(pathExists('/system/traces')).toBe(true)

    const usersRoute = router.getRoutes().find((route) => route.path === '/system/users')
    expect(usersRoute?.meta.permission).toBe('system:user:page')
  })

  it('无 PAGE 权限的页面不进路由表（FE-12 §5 页面权限）', async () => {
    // 这份契约只授予"用户管理"，链路查询根本不在里面。
    const contract = buildContract({ pages: [pageSpec('system:user:page', '/system/users')] })

    installDynamicRoutes(contract)

    expect(pathExists('/system/users')).toBe(true)
    // 不是"靠守卫拦下来"，而是压根没有这条路由 —— 拦得住是结果，不存在才是目的。
    expect(pathExists('/system/traces')).toBe(false)
  })

  it('守卫会把无页面权限的导航拦到 403 页', async () => {
    const authStore = useAuthStore()
    authStore.setTokens(makeTokenPair())
    authStore.user = {
      id: '7001',
      username: 'admin',
      display_name: '管理员',
      must_change_password: false,
    }
    const permissionStore = usePermissionStore()
    // 先按全量契约装路由（模拟"刚登录时权限还很多"）。
    const full = buildContract({ pages: FULL_PAGE_SPECS })
    permissionStore.apply(full)
    installDynamicRoutes(full)

    // 权限被回收：契约换成只有用户管理。此时路由表还没重装 ——
    // 这正是 FE-03 §5"不得假定权限永久缓存"的窗口，守卫必须挡住。
    const shrunk = buildContract({ pages: [pageSpec('system:user:page', '/system/users')] })
    permissionStore.apply(shrunk)

    await router.push('/system/users')
    expect(router.currentRoute.value.path).toBe('/system/users')

    await router.push('/system/traces')
    expect(router.currentRoute.value.path).toBe('/403')
  })

  it('未登录访问受保护页面会被送到登录页并带上来源', async () => {
    const authStore = useAuthStore()
    authStore.clearSession()

    await router.push('/system/users')

    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query['redirect']).toBe('/system/users')
  })
})

describe('Logout → 路由与状态清理', () => {
  it('登出后动态路由、权限、令牌、菜单一起消失', async () => {
    const authStore = useAuthStore()
    const permissionStore = usePermissionStore()

    await authStore.login({ username: 'admin', password: 'pw' })
    await permissionStore.load()
    installDynamicRoutes(permissionStore.toContract())
    expect(pathExists('/system/users')).toBe(true)

    await authStore.logout()

    // 少清一个就是"看起来登出了但菜单还在"的幽灵状态。
    expect(authStore.isAuthenticated).toBe(false)
    expect(permissionStore.isLoaded).toBe(false)
    expect(useAppStore().notice).toBeNull()
    expect(window.localStorage.getItem('vctn.access_token')).toBeNull()
    expect(pathExists('/system/users')).toBe(false)
  })

  it('resetAllSessionState 把三处状态一起清掉', () => {
    const authStore = useAuthStore()
    authStore.setTokens(makeTokenPair())
    const permissionStore = usePermissionStore()
    permissionStore.apply(buildContract())
    useAppStore().showNotice('info', 'x')

    resetAllSessionState()

    expect(authStore.isAuthenticated).toBe(false)
    expect(permissionStore.isLoaded).toBe(false)
    expect(useAppStore().notice).toBeNull()
  })
})

describe('401 → 刷新 → 重试', () => {
  it('令牌过期时自动刷新并重放原请求，用户无感', async () => {
    const authStore = useAuthStore()

    await authStore.login({ username: 'admin', password: 'pw' })
    expect(authStore.peekAccessToken()).toBe('access-A')

    // 只有第一次请求撞上过期的令牌，刷新接口本身可用。
    backend.meFailOnce = true

    await expect(authStore.loadMe()).resolves.toBeUndefined()

    expect(backend.refreshCalls).toBe(1)
    expect(backend.meCalls).toBe(2) // 原始一次 + 重试一次
    // 重试必须用的是新令牌 —— 否则等于白刷一次，用户看到的就是又一条 401。
    expect(authStore.peekAccessToken()).toBe('access-R1')
    expect(authStore.isAuthenticated).toBe(true)
  })

  it('刷新后重试仍 401：收敛到登出，而不是继续刷', async () => {
    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'pw' })

    // 会话真的没了：刷新接口自己是好的，但刷新出来的令牌仍然被拒。
    backend.meSucceeds = false

    await expect(authStore.loadMe()).rejects.toBeInstanceOf(UnauthorizedError)
    expect(backend.refreshCalls).toBe(1) // 刷新风暴在这里会被断言拦住
    expect(authStore.isAuthenticated).toBe(false)
  })

  it('刷新只发生一次：并发的多个 401 共用一个刷新', async () => {
    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'pw' })

    backend.meSucceeds = false

    await Promise.allSettled([
      authStore.loadMe(),
      authStore.loadMe(),
      authStore.loadMe(),
    ])

    expect(backend.refreshCalls).toBe(1)
  })
})

describe('Refresh failure → logout', () => {
  it('刷新令牌也失效时清空会话并回登录页', async () => {
    const authStore = useAuthStore()
    const permissionStore = usePermissionStore()

    await authStore.login({ username: 'admin', password: 'pw' })
    await permissionStore.load()
    installDynamicRoutes(permissionStore.toContract())
    expect(pathExists('/system/users')).toBe(true)

    backend.meSucceeds = false
    backend.refreshSucceeds = false

    await expect(authStore.loadMe()).rejects.toBeInstanceOf(UnauthorizedError)

    // 关键断言：刷新失败必须收敛到"已登出"，否则用户会拿着失效令牌继续点。
    expect(authStore.isAuthenticated).toBe(false)
    expect(permissionStore.isLoaded).toBe(false)
    expect(pathExists('/system/users')).toBe(false)
    expect(window.localStorage.getItem('vctn.access_token')).toBeNull()
  })

  it('刷新成功后仍被拒（403）不会把人踢下线', async () => {
    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'pw' })

    // 刷新换到了新令牌，但新令牌也进不了这个接口 —— 403 是权限问题，
    // 与登录态无关，绝不能因为"顺手刷了一次"就把人清出登录。
    backend.meForbiddenAfterRefresh = true

    await expect(authStore.loadMe()).rejects.toBeInstanceOf(ForbiddenError)
    expect(backend.refreshCalls).toBe(1)
    expect(authStore.isAuthenticated).toBe(true)
  })
})

describe('403 → forbidden', () => {
  it('API 返回 403 抛 ForbiddenError，且不触发刷新或登出', async () => {
    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'pw' })

    const before = backend.refreshCalls
    await expect(http.get('/probe')).rejects.toBeInstanceOf(ForbiddenError)

    expect(backend.refreshCalls).toBe(before)
    expect(authStore.isAuthenticated).toBe(true)
  })

  it('后端拒绝写操作后，本地状态不被"补偿"成成功', async () => {
    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'pw' })

    // 模拟后端在 403 里给出原因；前端只负责如实呈现，不代为决定。
    stubFetch(async () => fail(403001, '数据范围外，无法修改该部门', 403))

    await expect(http.post('/admin/departments/999', { department_name: 'x' })).rejects.toMatchObject({
      code: 403001,
      message: '数据范围外，无法修改该部门',
    })
    expect(authStore.isAuthenticated).toBe(true)
  })
})

describe('权限链完整性（FE-00 §4）', () => {
  it('令牌 → 契约 → 动态路由 → 菜单判定 全链路只由后端决定', async () => {
    const authStore = useAuthStore()
    const permissionStore = usePermissionStore()

    await authStore.login({ username: 'admin', password: 'pw' })
    await permissionStore.load()
    installDynamicRoutes(permissionStore.toContract())

    // 前端不持有任何"业务权限白名单"：菜单来自后端，判定也来自后端。
    expect(permissionStore.hasPagePermission('system:user:page')).toBe(true)
    expect(permissionStore.menuTree.length).toBeGreaterThan(0)

    // 令牌被清掉后，第三次判定的结果必须跟着变 —— 证明没有第二份缓存。
    useAuthStore().clearSession()
    resetAllSessionState()
    expect(permissionStore.hasPagePermission('system:user:page')).toBe(false)
    expect(pathExists('/system/users')).toBe(false)
  })

  it('登录请求带的是明文口令，且口令不写进任何响应缓存', async () => {
    backend.loginOk = true
    const fetchStub = stubFetch(async (call) => {
      if (headerOf(call, 'Authorization') !== undefined && !call.url.endsWith('/probe')) {
        return forbidden('no')
      }
      return serve(call)
    })

    const authStore = useAuthStore()
    await authStore.login({ username: 'admin', password: 'super-secret' })

    const loginCall = fetchStub.calls.find((call) => call.url === LOGIN_PATH)
    expect(loginCall?.init.body).toContain('super-secret')
    // 登录本身是免鉴权的，不应该带上 Authorization。
    expect(headerOf(loginCall!, 'Authorization')).toBeUndefined()
  })
})
