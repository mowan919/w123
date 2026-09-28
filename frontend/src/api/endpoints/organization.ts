import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type {
  DepartmentCreateRequest,
  DepartmentTreeNode,
  DepartmentUpdateRequest,
  Session,
  SessionPage,
  User,
  UserCreateRequest,
  UserPage,
  UserResetPasswordRequest,
  UserUpdateRequest,
} from '@/types'

/**
 * 组织与用户（`08 §4` / `08 §6`）。
 *
 * 本文件只调用**后端真实存在**的路由。曾经想当然写下的
 * `GET /admin/users/{id}/roles`、`GET /admin/departments`（列表）在后端
 * 并不存在 —— 前端按"应该有"去调，运行时才会拿到 404。
 * 因此这里的每一个路径都来自 `app.openapi()["paths"]` 的逐条核对。
 */

// ---------------------------------------------------------------- 用户

export function listUsers(query: {
  pageNum: number
  pageSize: number
  department_id?: ID | null
  /** `department_id` 是否连带其全部下级部门（DD-07 `DEPARTMENT_CHILDREN` 语义）。 */
  include_sub_departments?: boolean
  status?: string | null
  keyword?: string | null
}): Promise<UserPage> {
  return http.get<UserPage>('/admin/users', query)
}

export function getUser(userId: ID): Promise<User> {
  return http.get<User>(`/admin/users/${userId}`)
}

export function createUser(payload: UserCreateRequest): Promise<User> {
  return http.post<User>('/admin/users', payload)
}

/**
 * 部分更新。
 *
 * 后端用 `model_fields_set` 区分"显式传 null"与"没传"；前端同样只发送
 * **真正改动过**的字段，否则 DTO 上的 `None` 默认值会被当成"清空"
 * （后端 FINDING-9-02 的原话：非全局范围 403 改不动任何字段，
 * 全局范围会静默把用户移出部门）。
 */
export function updateUser(userId: ID, payload: UserUpdateRequest): Promise<User> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<User>(`/admin/users/${userId}`, changed)
}

export function enableUser(userId: ID): Promise<User> {
  return http.post<User>(`/admin/users/${userId}/enable`)
}

export function disableUser(userId: ID): Promise<User> {
  return http.post<User>(`/admin/users/${userId}/disable`)
}

/** 管理员重置口令。新口令由调用方生成后传输，**不回显旧口令**。 */
export function resetUserPassword(userId: ID, payload: UserResetPasswordRequest): Promise<void> {
  return http.post<void>(`/admin/users/${userId}/reset-password`, payload)
}

// ---------------------------------------------------------------- 部门

/** 部门只有**树**这一个查询入口，没有扁平列表端点。 */
export function getDepartmentTree(): Promise<DepartmentTreeNode[]> {
  return http.get<DepartmentTreeNode[]>('/admin/departments/tree')
}

export function createDepartment(payload: DepartmentCreateRequest): Promise<void> {
  return http.post<void>('/admin/departments', payload)
}

export function updateDepartment(
  departmentId: ID,
  payload: DepartmentUpdateRequest,
): Promise<void> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<void>(`/admin/departments/${departmentId}`, changed)
}

export function disableDepartment(departmentId: ID): Promise<void> {
  return http.post<void>(`/admin/departments/${departmentId}/disable`)
}

// ---------------------------------------------------------------- 会话

export interface SessionListQuery {
  pageNum: number
  pageSize: number
  /**
   * 在线状态三态。
   *
   * `null` / 省略 = **不筛选**（返回全部，含已撤销与已过期）；`true` = 仅在线；
   * `false` = 仅离线（在线条件的补集）。
   *
   * ⚠️ 这里必须用 `null` 表示"全部"，不能用 `false` —— `false` 在后端是
   * "只要离线的"，与"不筛选"是两回事。界面上的 `<select>` 空选项 value 只能是
   * 空串，因此下面 `listSessions` 里做了 `''` → `null` 的显式映射。
   */
  online?: boolean | null
  /** IP 子串（模糊，大小写不敏感）。 */
  ip?: string | null
  /** 设备 / User-Agent 子串（同时匹配两者）。 */
  device?: string | null
  /** 登录时间下界（含），ISO 8601。 */
  login_from?: string | null
  /** 登录时间上界（含），ISO 8601。 */
  login_to?: string | null
}

export function listSessions(query: SessionListQuery): Promise<SessionPage> {
  return http.get<SessionPage>('/admin/sessions', query)
}

export function revokeSession(sessionId: ID): Promise<void> {
  return http.post<void>(`/admin/sessions/${sessionId}/revoke`)
}

export function listUserSessions(
  userId: ID,
  query: SessionListQuery,
): Promise<PageResult<Session>> {
  return http.get<PageResult<Session>>(`/admin/users/${userId}/sessions`, query)
}

export function revokeAllUserSessions(userId: ID): Promise<{ revoked_count: number }> {
  return http.post<{ revoked_count: number }>(`/admin/users/${userId}/sessions/revoke-all`)
}
