import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/endpoints/notifications', () => ({
  listMyNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  listAnnouncements: vi.fn(),
  publishAnnouncement: vi.fn(),
  revokeAnnouncement: vi.fn(),
}))

import * as notificationApi from '@/api/endpoints/notifications'
import { POLL_INTERVAL_MS, useNotificationsStore } from '@/stores/notifications'
import type { NotificationItem, NotificationPage } from '@/types'

/**
 * notificationsStore —— 顶栏角标与消息面板（`DESIGN-DECISIONS §32`）。
 *
 * 这个 store 有两处**静默**失败模式，都不会报错，只会让界面看起来
 * "就是没有消息"：
 *
 * 1. **轮询定时器重复启动**。顶栏在布局切换 / 会话恢复等场景下可能被
 *    重复挂载，两个定时器互不知情 —— 请求量翻倍，而且 `stopPolling`
 *    只清掉后一个，前一个会一直跑（登出后仍在替一个不存在的会话发请求）。
 * 2. **轮询失败写进 `error`**。网络抖动是常态，把错误条挂到顶栏会让
 *    一次抖动看起来像系统坏了；更糟的是若同时把 `unread` 清零，
 *    角标会在"有 3 条未读"与"没有"之间反复跳。
 */

const api = vi.mocked(notificationApi)

function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: '900001',
    category: 'SYSTEM',
    event_code: 'PASSWORD_RESET',
    announcement_id: null,
    title: '登录口令已被重置',
    body: '管理员为你重置了登录口令，请尽快修改。',
    link: '/profile',
    level: 'IMPORTANT',
    read_at: null,
    created_at: '2026-09-29T06:00:00Z',
    ...overrides,
  }
}

function page(overrides: Partial<NotificationPage> = {}): NotificationPage {
  return {
    list: [item()],
    total: 1,
    pageNum: 1,
    pageSize: 8,
    unread: 1,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
  api.listMyNotifications.mockResolvedValue(page())
})

afterEach(() => {
  vi.useRealTimers()
})

describe('角标文案', () => {
  it('0 条时 hasUnread 为 false（角标整个不显示，而不是显示 0）', () => {
    const store = useNotificationsStore()
    expect(store.unread).toBe(0)
    expect(store.hasUnread).toBe(false)
    expect(store.badgeText).toBe('0')
  })

  it('99 条以内显示真实数字，超过则收敛成 99+', () => {
    const store = useNotificationsStore()
    store.setUnread(99)
    expect(store.badgeText).toBe('99')
    store.setUnread(100)
    expect(store.badgeText).toBe('99+')
    store.setUnread(1234)
    expect(store.badgeText).toBe('99+')
  })

  it('setUnread 挡住负值：负数会渲染成一个不存在的角标', () => {
    const store = useNotificationsStore()
    store.setUnread(5)
    store.setUnread(-3)
    expect(store.unread).toBe(0)
    expect(store.hasUnread).toBe(false)
  })
})

describe('loadUnreadCount', () => {
  it('成功时只写未读数，不碰面板列表', async () => {
    const store = useNotificationsStore()
    store.recent = [item({ id: 'keep-me' })]
    api.fetchUnreadCount.mockResolvedValue({ unread: 4 })

    await store.loadUnreadCount()

    expect(store.unread).toBe(4)
    expect(store.recent.map((row) => row.id)).toEqual(['keep-me'])
  })

  it('失败时不报错、**保留**上一个数字（角标偏旧好过突然消失）', async () => {
    const store = useNotificationsStore()
    store.setUnread(3)
    api.fetchUnreadCount.mockRejectedValue(new Error('network down'))

    await store.loadUnreadCount()

    expect(store.unread).toBe(3)
    // 关键：错误不写进 `error`。写了的话顶栏会在一次网络抖动后
    // 挂出一条错误提示，而这条路径每 60 秒就会走一次。
    expect(store.error).toBeNull()
  })
})

