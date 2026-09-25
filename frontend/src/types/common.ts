/**
 * 通用类型：Envelope、分页、ID 约定。
 *
 * 三个冻结约定（不得在别处重新定义）：
 * 1. `ID` 一律 `string` —— 后端 BIGINT 经 JSON 序列化为字符串
 *    （FE-00 §5、FE-10 §4）。禁止 `Number(id)`、禁止 `number` 承载业务 ID，
 *    因为超出 `Number.MAX_SAFE_INTEGER` 时会静默丢位。
 * 2. Response Envelope 固定 `{ code, message, data }`（FE-10 §3）。
 * 3. 分页请求 `pageNum` / `pageSize`，响应 `{ list, total, pageNum, pageSize }`
 *    （FE-09 §6：不得在前端重新定义分页语义）。
 */

/** 业务 ID（后端 BIGINT）。 */
export type ID = string

/** 时间戳：后端统一 UTC 并序列化为 ISO-8601 字符串。 */
export type DateTime = string

/** API 响应信封。失败时 `data` 为 `null`（`app.core.response.error_response`）。 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T | null
}

/** 分页请求参数。 */
export interface PageParams {
  pageNum: number
  pageSize: number
}

/** 分页响应。字段名与后端 DTO 逐字一致。 */
export interface PageResult<T> {
  /** 遮蔽内建 `list`：这里的 `list` 是**字段名**，不是数组字面量语法。 */
  list: T[]
  total: number
  pageNum: number
  pageSize: number
}

/** 下拉 / 摘要用的最小资源形状。 */
export interface OptionLike {
  id: ID
  name: string
  disabled?: boolean
}
