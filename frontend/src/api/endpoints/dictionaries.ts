import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type {
  DictItem,
  DictItemCreateRequest,
  DictItemUpdateRequest,
  DictStatus,
  DictType,
  DictTypeCreateRequest,
  DictTypeDeleteResult,
  DictTypePage,
  DictTypeUpdateRequest,
  PublicDictResponse,
} from '@/types'

/** 字典（`08 §9`，INTERIM-7-01/02）。 */

export interface DictTypeListQuery {
  pageNum: number
  pageSize: number
  keyword?: string | null
  status?: DictStatus | null
}

export function listDictTypes(query: DictTypeListQuery): Promise<DictTypePage> {
  return http.get<DictTypePage>('/admin/dicts', query)
}

export function createDictType(payload: DictTypeCreateRequest): Promise<DictType> {
  return http.post<DictType>('/admin/dicts', payload)
}

export function updateDictType(
  dictTypeId: ID,
  payload: DictTypeUpdateRequest,
): Promise<DictType> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<DictType>(`/admin/dicts/${dictTypeId}`, changed)
}

/** 删除会把该字典下的项一并逻辑删除，响应里带回数量。 */
export function deleteDictType(dictTypeId: ID): Promise<DictTypeDeleteResult> {
  return http.delete<DictTypeDeleteResult>(`/admin/dicts/${dictTypeId}`)
}

export function listDictItems(dictTypeId: ID, status?: DictStatus | null): Promise<DictItem[]> {
  return http.get<DictItem[]>(`/admin/dicts/${dictTypeId}/items`, { status })
}

export function createDictItem(dictTypeId: ID, payload: DictItemCreateRequest): Promise<DictItem> {
  return http.post<DictItem>(`/admin/dicts/${dictTypeId}/items`, payload)
}

export function updateDictItem(
  dictTypeId: ID,
  itemId: ID,
  payload: DictItemUpdateRequest,
): Promise<DictItem> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<DictItem>(`/admin/dicts/${dictTypeId}/items/${itemId}`, changed)
}

export function deleteDictItem(dictTypeId: ID, itemId: ID): Promise<void> {
  return http.delete<void>(`/admin/dicts/${dictTypeId}/items/${itemId}`)
}

/** 公开字典查询（无需认证）。业务页面统一走它取枚举，不在各页面硬编码。 */
export function getPublicDict(dictCode: string): Promise<PublicDictResponse> {
  return http.get<PublicDictResponse>(`/dicts/${dictCode}`, undefined, { auth: false })
}

export type DictItems = PageResult<DictItem>
