import { http } from '../client'
import type { PermissionContract } from '@/types'

/** `GET /auth/permissions` —— 前端权限的唯一来源（FE-00 §4 的权限链）。 */

/**
 * 拉当前用户的有效权限契约（七段）。
 *
 * 不写审计：与 `INTERIM-8-02`（公开字典查询）同一取向 —— 每次开页面都调，
 * 逐次审计会把审计表变成访问日志，稀释 FAILURE 信号。
 */
export function getPermissionContract(): Promise<PermissionContract> {
  return http.get<PermissionContract>('/auth/permissions')
}
