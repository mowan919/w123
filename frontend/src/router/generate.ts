import type { RouteRecordSingleView } from 'vue-router'
import { defineAsyncComponent, markRaw } from 'vue'
import type { Component } from 'vue'
import type { PermissionContract } from '@/types'

/**
 * 动态路由生成器（FE-02 §2 / FE-03）。
 *
 * 这里全部是**纯函数**：不碰 router 实例、不碰 Pinia。
 * 这样 FE-12 §2 要求的"route generator 单测"可以直接喂一个契约进来断言，
 * 不需要构造整个应用（那是集成测试的事）。
 */

/**
 * 路由 meta。
 *
 * 带显式索引签名：vue-router 的 `meta` 类型是 `Record<PropertyKey, unknown>`，
 * interface 没有隐式索引签名，直接赋给它会报 "Index signature for type
 * 'string' is missing"。用 type + 索引签名可以兼得（调用点仍有字段名提示）。
 */
export type RouteMeta = {
  title: string
  icon?: string
  /** 权限判定用的资源编码；`08` 冻结，以后端资源模型为准。 */
  permission?: string
  hidden?: boolean
  keepAlive?: boolean
  [key: string]: unknown
}

export interface DynamicRouteRecord {
  path: string
  name: string
  component: Component
  meta: RouteMeta
}

/**
 * 归一化后的组件键 → 组件工厂。
 *
 * 导出供测试钉住「注册表 ↔ 视图文件」的对应关系：少了、多了、改名了
 * 都会被 `tests/router/generate.spec.ts` 拦住。缺文件会让 FE-12 §5 的
 * 页面权限判定直接判失败 —— 而这是运行时才会暴露的一类错。
 */
export const VIEW_REGISTRY: Record<string, () => Promise<{ default: Component }>> = {
  'system/user': () => import('@/views/system/UserListView.vue'),
  'system/department': () => import('@/views/system/DepartmentListView.vue'),
  'system/role': () => import('@/views/system/RoleListView.vue'),
  'system/permission': () => import('@/views/system/PermissionListView.vue'),
  'system/permission-resource': () => import('@/views/system/PermissionResourceListView.vue'),
  'system/session': () => import('@/views/system/SessionListView.vue'),
  'system/dictionary': () => import('@/views/system/DictionaryListView.vue'),
  'system/param': () => import('@/views/system/ParamListView.vue'),
  'system/audit-log': () => import('@/views/system/AuditLogListView.vue'),
  'system/trace': () => import('@/views/system/TraceListView.vue'),
}

/**
 * 把后端存的 `component_path` 归一化成注册表键。
 *
 * 后端值可能是 `/system/user`、`system/user`、`/system/user/index.vue`
 * 等任意一种写法 —— 认识这些变体，比"约定后端必须写某种格式"更省心：
 * 后者需要后端改数据，而后端是冻结契约，改不动。
 */
export function normalizeComponentPath(raw: string | null): string {
  if (raw === null || raw.trim() === '') return ''
  let value = raw.trim().replace(/^\/+/, '').replace(/\.vue$/i, '')
  value = value.replace(/\/index$/i, '')
  return value.toLowerCase()
}

export function resolveView(componentPath: string | null): Component | null {
  const key = normalizeComponentPath(componentPath)
  if (key === '') return null
  const factory = VIEW_REGISTRY[key]
  if (factory === undefined) return null
  // markRaw：路由记录会被 vue-router 内部响应式化，组件对象一旦进入
  // reactive 代理就会丢失渲染上下文（表现为组件不渲染但不报错）。
  return markRaw(defineAsyncComponent(factory))
}

/** 由 `route_path` 生成本地路由名（避免与后端耦合）。 */
function routeNameFor(path: string, code: string): string {
  const cleaned = path.replace(/[^\w-]/g, '_')
  return `page_${cleaned || code}`
}

export interface GenerateResult {
  routes: DynamicRouteRecord[]
  /** 契约里有 `component_path` 但本地没有对应组件 —— 必须在测试里被断言为空。 */
  unresolved: Array<{ code: string; componentPath: string | null }>
}

/**
 * 由权限契约生成路由。
 *
 * 只生成**有 PAGE 权限**的页面（FE-12 §5"页面权限"：无 PAGE 权限路由不可正常进入）。
 * 组件解析不出来时**跳过**而不是建一条空路由 —— 后者表现为"菜单点进去白屏"，
 * 前者表现为"这一项不出现"，两者都是安全的，但后者更容易被察觉。
 */
export function generateRoutes(contract: PermissionContract): GenerateResult {
  const routes: DynamicRouteRecord[] = []
  const unresolved: GenerateResult['unresolved'] = []
  const seen = new Set<string>()

  for (const page of contract.pages) {
    // 只用 `component_path`，**不做** `?? route_path` 的回退。
    //
    // 曾经写过这个回退，理由是"后端没配 component_path 时还能凑一个"。
    // 结果是 10 个页面里只有 3 个碰巧能解析成功（其余 7 个落在 unresolved，
    // 表现为菜单里有、点进去白屏），而构建和类型检查都不会报错。
    // 后端 `ck_permission_resources_resource_type_fields` 已约束 PAGE 必须
    // **同时**具备 `route_path` 与 `component_path`，所以这里的 null 只可能是
    // 数据不完整 —— 那就如实记为 unresolved，而不是猜一个路径出来。
    const componentPath = page.component_path
    const view = resolveView(componentPath)
    if (view === null) {
      unresolved.push({ code: page.code, componentPath })
      continue
    }
    const path = page.route_path ?? ''
    if (path === '' || seen.has(path)) continue
    seen.add(path)
    routes.push({
      path,
      name: routeNameFor(path, page.code),
      component: view,
      meta: {
        title: page.name,
        // 权限判定用**资源编码**，不是路由路径 —— 后端资源模型里
        // `code` 才是稳定标识（FE-02 §3"最终权限字段以后端资源模型为准"）。
        permission: page.code,
        keepAlive: false,
      },
    })
  }

  return { routes, unresolved }
}

/**
 * 转成 vue-router 记录。
 *
 * 返回 `RouteRecordRaw` 会让 TS 在联合类型里挑错分支（报"children 缺失"），
 * 而这里的记录必然是"单视图、无 children"，用 `RouteRecordSingleView` 才准确。
 * 类型准确也让 `router.addRoute` 在调用点少一次断言。
 */
export function toRouteRecords(records: DynamicRouteRecord[]): RouteRecordSingleView[] {
  return records.map((record) => ({
    path: record.path,
    name: record.name,
    component: record.component,
    meta: record.meta,
  }))
}
