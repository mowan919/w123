import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { useAppStore } from '@/stores/app'
import { useOrganizationStore } from '@/stores/organization'
import { useRolesStore } from '@/stores/roles'
import { useResourcesStore } from '@/stores/resources'
import { useParamsStore } from '@/stores/params'
import { useStatisticsStore } from '@/stores/statistics'
import { useNotificationsStore } from '@/stores/notifications'
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
        // 报表是**静态路由**（与 profile 同类）：它是登录后的默认落地页，
        // 必须对任何已认证用户都可达，因此不能进权限契约被 PAGE 权限卡住。
        // 页面内容按域逐个降级（无权的那一域显示"无权限"而不是 403），
        // 判定在后端 `app/services/statistics.py`，前端不做任何白名单。
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportView.vue'),
        meta: { title: '报表' },
      },
      {
        // 个人中心是**静态路由**：它不需要任何管理类权限，人人都有自己的一页，
        // 因此不进权限契约、也不由 `generateRoutes` 生成。
        // 没有 `meta.permission` ⇒ 守卫只校验"已登录"，不做页面权限判定。
        path: 'profile',
        name: 'profile',
        component: () => import('@/views/ProfileView.vue'),
        meta: { title: '个人中心' },
      },
      {
        // 消息中心同样是**静态路由**（`DESIGN-DECISIONS §32`）：它是"我的消息"，
        // 任何已认证用户都有自己的一份。
        //
        // 做成契约页面会引入一个 PAGE 权限位，然后必须给**每个**角色都授它 ——
        // 漏配一个角色，该角色的用户连自己的消息都打不开，且报错是 403
        // （看起来像越权，实际是配置漏了）。`/profile` 与 `/reports` 同理由。
        //
        // ⚠️ 注意与 `/system/notifications`（通知**管理**页）区分：后者是
        // 契约页面、需要 `notification:manage:page`，管的是"发公告给别人"；
        // 这里是"看我收到的"，两者看的是同一张表的两个方向。
        path: 'notifications',
        name: 'notifications',
        component: () => import('@/views/NotificationsView.vue'),
        meta: { title: '消息中心' },
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
    // ⚠️ 必须挂到 admin-layout **名下**。曾经新建一条 `{ path: '/', children: [...] }`
    // —— 它没有 component，vue-router 会把子组件"提升"到根 RouterView，
    // 页面绕过 AppLayout 渲染：侧栏、顶栏、面包屑全部消失，只剩孤零零的内容。
    // 表现正好是"所有页面都光秃秃的"。
    router.addRoute(LAYOUT_NAME, withPrefix)
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
 * 七类状态必须一起清：动态路由、认证、权限、全局提示，以及四个业务域的
 * 参考数据缓存。少清一个是"看起来登出了但菜单还在"这类幽灵状态的经典
 * 来源 —— 实测 `authStore.logout()` 只清认证时，路由表里仍留着上一个
 * 账号的全部页面，绕过菜单直接改 URL 照样进得去。
 *
 * ⚠️ 业务域缓存这一项是**安全**要求，不只是"免得显示旧数据"：
 * 部门树是数据范围的骨架，超管拿到的树比部门管理员**宽**。这份树一旦被
 * 缓存留到换账号之后，下一个账号的用户（哪怕只是同一个浏览器开了另一个
 * 账号）就能看到上一个账号可见、而自己无权看到的部门清单 —— 一次实打实
 * 的越权信息泄露，且不会有任何报错。
 *
 * 报表统计同理，而且更直接：它的每个数字都是**已经被权限过滤过的**
 * （无权限的域返回 null）。缓存留到下一个（权限更低的）账号，
 * 页面会先渲染出上一个人看到的数字再被刷新覆盖 —— 同样是一次静默越权展示。
 *
 * 通知（`§32`）是**第三种**同样性质的残留，而且最露骨：未读数是"我收到几条"，
 * 面板里还带着消息**正文**。不清的话，换账号后顶栏会先显示上一个账号的
 * 未读数与消息标题，直到 60 秒后那次轮询才覆盖掉 —— 中间这段时间里，
 * 后一个用户读到的是前一个用户的消息。`reset()` 同时停掉定时器，
 * 否则登出后还会继续替一个已经不存在于前端的会话发请求。
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
    useOrganizationStore().reset()
    useRolesStore().reset()
    useResourcesStore().reset()
    useParamsStore().reset()
    useStatisticsStore().reset()
    useNotificationsStore().reset()
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
    // 动态路由只由 LoginView 在登录成功时装一次 —— 整页刷新后不存在，
    // 初始导航已把 /system/users 这类路径解析成 not-found。
    // 必须在放行前重建，并**重新导航**让新路由参与解析。
    installDynamicRoutes(permissionStore.toContract())
    const retry = decideNavigation({
      to: to.path,
      isAuthenticated: authStore.isAuthenticated,
      permissionsLoaded: permissionStore.isLoaded,
      requiredPermission: (to.meta?.permission as string | undefined) ?? undefined,
      hasPermission: (code) => permissionStore.hasPagePermission(code),
    })
    if (retry.kind === 'redirect') return retry.to
    if (retry.kind === 'wait') return false
    // 初始导航发生在动态路由注册之前，路径已被解析成 not-found；
    // 现在路由已就位，用原路径重导一次。真正不存在的路径重导后
    // 仍是 not-found，且此时 permissionsLoaded=true 不会再进本分支 —— 无循环。
    if (to.name === 'not-found') {
      return { path: to.fullPath, replace: true }
    }
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
