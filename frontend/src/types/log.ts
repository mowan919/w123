import type { DateTime, ID, PageResult } from './common'

/** 审计日志（`AuditLogResponse`）。 */
export interface AuditLog {
  id: ID
  trace_id: string | null
  request_id: string | null
  operator_id: ID | null
  operator_username: string | null
  action: string
  resource_type: string
  resource_id: ID | null
  before_data: Record<string, unknown> | null
  after_data: Record<string, unknown> | null
  result: string
  error_code: number | null
  ip: string | null
  user_agent: string | null
  created_at: DateTime
}

export type AuditLogPage = PageResult<AuditLog>
