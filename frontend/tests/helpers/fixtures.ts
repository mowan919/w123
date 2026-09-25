import type {
  FieldAccessLevel,
  PermissionContract,
  PermissionFieldItem,
  PermissionMenuItem,
  PermissionPageItem,
  TokenPair,
} from '@/types'

/**
 * 测试夹具。
 *
 * 这里的原则：**契约形状照抄后端，不照抄"应该长什么样"**。
 * 每个字段名都能在 `app/schemas` 里找到对应定义 —— 早期版本按直觉写了
 * `buttons` / `apis`，后来被 `PermissionContract` 的真实字段纠正过一次。
 */

/**
 * 页面夹具的形状**照抄契约**（snake_case），不用 camelCase。
 *
 * 曾经用 `routePath` 这个名字，结果在手写字面量时不小心漏掉了
 * `component_path` —— 类型检查不报（都是可选字段），直到动态路由只生成
 * 3/10 条才被发现。字段跟契约同名，这类拼写错误就无处可藏。
 */
export interface PageSpec {
  code: string
  name: string
  route_path: string
  /** 缺省表示后端没配 —— 真实数据里 PAGE 这个字段由 CHECK 约束强制非空。 */
  component_path?: string | null
  sort_order?: number
}

/**
 * 十个页面，与 `VIEW_REGISTRY` 的十个键一一对应。
 *
 * 每个页面都显式给出 `component_path`（等于注册表键），因为后端 CHECK 约束
 * 保证了 PAGE 必须同时具备 `route_path` 与 `component_path`。
 * 覆盖全部键是关键：只要有一个键没被任何页面引用，"注册表里有、文件不存在"
 * 这类错误就测不出来。
 */
export const FULL_PAGE_SPECS: PermissionPageItem[] = [
  { id: '1001', code: 'system:user:page', name: '用户管理', route_path: '/system/users', component_path: '/system/user', sort_order: 10 },
  { id: '1002', code: 'system:department:page', name: '部门管理', route_path: '/system/departments', component_path: '/system/department', sort_order: 20 },
  { id: '1003', code: 'system:role:page', name: '角色管理', route_path: '/system/roles', component_path: '/system/role', sort_order: 30 },
  { id: '1004', code: 'system:permission:page', name: '权限配置', route_path: '/system/permissions', component_path: 'system/permission/index.vue', sort_order: 40 },
  { id: '1005', code: 'system:permission-resource:page', name: '权限资源', route_path: '/system/permission-resources', component_path: '/system/permission-resource', sort_order: 50 },
  { id: '1006', code: 'system:session:page', name: '会话管理', route_path: '/system/sessions', component_path: '/system/session', sort_order: 60 },
  { id: '1007', code: 'system:dictionary:page', name: '字典管理', route_path: '/system/dictionaries', component_path: '/system/dictionary', sort_order: 70 },
  { id: '1008', code: 'system:param:page', name: '系统参数', route_path: '/system/params', component_path: '/system/param', sort_order: 80 },
  // `component_path` 是**视图注册表键**，不是路由路径 —— 两者不必同名。
  // 这两个页面正是靠"路径复数、键单数"的差别才暴露过一次夹具写错
  // （写成 component_path='/system/audit-logs'，归一化后匹配不到
  // `system/audit-log`，全量契约直接生成不出这两条路由）。
  { id: '1009', code: 'system:audit-log:page', name: '审计日志', route_path: '/system/audit-logs', component_path: '/system/audit-log', sort_order: 90 },
  { id: '1010', code: 'system:trace:page', name: '链路查询', route_path: '/system/traces', component_path: '/system/trace', sort_order: 100 },
]

/**
 * 默认的全套页面，直接就是完整契约项。
 *
 * 早期这里有两个形状（`PageSpec` 简写 + `buildPages` 补全），简写那条路径
 * 少了 `id`、且 `route_path` 写死成非空 `string` —— 于是"某个页面的
 * `route_path` 是 null"这个真实情况在测试里根本构造不出来。
 * 少一层转换，就少一处能藏住错误的缝。
 */
export function buildPages(): PermissionPageItem[] {
  return FULL_PAGE_SPECS
}

