import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { useAppStore } from '@/stores/app'
import { setSessionCleanupHook } from '@/stores/auth'
import { configureClient } from '@/api/client'
import {
  FORBIDDEN_PATH,
  HOME_PATH,
  LOGIN_PATH,
  decideNavigation,
  sanitizeRedirect,
} from './guard'
import { generateRoutes, toRouteRecords } from './generate'
import type { PermissionContract } from '@/types'

/**
 * 路由实例。
 *
 * 静态路由**只有** Login / 403 / 404 与一个 layout 容器（FE-02 §1）。
 * 业务路由全部由权限契约在运行时生成 —— 任何"静态声明的业务路由"
 * 都会绕过后端权限判定（FE-02 §6：不得仅靠前端 URL 隐藏实现安全控制）。
 */

const LAYOUT_NAME = 'admin-layout'
const DYNAMIC_PREFIX = 'dyn_'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', hidden: true, public: true },
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/views/ForbiddenView.vue'),
    meta: { title: '无权限', hidden: true, public: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在', hidden: true, public: true },
  },
  {
    path: '/',
    name: LAYOUT_NAME,
    component: () => import('@/layouts/AppLayout.vue'),
    children: [
      { path: '', redirect: HOME_PATH },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '概览' },
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// ---------------------------------------------------------------- 动态路由

const addedDynamicNames: string[] = []

/**
 * 把契约里的 PAGE 生成路由并挂到 layout 下。返回生成的路由名。
 *
 * 挂到 `path: '/'` 这条记录之下（它就是 AppLayout），因此新页面会自动
 * 获得布局外壳，不需要在这里重复声明 layout。
 */
export function installDynamicRoutes(contract: PermissionContract): string[] {
  // 先清掉上一次装的：权限变更后重装（FE-03 §5）时若只增不减，
  // 用户已经失去权限的页面会留下一条仍然可导航的路由。
  resetDynamicRoutes()
  const { routes: generated, unresolved } = generateRoutes(contract)
  if (unresolved.length > 0) {
    // 不抛异常：契约里有、但本地没有对应组件时，菜单侧也不会展示它。
    // 真正的问题会在测试里被断言拦住。
    useAppStore().showNotice('info', '部分页面组件未实现，已跳过')
  }
  const names: string[] = []
  for (const record of toRouteRecords(generated)) {
    const withPrefix: RouteRecordRaw = {
      ...record,
      name: `${DYNAMIC_PREFIX}${String(record.name)}`,
    }
    router.addRoute({ path: '/', children: [withPrefix] })
    names.push(String(withPrefix.name))
    addedDynamicNames.push(String(withPrefix.name))
  }
  return names
}

/** 移除全部动态路由（Logout / Session 失效时调用）。 */
export function resetDynamicRoutes(): void {
  while (addedDynamicNames.length > 0) {
    const name = addedDynamicNames.pop()
    if (name !== undefined) router.removeRoute(name)
  }
}

/** 防重入：`clearSession()` 会回调这里，不挡住就是无限递归。 */
let inSessionReset = false

/**
 * 会话级清理（FE-02 §5 / FE-04 §5）。
 *
 * 四处状态必须一起清：动态路由、认证、权限、全局提示。
 * 少清一个是"看起来登出了但菜单还在"这类幽灵状态的经典来源 —— 实测
 * `authStore.logout()` 只清认证时，路由表里仍留着上一个账号的全部页面，
 * 绕过菜单直接改 URL 照样进得去。
 */
export function resetAllSessionState(): void {
  if (inSessionReset) return
  inSessionReset = true
  try {
    resetDynamicRoutes()
    useAuthStore().clearSession()
    usePermissionStore().reset()
    useAppStore().clearNotice()
    useAppStore().setBusy(false)
  } finally {
    inSessionReset = false
  }
}

// 让 authStore 的 clearSession 连带清掉权限与动态路由。
// 放在模块求值这里，而不是 installHttpClient 里：后者只在测试里被显式调用，
// 生产环境下一旦漏调就会出现"登出只清了一半"的状态。
setSessionCleanupHook(resetAllSessionState)

// ---------------------------------------------------------------- 守卫

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  const permissionStore = usePermissionStore()

  const decision = decideNavigation({
    to: to.path,
    isAuthenticated: authStore.isAuthenticated,
    permissionsLoaded: permissionStore.isLoaded,
    requiredPermission: (to.meta?.permission as string | undefined) ?? undefined,
    hasPermission: (code) => permissionStore.hasPagePermission(code),
  })

  if (decision.kind === 'redirect') return decision.to
  if (decision.kind === 'wait') {
    // 权限未加载：先加载，再重新走一遍判定。加载失败会走到 onSessionLost。
    try {
      await permissionStore.load()
    } catch {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    const retry = decideNavigation({
      to: to.path,
      isAuthenticated: authStore.isAuthenticated,
      permissionsLoaded: permissionStore.isLoaded,
      requiredPermission: (to.meta?.permission as string | undefined) ?? undefined,
      hasPermission: (code) => permissionStore.hasPagePermission(code),
    })
    if (retry.kind === 'redirect') return retry.to
    if (retry.kind === 'wait') return false
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta?.title as string | undefined) ?? undefined
  document.title = title === undefined ? 'VCTN 管理后台' : `${title} · VCTN 管理后台`
})

// ---------------------------------------------------------------- 装配

/** 把 Pinia store 接到 HTTP Client 上（必须在 store 之后调用）。 */
export function installHttpClient(): void {
  const authStore = useAuthStore()
  configureClient({
    baseUrl: import.meta.env['VITE_API_BASE_URL'] ?? '/api/v1',
    bridge: {
      getAccessToken: () => authStore.peekAccessToken(),
      getRefreshToken: () => authStore.peekRefreshToken(),
      refresh: (refreshToken) => authStore.doRefresh(refreshToken),
      onSessionLost: () => {
        // 刷新失败 = 令牌失效或会话被撤销（FE-04 §5）。
        resetAllSessionState()
        useAppStore().showNotice('info', '登录状态已失效，请重新登录')
      },
    },
  })
}

export { LOGIN_PATH, FORBIDDEN_PATH, HOME_PATH, sanitizeRedirect }
