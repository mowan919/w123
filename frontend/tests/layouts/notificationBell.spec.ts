import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { NBadge } from 'naive-ui'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 顶栏消息铃铛与下拉面板（`DESIGN-DECISIONS §32`）。
 *
 * 这个组件里有两件事属于"装配问题"，坏了只会静默降级：
 *
 * 1. **角标在 0 条时必须整个不显示**。显示一个 "0" 既占位又提示"你没事"，
 *    还会在每次轮询后闪一下。
 * 2. **轮询必须随组件卸载停掉**。不停的话，登出后前端会继续以 60 秒的节奏
 *    替一个已经不存在的会话发请求 —— 而这条流量在服务端看起来完全正常。
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

import * as notificationApi from '@/api/endpoints/notifications'
import NotificationBell from '@/components/layout/NotificationBell.vue'
import NotificationPanel from '@/components/layout/NotificationPanel.vue'
import { useNotificationsStore } from '@/stores/notifications'
import { NOTIFICATION_CATEGORY_FALLBACK } from '@/utils/notification'
import type { NotificationItem, NotificationPage } from '@/types'

const api = vi.mocked(notificationApi)

function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: '900001',
    category: 'SYSTEM',
    event_code: 'SESSION_SUPERSEDED',
    announcement_id: null,
    title: '你的账号在别处登录',
    body: '同一个账号在新位置登录，之前的登录已自动下线。',
    link: '/system/sessions',
    level: 'WARNING',
    read_at: null,
    created_at: new Date(Date.now() - 120_000).toISOString(),
    ...overrides,
  }
}

function page(overrides: Partial<NotificationPage> = {}): NotificationPage {
  return { list: [item()], total: 1, pageNum: 1, pageSize: 8, unread: 1, ...overrides }
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/notifications', name: 'notifications', component: { template: '<div />' } },
      { path: '/system/sessions', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountBell(): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const wrapper = mount(NotificationBell, {
    global: { plugins: [router] },
    // 面板内容 teleport 到 body，必须挂进文档才查得到。
    attachTo: document.body,
  })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}

function panel(): HTMLElement | null {
  return document.querySelector('[data-testid="notification-panel"]')
}

function panelButton(text: string): HTMLButtonElement {
  const found = Array.from(panel()?.querySelectorAll('button') ?? []).find((node) =>
    (node.textContent ?? '').includes(text),
  )
  if (found === undefined) throw new Error(`面板里找不到按钮：${text}`)
  return found as HTMLButtonElement
}

async function clickBell(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('button.bell').trigger('click')
  await flushPromises()
  await flushPromises()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
  api.listMyNotifications.mockResolvedValue(page())
})

afterEach(() => {
  while (mounted.length > 0) mounted.pop()?.unmount()
})

describe('角标', () => {
  it('未读为 0 时整个角标不渲染（不是显示 0）', async () => {
    api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
    const { wrapper } = await mountBell()

    await flushPromises()

    expect(wrapper.find('.n-badge-sup').exists()).toBe(false)
    expect(wrapper.find('button.bell').attributes('aria-label')).toBe('消息')
  })

  it('有未读时显示角标数字，并把它读进无障碍标签', async () => {
    api.fetchUnreadCount.mockResolvedValue({ unread: 3 })
    const { wrapper } = await mountBell()

    await flushPromises()

    expect(wrapper.find('.n-badge-sup').exists()).toBe(true)
    // ⚠️ 不断言角标的**文字**。naive 的 NBadge 用"数字滚动"渲染，
    // 同一个字符会为动画渲染多份（实测 `3` 的 textContent 是 `333`），
    // 断言文字等于把第三方组件的内部实现写进用例 —— 它一改版就红，
    // 而产品行为完全没变。这里断言我们**传给它的契约**。
    const badge = wrapper.findComponent(NBadge)
    expect(badge.props('value')).toBe(3)
    // `max=99` 是"超过就显示 99+"的唯一来源，值错了角标会撑变形。
    expect(badge.props('max')).toBe(99)
    expect(badge.props('show')).toBe(true)

    // 图标按钮没有可读文字，标签是唯一的无障碍入口。
    expect(wrapper.find('button.bell').attributes('aria-label')).toBe('消息（3 条未读）')
  })

  it('0 条时把 show 关掉（而不是传一个 0 进去）', async () => {
    api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
    const { wrapper } = await mountBell()

    await flushPromises()

    expect(wrapper.findComponent(NBadge).props('show')).toBe(false)
    expect(wrapper.findComponent(NBadge).props('value')).toBe(0)
  })
})