/**
 * 只想摆一两个页面时的简写。直接返回**完整**的 `PermissionPageItem`。
 *
 * 早期这里返回的是不带 `id` 的简写形状，于是 `buildContract({ pages: [pageSpec(...)] })`
 * `componentPath` 的默认值是**注册表里必然存在**的键，不是 `routePath`：
 * 早期默认成 `routePath`（`/dup` 之类），结果绝大多数用例根本生成不出路由，
 * 而失败信息只是"expected [] to have a length of 1"，很难反推原因。
 * 想要"组件缺失"的情形请显式传 `null`。
 */
export function pageSpec(
  code: string,
  routePath: string,
  componentPath: string | null = 'system/user',
): PermissionPageItem {
  return {
    id: `p-${code}`,
    code,
    name: code,
    route_path: routePath,
    component_path: componentPath,
    sort_order: 10,
  }
}

/**
 * 菜单引用页面的方式：`page_ids` 存的是**页面 id**。
 *
 * 这里从 `FULL_PAGE_SPECS` 反查，而不是写死 '1000' / '1002' ——
 * 曾经写死，页面夹具补上 `id` 字段后这组数字悄悄失真，
 * 表现为"菜单点进去没反应"，但报错信息只说 path 少了，看不出是 id 对不上。
 */
export function pageIdOf(code: string): string {
  return FULL_PAGE_SPECS.find((page) => page.code === code)?.id ?? ''
}

/** 一个两级菜单：父菜单 + 两个子菜单，用来验证 `menuTree` 的父子挂载与排序。 */
export function buildMenus(): PermissionMenuItem[] {
  return [
    {
      id: '5001',
      code: 'system:system',
      name: '系统管理',
      icon: 'setting',
      parent_id: null,
      sort_order: 10,
      page_ids: [],
    },
    {
      id: '5002',
      code: 'system:user',
      name: '用户管理',
      icon: null,
      parent_id: '5001',
      sort_order: 20,
      page_ids: [pageIdOf('system:user:page')],
    },
    {
      id: '5003',
      code: 'system:role',
      name: '角色管理',
      icon: null,
      parent_id: '5001',
      sort_order: 10,
      page_ids: [pageIdOf('system:role:page')],
    },
  ]
}

export function fieldItems(): PermissionFieldItem[] {
  const rows: Array<[string, string, FieldAccessLevel]> = [
    ['6001', 'user.phone', 'READ_ONLY'],
    ['6002', 'user.email', 'EDITABLE'],
    ['6003', 'user.internal_note', 'HIDDEN'],
    ['6004', 'user.remark', 'VISIBLE'],
  ]
  return rows.map(([id, fieldKey, accessLevel]) => ({
    id,
    code: `field:${fieldKey}`,
    field_key: fieldKey,
    owner_resource_id: '6000',
    access_level: accessLevel,
  }))
}

export interface BuildContractOptions {
  pages?: PermissionPageItem[]
  menus?: PermissionMenuItem[]
  permissionVersion?: number
  isSuperAdmin?: boolean
  directRoleIds?: string[]
  inheritedRoleIds?: string[]
  dataScopePolicy?: PermissionContract['data_scope']['policy']
  dataScopeDepartmentIds?: string[] | null
  scopeIncludeSelf?: boolean
}

export function buildContract(options: BuildContractOptions = {}): PermissionContract {
  return {
    user_id: '7001',
    is_super_admin: options.isSuperAdmin ?? false,
    direct_role_ids: options.directRoleIds ?? ['9001'],
    inherited_role_ids: options.inheritedRoleIds ?? [],
    pages: options.pages ?? buildPages(),
    menus: options.menus ?? buildMenus(),
    buttons: [
      { id: '8001', code: 'user:create', name: '新增用户', parent_id: null, sort_order: 10 },
      { id: '8002', code: 'user:delete', name: '删除用户', parent_id: null, sort_order: 20 },
    ],
    apis: [
      {
        id: '8101',
        code: 'api:user:list',
        name: '查询用户',
        api_method: 'GET',
        api_path: '/admin/users',
        parent_id: null,
      },
    ],
    fields: fieldItems(),
    data_scope: {
      policy: options.dataScopePolicy ?? 'ALL',
      department_ids: options.dataScopeDepartmentIds ?? null,
      include_self: options.scopeIncludeSelf ?? true,
    },
    permission_version: options.permissionVersion ?? 1,
  }
}

export function makeTokenPair(access = 'access-1', refresh = 'refresh-1'): TokenPair {
  return {
    access_token: access,
    refresh_token: refresh,
    token_type: 'Bearer',
    access_expires_at: '2026-01-01T00:00:00Z',
    refresh_expires_at: '2026-01-08T00:00:00Z',
  }
}
