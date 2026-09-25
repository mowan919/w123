import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type { AuditLog, AuditLogPage } from '@/types/log'

/** 日志与链路查询（`08 §8`，Phase 10 补交付）。查这两个域需要 `AUDIT_READ` / `TRACE_READ`。 */

export interface AuditLogListQuery {
  pageNum: number
  pageSize: number
  action?: string | null
  operator_id?: ID | null
  resource_type?: string | null
  resource_id?: ID | null
  result?: string | null
  created_from?: string | null
  created_to?: string | null
}

export function listAuditLogs(query: AuditLogListQuery): Promise<AuditLogPage> {
  return http.get<AuditLogPage>('/admin/audit/logs', query)
}

export function getAuditLog(auditLogId: ID): Promise<AuditLog> {
  return http.get<AuditLog>(`/admin/audit/logs/${auditLogId}`)
}

export interface TraceListQuery {
  pageNum: number
  pageSize: number
}

export interface TraceSummary {
  trace_id: string
  request_id: string | null
  first_seen_at: string
  last_seen_at: string
  counts: Record<string, number>
  total_entries: number
}

export interface TraceEntry {
  log_type: string
  id: ID
  trace_id: string
  request_id: string | null
  created_at: string
  operator_id: ID | null
  operator_username: string | null
  name: string
  result: string | null
  detail: Record<string, unknown>
}

export interface TraceDetail {
  trace_id: string
  entries: TraceEntry[]
}

export function listTraces(query: TraceListQuery): Promise<PageResult<TraceSummary>> {
  return http.get<PageResult<TraceSummary>>('/admin/traces', query)
}

export function getTrace(traceId: string): Promise<TraceDetail> {
  return http.get<TraceDetail>(`/admin/traces/${traceId}`)
}

export type LogsPage = PageResult<AuditLog>
