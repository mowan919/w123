import type { DateTime, ID, PageParams, PageResult } from './common'
// ---------------------------------------------------------------- 用户

export interface UserListQuery extends PageParams {
  department_id?: ID | null
  status?: 'ACTIVE' | 'DISABLED' | 'LOCKED' | null
  keyword?: string | null
}

/** 用户视图。刻意**不含** password / password_hash / 任何令牌字段。 */
export interface User {
  id: ID
  username: string
  display_name: string
  /** 手机号是真实值（后端响应返回真实值，脱敏只作用于日志侧）。 */
  phone: string | null
  email: string | null
  department_id: ID | null
  status: 'ACTIVE' | 'DISABLED' | 'LOCKED'
  failed_login_count: number
  locked_until: DateTime | null
  password_changed_at: DateTime | null
  must_change_password: boolean
  created_at: DateTime
  updated_at: DateTime
}

export type UserPage = PageResult<User>

export interface UserCreateRequest {
  username: string
  password: string
  display_name: string
  department_id?: ID | null
  phone?: string | null
  email?: string | null
  role_ids?: ID[]
}

/** 部分更新：未出现在 `model_fields_set` 里的字段保持原值，不得被当成清空。 */
export interface UserUpdateRequest {
  username?: string | null
  display_name?: string | null
  phone?: string | null
  email?: string | null
  department_id?: ID | null
}

export interface UserResetPasswordRequest {
  new_password: string
}

export interface RoleSummary {
  id: ID
  role_code: string
  role_name: string
  status: 'ACTIVE' | 'DISABLED'
}

// ---------------------------------------------------------------- 部门

export interface Department {
  id: ID
  parent_id: ID | null
  department_code: string
  department_name: string
  status: 'ACTIVE' | 'DISABLED'
  created_at: DateTime
  updated_at: DateTime
}

export interface DepartmentTreeNode {
  id: ID
  parent_id: ID | null
  department_code: string
  department_name: string
  status: 'ACTIVE' | 'DISABLED'
  children: DepartmentTreeNode[]
}

export interface DepartmentCreateRequest {
  department_code: string
  department_name: string
  parent_id?: ID | null
}

export interface DepartmentUpdateRequest {
  department_code?: string | null
  department_name?: string | null
  parent_id?: ID | null
}
