import type { DateTime, ID, PageResult } from './common'

/** 参数类型（`SystemParamType`）。 */
export type SystemParamType = 'STRING' | 'INT' | 'BOOL'

/** 参数状态。 */
export type SystemParamStatus = 'ACTIVE' | 'DISABLED'

/**
 * 系统参数（`SystemParamResponse`）。
 *
 * 安全约定：审计侧**不记录参数值**，因此前端也不提供"查看历史值"的入口。
 * `param_value` 可能承载密钥类配置，而审计 append-only 保留 2 年 ——
 * 一旦可回看就是不可撤回的泄漏通道。
 */
export interface SystemParam {
  id: ID
  param_key: string
  param_name: string
  param_type: 'STRING' | 'INT' | 'BOOL'
  param_value: string | null
  default_value: string
  /** 实际生效值：优先取 `param_value`，缺失时回退 `default_value`。 */
  effective_value: string
  status: 'ACTIVE' | 'DISABLED'
  description: string | null
  created_at: DateTime
  updated_at: DateTime
}

export type SystemParamPage = PageResult<SystemParam>

/** 创建请求。`default_value` 必填（`05 §5`：参数必须有默认值）。 */
export interface SystemParamCreateRequest {
  param_key: string
  param_name: string
  param_type: SystemParamType
  default_value: string
  param_value?: string | null
  description?: string | null
  status?: 'ACTIVE' | 'DISABLED'
}

/**
 * 更新请求（`param_key` / `param_type` 不可改）。
 *
 * `clear_value` 表示"清空当前值、回落到 `default_value`"，与提供
 * `param_value` **互斥** —— 两边同时给时后端会拒绝，所以前端的"清空"
 * 动作只提交 `clear_value: true`，不夹带值。
 */
export interface SystemParamUpdateRequest {
  param_name?: string | null
  param_type?: SystemParamType | null
  default_value?: string | null
  param_value?: string | null
  clear_value?: boolean
  description?: string | null
  status?: 'ACTIVE' | 'DISABLED' | null
}
