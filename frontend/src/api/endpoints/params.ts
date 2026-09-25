import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type {
  SystemParam,
  SystemParamCreateRequest,
  SystemParamPage,
  SystemParamStatus,
  SystemParamUpdateRequest,
} from '@/types'

/** 系统参数（`08 §9`）。与字典是两套东西，不共用存储也不共用页面语义。 */

export interface SystemParamListQuery {
  pageNum: number
  pageSize: number
  keyword?: string | null
  status?: SystemParamStatus | null
}

export function listSystemParams(query: SystemParamListQuery): Promise<SystemParamPage> {
  return http.get<SystemParamPage>('/admin/params', query)
}

export function createSystemParam(payload: SystemParamCreateRequest): Promise<SystemParam> {
  return http.post<SystemParam>('/admin/params', payload)
}

export function updateSystemParam(
  paramId: ID,
  payload: SystemParamUpdateRequest,
): Promise<SystemParam> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  // `clear_value` 保留在对象里一起提交：它是"清空值"这个动作的显式表达，
  // 让调用方一眼看到这次更新到底有没有清值，而不是靠默认值的巧合。
  return http.put<SystemParam>(`/admin/params/${paramId}`, changed)
}

export function deleteSystemParam(paramId: ID): Promise<void> {
  return http.delete<void>(`/admin/params/${paramId}`)
}

export type SystemParams = PageResult<SystemParam>
