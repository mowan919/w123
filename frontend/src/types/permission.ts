import type { DateTime, ID } from './common'

/**
 * 权限资源类型（`PermissionResourceType`）。
 * 这五值来自 `03` 的资源模型，是**冻结**契约。
 */
export type ResourceType = 'PAGE' | 'MENU' | 'BUTTON' | 'API' | 'FIELD'

/** 字段访问级别（`FieldAccessLevel`）—— FE-05 §3 的四态。 */
export type FieldAccessLevel = 'VISIBLE' | 'HIDDEN' | 'READ_ONLY' | 'EDITABLE'

/**
 * 参与"有没有"判定的四类权限资源。
 *
 * `03` 的资源模型有五值，`FIELD` **不在**这里：它表达的是四态访问级别
 * （VISIBLE / HIDDEN / READ_ONLY / EDITABLE），不是"授没授"。
 * 把两类语义压进同一个二态勾选框，就得在界面上额外发明一个
 * "半选 = 只读"的约定 —— 那是自造规则。
 *
 * 四类二元授权与后端 `role_permissions` 的存储形状一一对应。
 */
export type GrantKind = 'PAGE' | 'MENU' | 'BUTTON' | 'API'

/** 固定顺序：遍历、逐类提交、结果提示都用它，避免各处各写一遍数组。 */
export const GRANT_KINDS: GrantKind[] = ['PAGE', 'MENU', 'BUTTON', 'API']

/** 四类已授权 id 集合（与后端 `RolePermissionView` 同形）。 */
export interface GrantSelection {
  PAGE: ID[]
  MENU: ID[]
  BUTTON: ID[]
  API: ID[]
}

export function emptySelection(): GrantSelection {
  return { PAGE: [], MENU: [], BUTTON: [], API: [] }
}

/** 类别的中文名（权限树标签、逐类保存的成败提示共用一份）。 */
export const GRANT_KIND_LABEL: Record<GrantKind, string> = {
  PAGE: '页面',
  MENU: '菜单',
  BUTTON: '按钮',
  API: '接口',
}

export interface PermissionPageItem {
  id: ID
  /** 资源编码，权限判定用的就是这个值。 */
  code: string
  name: string
  route_path: string | null
  component_path: string | null
  sort_order: number
}

export interface PermissionMenuItem {
  id: ID
  code: string
  name: string
  icon: string | null
  parent_id: ID | null
  sort_order: number
  page_ids: ID[]
}

export interface PermissionButtonItem {
  id: ID
  code: string
  name: string
  parent_id: ID | null
  sort_order: number
}

export interface PermissionApiItem {
  id: ID
  code: string
  name: string
  api_method: string | null
  api_path: string | null
  parent_id: ID | null
}

export interface PermissionFieldItem {
  id: ID
  code: string
  field_key: string
  owner_resource_id: ID | null
  access_level: FieldAccessLevel
}

/** 数据范围（FE-05 §4）。CUSTOM 的具体存储由后端决定，前端不设计替代模型。 */
export interface PermissionDataScope {
  /** `null` = 部门维度不限制（ALL / SUPER_ADMIN）；`[]` = 全拒。两者语义相反。 */
  policy: DataScopePolicy | null
  department_ids: ID[] | null
  include_self: boolean
}

export type DataScopePolicy = 'ALL' | 'DEPARTMENT' | 'DEPARTMENT_CHILDREN' | 'SELF' | 'CUSTOM'

/** `GET /auth/permissions` 响应的七段契约。 */
export interface PermissionContract {
  user_id: ID
  is_super_admin: boolean
  direct_role_ids: ID[]
  inherited_role_ids: ID[]
  pages: PermissionPageItem[]
  menus: PermissionMenuItem[]
  buttons: PermissionButtonItem[]
  apis: PermissionApiItem[]
  fields: PermissionFieldItem[]
  data_scope: PermissionDataScope
  permission_version: number
}

/** `GET /auth/permissions` 原始响应（外层 Envelope 之后）。 */
export type PermissionContractResponse = PermissionContract

/** 角色权限视图（`GET /admin/roles/{role_id}/permissions`）。 */
export interface RolePermissionView {
  role_id: ID
  page_ids: ID[]
  menu_ids: ID[]
  button_ids: ID[]
  api_ids: ID[]
  field_levels: Record<string, FieldAccessLevel>
}

/** 权限资源（`GET /admin/permission-resources*`）。 */
export interface PermissionResource {
  id: ID
  resource_type: ResourceType
  resource_code: string
  resource_name: string
  parent_id: ID | null
  sort_order: number
  status: 'ACTIVE' | 'DISABLED'
  route_path: string | null
  component_path: string | null
  icon: string | null
  api_method: string | null
  api_path: string | null
  field_key: string | null
  owner_resource_id: ID | null
  created_at: DateTime
  updated_at: DateTime
}

export interface PermissionResourceTreeNode {
  resource: PermissionResource
  children: PermissionResourceTreeNode[]
}

/** 资源状态。软删除感知的唯一性由库层 partial index 保证，前端不重复实现。 */
export type PermissionStatus = 'ACTIVE' | 'DISABLED'

/** `PUT /admin/permission-resources/{id}` 的请求体；未出现的字段保持原值。 */
export interface PermissionResourceUpdateRequest {
  resource_name?: string | null
  sort_order?: number | null
  status?: PermissionStatus | null
  route_path?: string | null
  component_path?: string | null
  icon?: string | null
  api_method?: string | null
  api_path?: string | null
  field_key?: string | null
}
