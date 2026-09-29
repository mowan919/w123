import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 消息中心（`/notifications`，`DESIGN-DECISIONS §32`）。
 *
 * 这一页里有三处**静默错**，全都不报错、只看结果，所以逐条钉住：
 *
 * 1. **筛选后不回第 1 页**。在第 3 页把分类改成"公告"，结果集只有 1 页，
 *    而请求还在问第 3 页 —— 用户看到空列表，会以为"一条公告都没有"。
 * 2. **角标与列表不同源**。收件箱响应自带 `unread`，页面若不把它写回顶栏
 *    store，屏幕上会同时出现"列表页头 3 条未读"和"顶栏角标 0"两个数字。
 * 3. **已读消息重复标记**。点一条已经读过的消息还去发一次已读请求，
 *    在后端是幂等的（无害），但会在网络慢时让跳转多等一个来回。
 */

vi.mock('@/api/endpoints/notifications', () => ({
  listMyNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  listAnnouncements: vi.fn(),
  publishAnnouncement: vi.fn(),
  revokeAnnouncement: vi.fn(),
}))

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
}))

import * as notificationApi from '@/api/endpoints/notifications'
import * as dictApi from '@/api/endpoints/dictionaries'
import NotificationsView from '@/views/NotificationsView.vue'
import { useNotificationsStore } from '@/stores/notifications'
import { useAppStore } from '@/stores/app'
import type { NotificationItem, NotificationPage } from '@/types'

const api = vi.mocked(notificationApi)
const dicts = vi.mocked(dictApi)

function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: '900001',
    category: 'SYSTEM',
    event_code: 'SESSION_SUPERSEDED',
    announcement_id: null,
    title: '你的账号在别处登录',
    body: '同一个账号在新位置登录，之前的登录已自动下线。',
    link: '/profile',
    level: 'WARNING',
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
    pageSize: 20,
    unread: 1,
    ...overrides,
  }
}

/** 最近一次 `listMyNotifications` 的查询参数。 */
function lastQuery(): Record<string, unknown> | undefined {
  const call = api.listMyNotifications.mock.calls.at(-1)
  return call === undefined ? undefined : (call[0] as unknown as Record<string, unknown>)
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    // 消息里可能指向任意页面；这里只需要它指向的那一条存在，
    // 否则 vue-router 会打 "No match found" 警告把真实失败埋掉。
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/profile', component: { template: '<div />' } },
    ],
  })
}

async function mountView(): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const wrapper = mount(NotificationsView, { global: { plugins: [router] } })
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((node) => node.text().includes(text))
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  await button.trigger('click')
  await flushPromises()
  await flushPromises()
}

/**
 * 点分页里的某个页码。
 *
 * 单独一个函数、且**只在分页容器里找**：直接按文字找 `3` 会先命中
 * 工具栏或其它带数字的按钮（"共 60 条"之类），而那种误命中不会报错 ——
 * 只会让"翻页没生效"的断言看起来通过了。
 */
async function clickPage(wrapper: VueWrapper, target: number): Promise<void> {
  const button = wrapper
    .findAll('.n-pagination-item')
    .find((node) => node.text().trim() === String(target))
  if (button === undefined) throw new Error(`找不到页码 ${target}`)
  await button.trigger('click')
  await flushPromises()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listMyNotifications.mockResolvedValue(page())
  api.fetchUnreadCount.mockResolvedValue({ unread: 1 })
  api.markNotificationRead.mockResolvedValue(item({ read_at: '2026-09-29T07:00:00Z' }))
  api.markAllNotificationsRead.mockResolvedValue({ updated: 1 })
  dicts.getPublicDict.mockResolvedValue({
    dict_code: 'notification_category',
    dict_name: '通知分类',
    description: null,
    items: [],
  })
})

