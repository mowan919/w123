import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type {
  DataScopePolicy,
  FieldAccessLevel,
  Role,
  RoleCreateRequest,
  RoleDataScope,
  RolePage,
  RolePermissionView,
  RoleUpdateRequest,
} from '@/types'

/** 角色（`08 §7`）。 */

export interface RoleListQuery {
  pageNum: number
  pageSize: number
  keyword?: string | null
  status?: 'ACTIVE' | 'DISABLED' | null
}

export function listRoles(query: RoleListQuery): Promise<RolePage> {
  return http.get<RolePage>('/admin/roles', query)
}

export function createRole(payload: RoleCreateRequest): Promise<Role> {
  return http.post<Role>('/admin/roles', payload)
}

export function updateRole(roleId: ID, payload: RoleUpdateRequest): Promise<Role> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<Role>(`/admin/roles/${roleId}`, changed)
}

/** 删除是 `POST .../delete`，不是 `DELETE`（后端冻结的路径）。 */
export function deleteRole(roleId: ID): Promise<void> {
  return http.post<void>(`/admin/roles/${roleId}/delete`)
}

// ---------------------------------------------------------------- 权限

export function getRolePermissions(roleId: ID): Promise<RolePermissionView> {
  return http.get<RolePermissionView>(`/admin/roles/${roleId}/permissions`)
}

/** 提交某类资源的授权 ID 集合，语义为"整体覆盖"。 */
export function setRolePagePermissions(roleId: ID, resourceIds: ID[]): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/permissions/pages`, { resourceIds })
}

export function setRoleMenuPermissions(roleId: ID, resourceIds: ID[]): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/permissions/menus`, { resourceIds })
}

export function setRoleButtonPermissions(roleId: ID, resourceIds: ID[]): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/permissions/buttons`, { resourceIds })
}

export function setRoleApiPermissions(roleId: ID, resourceIds: ID[]): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/permissions/apis`, { resourceIds })
}

export interface RoleFieldPermissionItem {
  resourceId: ID
  accessLevel: FieldAccessLevel
}

export function setRoleFieldPermissions(
  roleId: ID,
  fields: RoleFieldPermissionItem[],
): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/permissions/fields`, { fields })
}

// ---------------------------------------------------------------- 数据范围

export function getRoleDataScope(roleId: ID): Promise<RoleDataScope> {
  return http.get<RoleDataScope>(`/admin/roles/${roleId}/data-scope`)
}

/**
 * 设置数据范围（DD-07）。
 *
 * ⚠️ 请求体里的 `department_ids` 是**普通数组**，不是契约里的三态：
 * 后端 `RoleDataScopeRequest` 规定非 CUSTOM 策略必须携带**空数组**，
 * 携带非空集合会被服务层拒绝（避免"以为已限定、实际未限定"）。
 * 契约层那个 `null` / `[]` 三态是另一回事 —— 两者不可混用。
 */
export function setRoleDataScope(
  roleId: ID,
  payload: { data_scope: DataScopePolicy; department_ids: ID[] },
): Promise<void> {
  return http.put<void>(`/admin/roles/${roleId}/data-scope`, payload)
}

/** 角色分页类型在业务侧的别名。 */
export type RolesPage = PageResult<Role>
