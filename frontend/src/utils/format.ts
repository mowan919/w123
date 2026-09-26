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
