import type { DateTime, ID, PageResult } from './common'
import type { DataScopePolicy, FieldAccessLevel } from './permission'

/** 角色（`08 §7`）。 */

export interface Role {
  id: ID
  role_code: string
  role_name: string
  status: 'ACTIVE' | 'DISABLED'
  description: string | null
  data_scope: DataScopePolicy
  created_at: DateTime
  updated_at: DateTime
}

export type RolePage = PageResult<Role>

export interface RoleCreateRequest {
  role_code: string
  role_name: string
  description?: string | null
  status: 'ACTIVE' | 'DISABLED'
}

/** 设置数据范围的请求体（DD-07）。 */
export interface RoleDataScopeRequest {
  data_scope: DataScopePolicy
  /** 仅 CUSTOM 时有效，其余策略必须为**空数组**。 */
  department_ids: ID[]
}

export interface RoleUpdateRequest {
  role_name?: string | null
  description?: string | null
  status?: 'ACTIVE' | 'DISABLED' | null
}

/** 数据范围配置（`RoleDataScopeResponse`）。 */
export interface RoleDataScope {
  role_id: ID
  data_scope: DataScopePolicy
  /** 三态：`null` 不限制、`[]` 全拒、非空允许集合。 */
  department_ids: ID[]
}

/** 字段权限项（`RoleFieldPermissionItem`）。 */
export interface RoleFieldPermissionItem {
  resourceId: ID
  accessLevel: FieldAccessLevel
}