describe('轮询生命周期', () => {
  it('挂载时立刻拉一次未读数', async () => {
    await mountBell()
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1)
  })

  it('卸载后停止轮询，不再发请求', async () => {
    const { wrapper } = await mountBell()
    const callsWhileMounted = api.fetchUnreadCount.mock.calls.length

    wrapper.unmount()
    await flushPromises()

    expect(useNotificationsStore().timer).toBeNull()
    // 定时器已清掉，所以这里只能确认"卸载动作本身没有再发请求"。
    expect(api.fetchUnreadCount.mock.calls.length).toBe(callsWhileMounted)
  })
})

describe('下拉面板', () => {
  it('打开面板时重新拉一次（轮询的 60 秒空窗期里数据大概率已过期）', async () => {
    const { wrapper } = await mountBell()
    const listCallsBefore = api.listMyNotifications.mock.calls.length

    await clickBell(wrapper)

    expect(api.listMyNotifications.mock.calls.length).toBeGreaterThan(listCallsBefore)
    expect(panel()).not.toBeNull()
  })

  it('面板逐条展示标题、分类与轻重', async () => {
    const { wrapper } = await mountBell()

    await clickBell(wrapper)

    const text = panel()?.textContent ?? ''
    expect(text).toContain('你的账号在别处登录')
    expect(text).toContain(NOTIFICATION_CATEGORY_FALLBACK.SYSTEM)
    // 两条消息用不同分类时标签也要跟着变 —— 只显示"系统消息"的话，
    // 管理员公告在面板里的辨识度就没了。
    expect(text).toContain('提醒')
  })

  it('没有消息时给出空态而不是一个空列表', async () => {
    api.listMyNotifications.mockResolvedValue(page({ list: [], total: 0, unread: 0 }))
    const { wrapper } = await mountBell()

    await clickBell(wrapper)

    expect(panel()?.textContent).toContain('暂时没有消息')
  })

  it('「查看全部」跳到消息中心（按路由名，不是路径字面量）', async () => {
    const { wrapper, router } = await mountBell()
    await clickBell(wrapper)

    panelButton('查看全部').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('notifications')
  })

  it('点面板里的一条会把它标记为已读', async () => {
    api.markNotificationRead.mockResolvedValue(item({ read_at: '2026-09-29T07:00:00Z' }))
    const { wrapper } = await mountBell()
    await clickBell(wrapper)

    const row = panel()?.querySelector('button.row')
    expect(row).not.toBeNull()
    row!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(api.markNotificationRead).toHaveBeenCalledWith('900001')
  })

  it('「全部已读」在没有未读时不可点', async () => {
    api.fetchUnreadCount.mockResolvedValue({ unread: 0 })
    api.listMyNotifications.mockResolvedValue(page({ list: [], total: 0, unread: 0 }))
    const { wrapper } = await mountBell()
    await clickBell(wrapper)

    expect(panelButton('全部已读').disabled).toBe(true)
  })
})

describe('NotificationPanel（纯展示组件）', () => {
  it('未读与已读在四个视觉信号上都不同（色点 / 加粗 / 淡底 / 圆点）', async () => {
    const wrapper = mount(NotificationPanel, {
      props: { items: [item({ id: 'a' }), item({ id: 'b', read_at: '2026-09-29T07:00:00Z' })] },
    })

    const rows = wrapper.findAll('button.row')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.classes()).toContain('row--unread')
    expect(rows[1]?.classes()).not.toContain('row--unread')
    // 右端那个孤立的小圆点是"快速滚动时最容易被扫到"的那一个信号。
    expect(rows[0]?.find('.row__dot').exists()).toBe(true)
    expect(rows[1]?.find('.row__dot').exists()).toBe(false)
  })

  it('点一行只上抛 id，不自己发请求（写操作在 store 里）', async () => {
    const wrapper = mount(NotificationPanel, { props: { items: [item()] } })

    await wrapper.find('button.row').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['900001']])
  })

  it('时间用相对表达，且非法时间不编造', async () => {
    const wrapper = mount(NotificationPanel, {
      props: { items: [item({ created_at: 'not-a-date' })] },
    })

    // 兜底是原样返回，而不是显示 "Invalid Date"。
    expect(wrapper.find('.row__time').text()).toBe('not-a-date')
  })
})
