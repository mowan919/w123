import type { DateTime, ID, PageResult } from './common'

/** 字典类型（`DictTypeResponse`）。 */
export interface DictType {
  id: ID
  dict_code: string
  dict_name: string
  description: string | null
  status: 'ACTIVE' | 'DISABLED'
  created_at: DateTime
  updated_at: DateTime
}

export type DictTypePage = PageResult<DictType>

/** 删除时回带被连带逻辑删除的项数。 */
export interface DictTypeDeleteResult {
  id: ID
  dict_code: string
  deleted_item_count: number
}

/** 字典状态（`DictStatus`）。软删除感知的唯一性由库层 partial index 保证。 */
export type DictStatus = 'ACTIVE' | 'DISABLED'

export interface DictTypeCreateRequest {
  dict_code: string
  dict_name: string
  description?: string | null
  status?: 'ACTIVE' | 'DISABLED'
}

/**
 * 更新请求。
 *
 * 有意**不含** `dict_code`：编码是对外稳定标识（公开查询按它取字典），
 * 改码会让调用方静默失效 —— 后端不提供这条路径，前端也不绕过。
 */
export interface DictTypeUpdateRequest {
  dict_name?: string | null
  description?: string | null
  status?: 'ACTIVE' | 'DISABLED' | null
}

export interface DictItemCreateRequest {
  item_label: string
  item_value: string
  item_code: string
  sort_order?: number
  status?: 'ACTIVE' | 'DISABLED'
  is_default?: boolean
  description?: string | null
}

export interface DictItemUpdateRequest {
  item_label?: string | null
  item_value?: string | null
  item_code?: string | null
  sort_order?: number | null
  status?: 'ACTIVE' | 'DISABLED' | null
  is_default?: boolean | null
  description?: string | null
}

/** 字典项（`DictItemResponse`）。 */
export interface DictItem {
  id: ID
  dict_type_id: ID
  item_label: string
  item_value: string
  item_code: string
  sort_order: number
  status: 'ACTIVE' | 'DISABLED'
  is_default: boolean
  description: string | null
  created_at: DateTime
  updated_at: DateTime
}

export type DictItemList = DictItem[]

/** 公开查询（`PublicDictResponse`）与后台 DTO 形状不同，不要混用。 */
export interface PublicDictItem {
  item_label: string
  item_value: string
  item_code: string
  sort_order: number
  is_default: boolean
  description: string | null
}

export interface PublicDictResponse {
  dict_code: string
  dict_name: string
  description: string | null
  items: PublicDictItem[]
}
