import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { Component } from 'vue'

vi.mock('@/api/endpoints/statistics', () => ({
  getStatisticsOverview: vi.fn(),
}))

import * as statisticsApi from '@/api/endpoints/statistics'
import ReportView from '@/views/ReportView.vue'
import { usePermissionStore } from '@/stores/permission'
import { useStatisticsStore } from '@/stores/statistics'
import type { StatisticsOverview } from '@/types'

/**
 * 报表页（登录后的默认首页）的渲染契约。
 *
 * 三条最要紧的断言：
 *
 * 1. **注册用户 / 在线用户**真的带着后端数字出现在 DOM 上 —— 这一页存在的
 *    理由就是这两项；store 单测全绿只能证明"数据到手了"，证明不了页面读对了字段。
 * 2. `accessible: false` 的分组渲染成"无权限"，**绝不放成 0**。把"看不到"
 *    渲染成 0 会让运维以为系统里一个用户都没有，是这一页最危险的一种错。
 * 3. 在线用户与在线会话**是两个不同的数字**（一人可开多条会话）。把它们
 *    渲染成同一个值，报表就不再有任何解释力。
 */

const api = vi.mocked(statisticsApi)

function overview(overrides: Partial<StatisticsOverview> = {}): StatisticsOverview {
  return {
    generated_at: '2026-09-28T06:00:00Z',
    scope_policy: 'ALL',
    users: { accessible: true, total: 39, active: 38, disabled: 1 },
    sessions: { accessible: true, online_users: 2, online_sessions: 5, total: 41 },
    departments: { accessible: true, total: 6 },
    roles: { accessible: true, total: 6 },
    audit: { accessible: true, today: 13, total: 3401 },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getStatisticsOverview.mockResolvedValue(overview())
})

async function mountReport(component: Component = ReportView) {
  const wrapper = mount(component)
  await flushPromises()
  await flushPromises()
  return wrapper
}

/** 按标签取一张指标卡片（卡片结构：label / value / hint）。 */
function cardOf(wrapper: Awaited<ReturnType<typeof mountReport>>, label: string) {
  return wrapper.findAll('article.stat').find((card) => card.text().includes(label))
}

describe('报表页 · 关键指标', () => {
  it('渲染出注册用户与在线用户两个数字', async () => {
    const wrapper = await mountReport()

    const registered = cardOf(wrapper, '注册用户')
    const online = cardOf(wrapper, '在线用户')

    expect(registered?.text()).toContain('39')
    expect(registered?.text()).toContain('启用 38 · 禁用 1')
    expect(online?.text()).toContain('2')
  })

  it('在线用户与在线会话是**两个不同的数字**', async () => {
    const wrapper = await mountReport()

    // 后端：在线用户 2（去重后的人）、在线会话 5。若页面把两者渲染成同一个值，
    // "为什么有人开了 5 个标签页"就无法解释 —— 那正是这一栏存在的意义。
    expect(cardOf(wrapper, '在线用户')?.text()).toContain('2')
    expect(cardOf(wrapper, '在线会话')?.text()).toContain('5')
    expect(cardOf(wrapper, '在线用户')?.text()).toContain('在线会话 5')
  })

  it('补充指标也渲染（部门 / 角色 / 今日审计）', async () => {
    const wrapper = await mountReport()

    expect(cardOf(wrapper, '部门数')?.text()).toContain('6')
    expect(cardOf(wrapper, '角色数')?.text()).toContain('6')
    expect(cardOf(wrapper, '今日审计')?.text()).toContain('13')
    expect(cardOf(wrapper, '今日审计')?.text()).toContain('累计 3401 条')
  })
})

describe('报表页 · 无权限的分组', () => {
  it('渲染成"无权限"，绝不显示 0', async () => {
    api.getStatisticsOverview.mockResolvedValue(
      overview({ roles: { accessible: false, total: null } }),
    )
    const wrapper = await mountReport()

    const roles = cardOf(wrapper, '角色数')
    expect(roles?.text()).toContain('无权限')
    expect(roles?.text()).not.toContain('0')
    // 卡片本身仍然可见（降级样式），而不是被整张隐藏：
    // 隐藏会让人以为"没有这一项"，而它是存在的、只是这个人看不到。
    expect(roles?.classes()).toContain('is-locked')
  })

  it('整页都无权限时给出解释，并保留"我的权限范围"', async () => {
    const hidden = { accessible: false, total: null }
    api.getStatisticsOverview.mockResolvedValue(
      overview({
        users: { accessible: false, total: null, active: null, disabled: null },
        sessions: { accessible: false, online_users: null, online_sessions: null, total: null },
        departments: hidden,
        roles: hidden,
        audit: { accessible: false, today: null, total: null },
      }),
    )
    const wrapper = await mountReport()

    expect(wrapper.text()).toContain('当前账号没有任何统计查看权限')
    // 自己的权限范围不依赖管理权限，必须还在。
    expect(wrapper.text()).toContain('我的权限范围')
  })
})

describe('报表页 · 我的权限范围', () => {
  it('数量取自权限 store，而不是再算一遍', async () => {
    const permissionStore = usePermissionStore()
    permissionStore.pages = [
      { id: '1', code: 'system:user:page', name: '用户管理' },
    ] as (typeof permissionStore.pages)[number][]

    const wrapper = await mountReport()

    expect(cardOf(wrapper, '可访问页面')?.text()).toContain('1')
  })
})

describe('报表页 · 加载与刷新', () => {
  it('挂载即加载，且只打一次请求', async () => {
    await mountReport()

    expect(api.getStatisticsOverview).toHaveBeenCalledTimes(1)
  })

  it('点刷新会强制重新拉取（绕过"已加载过就跳过"）', async () => {
    const wrapper = await mountReport()
    const refresh = wrapper.findAll('button').find((button) => button.text().includes('刷新'))
    expect(refresh).toBeDefined()

    await refresh?.trigger('click')
    await flushPromises()

    expect(api.getStatisticsOverview).toHaveBeenCalledTimes(2)
  })

  it('加载失败时显示错误条，而不是空白页', async () => {
    api.getStatisticsOverview.mockRejectedValue(new Error('接口挂了'))
    const wrapper = await mountReport()

    expect(wrapper.text()).toContain('接口挂了')
    // 首屏失败时不该留下 7 张骨架卡片撑着一页空白。
    expect(wrapper.findAll('article.stat.is-skeleton')).toHaveLength(0)
  })
})

describe('报表页 · 快照信息', () => {
  it('展示数据生成时刻与数据范围（说明这些数字是什么时候、多大范围的）', async () => {
    const wrapper = await mountReport()

    expect(wrapper.text()).toContain('数据时刻')
    expect(wrapper.text()).toContain('全部数据')
    expect(wrapper.text()).toContain('角色与审计是全局计数')
  })
})

describe('报表页 · store 透传', () => {
  it('数据写进的是 statistics store（换页回来不必再拉一次）', async () => {
    await mountReport()

    expect(useStatisticsStore().overview?.users.total).toBe(39)
    expect(useStatisticsStore().loaded).toBe(true)
  })
})
