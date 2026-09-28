/**
 * 展示层格式化工具。
 *
 * 为什么放这里：API 返回的时间是 ISO 8601 UTC 字符串（项目约定 UTC），
 * 直接 `{{ row.created_at }}` 会把 `2026-09-25T15:59:04.177806Z` 原样怼给用户。
 * 展示层转本地时区是**纯展示**职责，不影响任何业务判定。
 */

/** ISO 时间 → `YYYY-MM-DD HH:mm:ss`（本地时区）。非法输入原样返回。 */
export function formatDateTime(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw === '') return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  const pad = (n: number): string => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

const pad2 = (n: number): string => String(n).padStart(2, '0')

/**
 * `datetime-local` 输入值 → UTC ISO 串（后端的时间筛选参数一律是 UTC）。
 *
 * 为什么必须显式转换，而不能像最初那样把 `datetime-local` 的值原样发出去：
 * `<input type="datetime-local">` 的 value 是**不带时区**的本地时间串
 * （`2026-09-28T17:33`）。后端 DTO 收的是 `datetime`，它会解析成一个
 * **naive** datetime，再绑到 `timestamptz` 列上比较 ——
 * 此时由**运行进程/数据库的时区**决定它被当作几点，而不是浏览器时区。
 * 实测（见 `.workbuddy/tmp/probe_tz.py`）：本机 `TimeZone=Asia/Shanghai`，
 * naive `09:35` 被当成 `01:35+00:00`。所以"用户选的本地时间"与
 * "后端理解的时间"只在两边时区恰好相同时才一致 —— 一旦服务器改 UTC，
 * 筛选会整块偏 8 小时，而且**不会报任何错**。
 * 转成带 `Z` 的 UTC 串后，两种时区下结果都相同。
 *
 * 空串 / 非法值返回 `null`（调用方据此不发这个参数，而不是发个空串）。
 */
export function localInputToUtcIso(raw: string): string | null {
  if (raw === '') return null
  // `YYYY-MM-DDTHH:mm` 这种**带时间**的字符串被 `Date` 按**本地时区**解析
  // （只有 `YYYY-MM-DD` 这种纯日期形式才按 UTC），这正是我们要的语义。
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

/** 当前时间，格式化成 `datetime-local` 回填用的本地时间串（精确到分钟）。 */
export function nowAsLocalInput(): string {
  const now = new Date()
  return (
    `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}` +
    `T${pad2(now.getHours())}:${pad2(now.getMinutes())}`
  )
}
