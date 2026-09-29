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

export async function listDictItems(
  dictTypeId: ID,
  status?: DictStatus | null,
): Promise<DictItem[]> {
  // ⚠️ 后端这条端点把列表包在 `items` 键里（`DictItemListResponse`），
  // 不是裸数组 —— 直接把 data 当数组用，`v-for` 会去遍历对象，
  // 渲染出一行全是"—"的怪数据（字段管理里"只有字典没有资源类型"）。
  const data = await http.get<{ items: DictItem[] }>(`/admin/dicts/${dictTypeId}/items`, { status })
  return data.items
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
  // ⚠️ 不能带 `auth: false`。后端 `/dicts/{dict_code}` 的"公开"指**免 API 权限**
  // 但仍需登录（JUDGMENT-7-03：CurrentActorDep 强制认证）。曾按"公开=匿名"
  // 理解写成 auth:false —— 请求永远 401，触发 refresh 后重试仍 401，
  // 重试耗尽 → notifySessionLost → clearSession 把刚登录的令牌**整体清空**，
  // 表现为"登录成功、能看页面，但一刷新/切换就掉回登录页"。
  return http.get<PublicDictResponse>(`/dicts/${dictCode}`)
}

export type DictItems = PageResult<DictItem>