describe('loadPanel', () => {
  it('写入列表、总数与未读数', async () => {
    const store = useNotificationsStore()
    api.listMyNotifications.mockResolvedValue(
      page({ list: [item(), item({ id: '900002' })], total: 2, unread: 2 }),
    )

    await store.loadPanel()

    expect(store.recent).toHaveLength(2)
    expect(store.total).toBe(2)
    expect(store.unread).toBe(2)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('面板打开时用的页大小是固定的小页，不是消息中心的 20', async () => {
    const store = useNotificationsStore()

    await store.loadPanel()

    expect(api.listMyNotifications).toHaveBeenCalledWith({ pageNum: 1, pageSize: 8 })
  })

  it('失败时给出错误文案并复位 loading', async () => {
    const store = useNotificationsStore()
    api.listMyNotifications.mockRejectedValue(new Error('boom'))

    await store.loadPanel()

    expect(store.error).toBe('boom')
    expect(store.loading).toBe(false)
  })
})

describe('markRead', () => {
  it('先发请求，再**重新拉取**而不是本地乐观更新', async () => {
    const store = useNotificationsStore()
    store.setUnread(1)
    api.markNotificationRead.mockResolvedValue(item({ read_at: '2026-09-29T07:00:00Z' }))
    api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
    api.listMyNotifications.mockResolvedValue(
      page({ list: [item({ read_at: '2026-09-29T07:00:00Z' })], unread: 0 }),
    )

    await store.markRead('900001')

    expect(api.markNotificationRead).toHaveBeenCalledWith('900001')
    // 后端只在**首次**标记时写 `read_at`；本地猜一个时间会与后端不一致
    // （同一秒内点两次就分叉）。因此必须回读。
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1)
    expect(api.listMyNotifications).toHaveBeenCalledTimes(1)
    expect(store.recent[0]?.read_at).toBe('2026-09-29T07:00:00Z')
    expect(store.unread).toBe(0)
  })
})

describe('markAllRead', () => {
  it('返回本次真正被标记的条数，并把未读数清掉', async () => {
    const store = useNotificationsStore()
    store.setUnread(5)
    api.markAllNotificationsRead.mockResolvedValue({ updated: 5 })
    api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
    api.listMyNotifications.mockResolvedValue(page({ list: [], total: 5, unread: 0 }))

    const updated = await store.markAllRead()

    expect(updated).toBe(5)
    expect(store.unread).toBe(0)
  })
})

describe('轮询', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('启动时立刻拉一次，之后按间隔拉', async () => {
    const store = useNotificationsStore()

    store.startPolling()
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(3)

    store.stopPolling()
  })

  it('重复 startPolling 不会起第二个定时器（请求量不翻倍）', async () => {
    const store = useNotificationsStore()

    store.startPolling()
    store.startPolling()
    store.startPolling()
    // 三次调用只有第一次的"立刻拉一次"生效。
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    // 若真的起了三个定时器，这里会是 4。
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(2)

    store.stopPolling()
  })

  it('stopPolling 之后不再发请求，且句柄被置回 null', async () => {
    const store = useNotificationsStore()
    store.startPolling()
    expect(store.timer).not.toBeNull()

    store.stopPolling()
    expect(store.timer).toBeNull()

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1)
  })

  it('stopPolling 可以重复调用（登出与卸载都会走到）', () => {
    const store = useNotificationsStore()
    store.startPolling()
    store.stopPolling()
    expect(() => store.stopPolling()).not.toThrow()
  })
})

describe('reset —— 会话级清理', () => {
  it('清掉数字、正文与错误，并停掉定时器', async () => {
    vi.useFakeTimers()
    const store = useNotificationsStore()
    api.listMyNotifications.mockResolvedValue(page({ total: 2, unread: 2 }))
    await store.loadPanel()
    store.startPolling()
    store.setUnread(2)

    store.reset()

    expect(store.unread).toBe(0)
    expect(store.recent).toEqual([])
    expect(store.total).toBe(0)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
    // 定时器必须停：否则登出后前端还会继续替一个已经不存在的会话发请求。
    expect(store.timer).toBeNull()

    const callsAfterReset = api.fetchUnreadCount.mock.calls.length
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2)
    expect(api.fetchUnreadCount.mock.calls.length).toBe(callsAfterReset)
  })
})
