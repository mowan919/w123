import { http } from '../client'
import type { ID } from '@/types/common'
import type {
  Announcement,
  AnnouncementCreateRequest,
  AnnouncementPage,
  AnnouncementPublishResult,
  AnnouncementRevokeResult,
  MarkAllReadResult,
  NotificationCategory,
  NotificationItem,
  NotificationPage,
  NotificationUnreadCount,
} from '@/types'

/**
 * 站内通知（`DESIGN-DECISIONS §32`）。
 *
 * 两个前缀，与后端的两组端点一一对应：
 *
 * | 用途 | 前缀 | 后端挂载 |
 * |---|---|---|
 * | 我的收件箱 | `/auth/notifications*` | 认证域（与 `/auth/me`、`/auth/mfa*` 同类） |
 * | 公告管理 | `/admin/notifications/announcements*` | admin 资源域（需权限位） |
 *
 * 收件箱在前端写的是 `/auth/...` 而不是 `/admin/...`，是因为后端**刻意**
 * 把它放在认证域：任何已认证用户都有自己的一份消息，不能被 admin 域的
 * API 权限位卡住（详见后端 `endpoints/notifications.py` 的模块文档）。
 * 写错前缀的表现是所有用户都看不到自己的消息（403），
 * `tests/api/notifications.spec.ts` 钉住这两个前缀。
 */

export interface NotificationListQuery {
  pageNum: number
  pageSize: number
  /** 只看未读。 */
  unreadOnly?: boolean
  /** 按分类过滤；`null` = 全部。 */
  category?: NotificationCategory | null
}

export function listMyNotifications(query: NotificationListQuery): Promise<NotificationPage> {
  return http.get<NotificationPage>('/auth/notifications', query)
}

/** 角标专用：只取一个整数。 */
export function fetchUnreadCount(): Promise<NotificationUnreadCount> {
  return http.get<NotificationUnreadCount>('/auth/notifications/unread-count')
}

export function markNotificationRead(notificationId: ID): Promise<NotificationItem> {
  return http.post<NotificationItem>(`/auth/notifications/${notificationId}/read`)
}

export function markAllNotificationsRead(): Promise<MarkAllReadResult> {
  return http.post<MarkAllReadResult>('/auth/notifications/read-all')
}

// ---------------------------------------------------------------- 公告管理

export interface AnnouncementListQuery {
  pageNum: number
  pageSize: number
}

export function listAnnouncements(query: AnnouncementListQuery): Promise<AnnouncementPage> {
  return http.get<AnnouncementPage>('/admin/notifications/announcements', query)
}

export function publishAnnouncement(
  payload: AnnouncementCreateRequest,
): Promise<AnnouncementPublishResult> {
  return http.post<AnnouncementPublishResult>('/admin/notifications/announcements', payload)
}

export function revokeAnnouncement(announcementId: ID): Promise<AnnouncementRevokeResult> {
  return http.post<AnnouncementRevokeResult>(
    `/admin/notifications/announcements/${announcementId}/revoke`,
  )
}

export type AnnouncementList = Announcement[]
