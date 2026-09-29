import { beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '@/api/client'
import {
  fetchUnreadCount,
  listAnnouncements,
  listMyNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  publishAnnouncement,
  revokeAnnouncement,
} from '@/api/endpoints/notifications'
import type { AuthBridge } from '@/api/client'
import { fail, ok, stubFetch } from '../helpers/fetchMock'
import { makeTokenPair } from '../helpers/fixtures'
import type { Announcement, NotificationPage } from '@/types'

/**
 * 站内通知端点的**前缀与信封**（`DESIGN-DECISIONS §32`）。
 *
 * 为什么这一条值得单独一个 spec：下面两组端点挂在**两个不同的域**上，
 * 而前缀写错在类型检查、构建、lint 三道关卡里都**不会**报错 —— 只有真跑
 * 起来才看到 404 / 403。两个方向的写错各有一种特有的表现：
 *
 * - 收件箱若写成 `/admin/notifications`：所有用户都看不到自己的消息（403），
 *   因为 admin 域要求 API 权限位，而普通用户没有。
 * - 公告管理若写成 `/auth/notifications/announcements`：任何登录用户
 *   都能发全员公告（越权）。
 *
 * 这两条都不会在界面上留下一点异常痕迹（前者看起来"就是没有消息"）。
 * 项目里同类事故已经出过一次（`organization.ts` 记录的
 * `GET /admin/users/{id}/roles` 并不存在）。
 */

beforeEach(() => {
  const bridge: AuthBridge = {
    getAccessToken: () => 'access-1',
    getRefreshToken: () => 'refresh-1',
    refresh: async () => makeTokenPair(),
    onSessionLost: () => undefined,
  }
  configureClient({ baseUrl: '/api/v1/', bridge })
})

function page(): NotificationPage {
  return {
    list: [
      {
        id: '900001',
        category: 'SYSTEM',
        event_code: 'SESSION_SUPERSEDED',
        announcement_id: null,
        title: '你的账号在别处登录',
        body: '同一个账号在新位置登录，之前的登录已自动下线。',
        link: '/system/sessions',
        level: 'WARNING',
        read_at: null,
        created_at: '2026-09-29T06:00:00Z',
      },
    ],
    total: 1,
    pageNum: 1,
    pageSize: 20,
    unread: 1,
  }
}

function announcement(): Announcement {
  return {
    id: '910001',
    title: '系统维护通知',
    body: '本周六 02:00 起停机维护 2 小时。',
    level: 'IMPORTANT',
    audience_type: 'ALL',
    audience_role_id: null,
    recipient_count: 39,
    created_by_username: 'admin',
    created_at: '2026-09-29T06:00:00Z',
  }
}

describe('收件箱端点 —— 认证域', () => {
  it('列表打到 /auth/notifications，且解包信封', async () => {
    const fetchStub = stubFetch(async () => ok(page()))

    const result = await listMyNotifications({ pageNum: 1, pageSize: 20 })

    expect(fetchStub.calls).toHaveLength(1)
    expect(fetchStub.calls[0]?.url).toContain('/api/v1/auth/notifications')
    // ⚠️ 这一条是**安全**断言，不是措辞检查：前缀落到 admin 域，
    // 普通用户就会因为缺少 API 权限位而看不到自己的任何消息。
    expect(fetchStub.calls[0]?.url).not.toContain('/admin/')
    expect(result.list).toHaveLength(1)
    // `unread` 与 `total` 是两个不同的数：前者是未读总数，后者是收件箱总量。
    // 解包时把它们合并或顶替，角标就会永远等于列表总条数。
    expect(result.unread).toBe(1)
    expect(result.total).toBe(1)
  })

  it('未读数是独立端点，不靠列表接口算', async () => {
    const fetchStub = stubFetch(async () => ok({ unread: 7 }))

    const result = await fetchUnreadCount()

    expect(fetchStub.calls[0]?.url).toBe('/api/v1/auth/notifications/unread-count')
    expect(result.unread).toBe(7)
  })

  it('单条已读是 POST /auth/notifications/{id}/read', async () => {
    const fetchStub = stubFetch(async () => ok(page().list[0]))

    await markNotificationRead('900001')

    expect(fetchStub.calls[0]?.url).toBe('/api/v1/auth/notifications/900001/read')
    expect(fetchStub.calls[0]?.init.method).toBe('POST')
  })

  it('全部已读打到 read-all，且**不带请求体**', async () => {
    const fetchStub = stubFetch(async () => ok({ updated: 3 }))

    const result = await markAllNotificationsRead()

    expect(fetchStub.calls[0]?.url).toBe('/api/v1/auth/notifications/read-all')
    expect(fetchStub.calls[0]?.init.method).toBe('POST')
    // 后端这条端点没有 body schema；发一个 `{}` 会被 FastAPI 当成
    // "提供了一份空对象"而不是"没有请求体"。
    expect(fetchStub.calls[0]?.init.body ?? null).toBeNull()
    expect(result.updated).toBe(3)
  })
})

describe('公告管理端点 —— admin 域', () => {
  it('列表打到 /admin/notifications/announcements', async () => {
    const fetchStub = stubFetch(async () =>
      ok({ list: [announcement()], total: 1, pageNum: 1, pageSize: 20 }),
    )

    const result = await listAnnouncements({ pageNum: 1, pageSize: 20 })

    expect(fetchStub.calls[0]?.url).toContain('/api/v1/admin/notifications/announcements')
    // 反向断言：公告管理**必须**在 admin 域，否则任何登录用户都能发全员公告。
    expect(fetchStub.calls[0]?.url).not.toContain('/auth/')
    expect(result.total).toBe(1)
  })

  it('发布带上受众与角色 id，并解包 recipient_count', async () => {
    const fetchStub = stubFetch(async () =>
      ok({ announcement: announcement(), recipient_count: 39 }),
    )

    const result = await publishAnnouncement({
      title: '系统维护通知',
      body: '本周六 02:00 起停机维护 2 小时。',
      level: 'IMPORTANT',
      audience_type: 'ALL',
      audience_role_id: null,
    })

    expect(fetchStub.calls[0]?.init.method).toBe('POST')
    const body = JSON.parse(String(fetchStub.calls[0]?.init.body)) as Record<string, unknown>
    expect(body.level).toBe('IMPORTANT')
    // `null` 必须原样发出去。省略字段与发 null 在后端是两件事
    // （`model_fields_set` 分派），而审计快照记的是"有没有指定受众"。
    expect(body.audience_role_id).toBeNull()
    expect(result.recipient_count).toBe(39)
    expect(result.announcement.created_by_username).toBe('admin')
  })

  it('撤回是 POST .../{id}/revoke，并带回被收回的条数', async () => {
    const fetchStub = stubFetch(async () => ok({ id: '910001', purged: 39 }))

    const result = await revokeAnnouncement('910001')

    expect(fetchStub.calls[0]?.url).toBe(
      '/api/v1/admin/notifications/announcements/910001/revoke',
    )
    expect(result.purged).toBe(39)
  })

  it('公告管理被拒时如实抛出 403（不能静默吞成"没有公告"）', async () => {
    stubFetch(async () => fail(403001, 'permission denied', 403))

    await expect(listAnnouncements({ pageNum: 1, pageSize: 20 })).rejects.toThrow()
  })
})
