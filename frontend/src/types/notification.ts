import type { DateTime, ID, PageResult } from './common'

/**
 * 站内通知的类型契约（`DESIGN-DECISIONS §32`）。
 *
 * ⚠️ 实体类型叫 `NotificationItem` 而**不是** `Notification`：
 * 后者是 DOM 的浏览器通知 API（`new Notification(...)`）的全局类型名。
 * 同名会让"在某个模块里想用 DOM 通知"变成一个要小心 import 顺序的坑，
 * 而且 TS 不会报错 —— 只会静默解析成我们的接口。少一个同名，少一类怪问题。
 */

/** 通知分类：`SYSTEM` 由服务端事件产生，`ANNOUNCEMENT` 由管理员发布。 */
export type NotificationCategory = 'SYSTEM' | 'ANNOUNCEMENT'

/** 轻重。**只影响展示**（颜色 / 是否置顶），不参与任何判定。 */
export type NotificationLevel = 'INFO' | 'WARNING' | 'IMPORTANT'

/** 公告受众。`ROLE` 按 `user_roles` 的**直接分配**判定（不含角色继承）。 */
export type AnnouncementAudience = 'ALL' | 'ROLE'

/** 一条站内通知（收件箱里的一行）。 */
export interface NotificationItem {
  id: ID
  category: NotificationCategory
  /** 系统事件码（`SESSION_SUPERSEDED` 等）；公告为 `null`。 */
  event_code: string | null
  /** 来源公告 ID；系统消息为 `null`。 */
  announcement_id: ID | null
  title: string
  body: string | null
  /** 点击后跳转的前端路由路径。`null` = 不可跳转。 */
  link: string | null
  level: NotificationLevel
  /**
   * 已读时间。**未读的唯一判据是 `read_at === null`** ——
   * 后端刻意不下发 `is_read` 布尔（`read_at` 比布尔多一个"什么时候读的"，
   * 两个字段不一致时无人能判谁对）。
   */
  read_at: DateTime | null
  created_at: DateTime
}

/**
 * 收件箱分页响应。
 *
 * `unread` 是**未读总数**（不是本页未读数）：角标与列表在界面上总是同时
 * 出现，后端把它放在同一个响应里，两者因此必然同源 —— 分两次请求会让
 * "列表里有未读、角标却是 0"这种不一致稳定地出现在慢网络上。
 */
export type NotificationPage = PageResult<NotificationItem> & { unread: number }

/** 角标响应。 */
export interface NotificationUnreadCount {
  unread: number
}

/** 全部已读的结果：`updated` 是本次真正被标记的条数。 */
export interface MarkAllReadResult {
  updated: number
}

/** 一条已发布公告。 */
export interface Announcement {
  id: ID
  title: string
  body: string | null
  level: NotificationLevel
  audience_type: AnnouncementAudience
  audience_role_id: ID | null
  /** 发布那一刻的收件人数（历史事实，不随用户增减变化）。 */
  recipient_count: number
  /**
   * 发布人用户名**快照**。刻意没有 `created_by`（裸雪花 ID）：
   * 列表里显示一串数字对使用者毫无意义。
   */
  created_by_username: string
  created_at: DateTime
}

export type AnnouncementPage = PageResult<Announcement>

/** 发布公告的请求体。 */
export interface AnnouncementCreateRequest {
  title: string
  body?: string | null
  level: AnnouncementLevelInput
  audience_type: AnnouncementAudience
  audience_role_id?: ID | null
}

/** 与 `NotificationLevel` 同形，单独起名是为了让"输入"与"展示"两处可独立演进。 */
export type AnnouncementLevelInput = NotificationLevel

/** 发布结果。 */
export interface AnnouncementPublishResult {
  announcement: Announcement
  recipient_count: number
}

/** 撤回结果：`purged` 是被一并撤回的收件箱行数。 */
export interface AnnouncementRevokeResult {
  id: ID
  purged: number
}