describe('筛选面', () => {
  it('首屏不带任何筛选，分类是 null 而不是空串', async () => {
    await mountView()

    expect(lastQuery()).toMatchObject({ pageNum: 1, pageSize: 20, unreadOnly: false })
    // 空串会被后端当成一个**分类取值**去比对，结果是 0 条 ——
    // 界面上看就是"一条消息都没有"，比报错更难查。
    expect(lastQuery()?.['category']).toBeNull()
  })

  it('选了分类就带上，选回"全部"又归 null', async () => {
    const { wrapper } = await mountView()

    await wrapper.find('select').setValue('ANNOUNCEMENT')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.['category']).toBe('ANNOUNCEMENT')

    await wrapper.find('select').setValue('')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.['category']).toBeNull()
  })

  it('「只看未读」勾上后 unreadOnly 为 true', async () => {
    const { wrapper } = await mountView()

    await wrapper.find('input[type="checkbox"]').setValue(true)
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.['unreadOnly']).toBe(true)
  })

  it('筛选后回到第 1 页 —— 否则会停在一个不存在的页码上看到空列表', async () => {
    // 让假后端**回显请求的页码**：视图会拿响应里的 `pageNum` 覆盖本地页码，
    // 假后端永远返回 1 的话，"翻到第 3 页"这件事根本立不住。
    api.listMyNotifications.mockImplementation(async (query) =>
      page({ total: 60, pageNum: query.pageNum, pageSize: query.pageSize }),
    )
    const { wrapper } = await mountView()

    await clickPage(wrapper, 3)
    expect(lastQuery()?.['pageNum']).toBe(3)

    await wrapper.find('select').setValue('ANNOUNCEMENT')
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.['pageNum']).toBe(1)
  })
})

describe('角标与列表同源', () => {
  it('列表响应里的 unread 被写回顶栏 store', async () => {
    api.listMyNotifications.mockResolvedValue(page({ total: 5, unread: 5 }))
    const store = useNotificationsStore()

    await mountView()

    // 两个数字在屏幕上总是同时出现；不写回就会看到"列表说 5 条未读、
    // 顶栏角标还是 0"这种同屏矛盾。
    expect(store.unread).toBe(5)
  })
})

describe('已读操作', () => {
  it('点未读消息：先标记已读，再跳到 link', async () => {
    const { wrapper, router } = await mountView()

    await wrapper.find('button.card').trigger('click')
    await flushPromises()

    expect(api.markNotificationRead).toHaveBeenCalledWith('900001')
    expect(router.currentRoute.value.path).toBe('/profile')
  })

  it('点已读消息：不再重复发已读请求，直接跳转', async () => {
    api.listMyNotifications.mockResolvedValue(
      page({ list: [item({ read_at: '2026-09-29T07:00:00Z' })], unread: 0 }),
    )
    const { wrapper, router } = await mountView()

    await wrapper.find('button.card').trigger('click')
    await flushPromises()

    expect(api.markNotificationRead).not.toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/profile')
  })

  it('没有 link 的消息：不跳转，只刷新列表', async () => {
    api.listMyNotifications.mockResolvedValue(
      page({ list: [item({ link: null, read_at: '2026-09-29T07:00:00Z' })], unread: 0 }),
    )
    const { wrapper, router } = await mountView()
    const listCallsBefore = api.listMyNotifications.mock.calls.length

    await wrapper.find('button.card').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')
    expect(api.listMyNotifications.mock.calls.length).toBeGreaterThan(listCallsBefore)
  })

  it('「全部已读」按返回的条数给提示', async () => {
    api.markAllNotificationsRead.mockResolvedValue({ updated: 4 })
    api.listMyNotifications.mockResolvedValue(page({ total: 4, unread: 4 }))
    const { wrapper } = await mountView()

    await clickButton(wrapper, '全部已读')

    expect(api.markAllNotificationsRead).toHaveBeenCalledTimes(1)
    expect(useAppStore().notice?.message).toContain('4')
  })

  it('没有未读时「全部已读」按钮不可点', async () => {
    api.listMyNotifications.mockResolvedValue(page({ list: [], total: 0, unread: 0 }))
    const { wrapper } = await mountView()

    const button = wrapper.findAll('button').find((node) => node.text().includes('全部已读'))
    expect(button?.attributes('disabled')).toBeDefined()
  })
})

describe('列表渲染', () => {
  it('未读与已读在状态上有区分（未读带左侧色条）', async () => {
    api.listMyNotifications.mockResolvedValue(
      page({
        list: [item({ id: 'a' }), item({ id: 'b', read_at: '2026-09-29T07:00:00Z' })],
        total: 2,
        unread: 1,
      }),
    )
    const { wrapper } = await mountView()

    const cards = wrapper.findAll('button.card')
    expect(cards).toHaveLength(2)
    expect(cards[0]?.classes()).toContain('card--unread')
    expect(cards[1]?.classes()).not.toContain('card--unread')
  })

  it('空列表给出空态文案', async () => {
    api.listMyNotifications.mockResolvedValue(page({ list: [], total: 0, unread: 0 }))
    const { wrapper } = await mountView()

    expect(wrapper.text()).toContain('暂时没有消息')
  })
})
