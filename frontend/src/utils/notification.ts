import type { AnnouncementAudience, NotificationCategory, NotificationLevel } from '@/types'
import { CSS_VARS } from '@/styles/theme'

/**
 * 站内通知的视觉表达与**回落文案**（`DESIGN-DECISIONS §32`）。
 *
 * 为什么轻重色复用既有语义色而不是新增一套
 * --------------------------------------
 * 通知的轻重（普通 / 提醒 / 重要）要表达的是"需要多快看"，
 * 与系统的告警色是同一件事。再拉一套"通知专用色"会让同一个
 * "重要"在页面上有两种红，运营改配色时也必然只改一处。
 * 因此直接复用 `info` / `warn` / `danger` 三组。
 *
 * 用 `Record<NotificationLevel, ...>` 而不是带 fallback 的函数：
 * 新增第四种轻重时**类型标注会直接编译失败**，逼着补色 ——
 * 带 fallback 的写法只会静默退化成灰色（与 `utils/resourceType.ts`
 * 同一取向与同一理由）。
 */

export interface NotificationLevelStyle {
  /** 文字色。 */
  color: string
  /** 底色（同色系浅底）。 */
  background: string
  /** 前端**回落**文案；真正的显示文案来自字典 `notification_level`。 */
  label: string
}

export const NOTIFICATION_LEVEL_STYLE: Record<NotificationLevel, NotificationLevelStyle> = {
  INFO: { color: CSS_VARS.info, background: CSS_VARS.infoWeak, label: '普通' },
  WARNING: { color: CSS_VARS.warn, background: CSS_VARS.warnWeak, label: '提醒' },
  IMPORTANT: { color: CSS_VARS.danger, background: CSS_VARS.dangerWeak, label: '重要' },
}

export function notificationLevelStyle(level: NotificationLevel): NotificationLevelStyle {
  return NOTIFICATION_LEVEL_STYLE[level]
}

/**
 * 分类的**回落**文案（字典 `notification_category` 取不到时用）。
 *
 * 为什么这里可以是"只会回落的常量"而不是 `Record<...>` 强约束：
 * 分类在界面上只出现在消息中心的分流标签上，取值来自后端，
 * 少一个只表现为标签显示成英文 —— 而轻重那套是**底色**，
 * 少一个会让一整行看起来"没有状态"，两者后果不对称。
 * 即便这样，也仍然写成 `Record` 让新增分类在编译期可见。
 */
export const NOTIFICATION_CATEGORY_FALLBACK: Record<NotificationCategory, string> = {
  SYSTEM: '系统消息',
  ANNOUNCEMENT: '公告',
}

/**
 * 公告受众的文案（`ALL` / `ROLE`）。
 *
 * 这里**没有对应的字典**：受众是发布表单里紧挨着角色下拉框的一个开关，
 * 它的两种取值在界面上各自带着明确的补充说明（"给所有人""只给选中角色"），
 * 再放进字典只会多一次请求与一层"字典没配就显示 ROLE"的风险。
 * 与分类 / 轻重不同：那两者是**数据的属性**（可能随业务新增取值），
 * 这是**发布动作的形态**（只有这两种可能），形态不会靠改字典来扩展。
 */
export const ANNOUNCEMENT_AUDIENCE_FALLBACK: Record<AnnouncementAudience, string> = {
  ALL: '全体用户',
  ROLE: '指定角色',
}

/**
 * 相对时间的兜底（`刚刚` / `N 分钟前` / …）。
 *
 * 为什么需要它而不是直接用 `formatDateTime`
 * --------------------------------------
 * 面板里一行的高度有限，绝对时间（`2026-09-29 14:03:22`）会把标题挤到
 * 换行；而"3 分钟前"才是看通知时真正想知道的信息（"这是不是刚发生的"）。
 * 超过 7 天回落到绝对时间：那时"多少天前"已经不如日期直观。
 *
 * 时间戳由后端给的是 **UTC**，字符串里带 `Z`；`new Date()` 会正确解析。
 * 这里不做时区偏移计算（那属于 `utils/format.ts` 的职责），
 * 只做"两个绝对时刻的差"，因此与时区无关。
 */
export function relativeTime(raw: string, now: Date = new Date()): string {
  const target = new Date(raw)
  if (Number.isNaN(target.getTime())) return raw
  const diffMs = now.getTime() - target.getTime()
  // 未来时间（服务端与客户端时钟偏差）不显示"负几分钟前"。
  if (diffMs < 0) return '刚刚'

  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`

  const days = Math.floor(hours / 24)
  if (days <= 7) return `${days} 天前`

  // 超过一周回落到"月-日"而不回落"几天前"：到那个尺度上，
  // "23 天前"需要心算，而"09-06"一眼就能与自己的记忆对上。
  // 刻意不显示年份：需要看年份的消息应当在消息中心里看（那里有完整时间）。
  return `${pad(target.getMonth() + 1)}-${pad(target.getDate())}`
}

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}
