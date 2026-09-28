import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 会话管理的筛选面（需求：在线状态可留空查全部，并新增 IP / 时间 / 系统筛选）。
 *
 * 为什么单独一个 spec：这些全是**静默错**的地方 —— 传错一个值不会报错，
 * 只会查出另一个结果集，而界面上看起来完全正常。逐一钉住：
 *
 * 1. **"全部"必须是 `null`，不能是 `false`**。界面上的 `<select>` 空选项
 *    value 只能是空串，早先直接把它绑在一个 `boolean` 上，靠"空串刚好为假"
 *    勉强工作；一旦映射错成 `false`，后端会理解成"只要离线的"，
 *    于是"不筛选"变成"筛掉全部在线会话" —— 与用户意图正好相反。
 * 2. **本地日期不能当 UTC 用**。`login_at` 是 UTC，`<input type="date">`
 *    给的是本地日期；直接拼 `T00:00:00Z` 在东八区会漏掉 8 小时的数据
 *    （"选了昨天却查不到昨天的登录"）。
 * 3. **区间反了要如实拒绝**，不能静默交换两端 —— 交换后用户以为筛的是
 *    自己填的区间，实际筛的是另一个。
 */

vi.mock('@/api/endpoints/organization', () => ({
  listUsers: vi.fn(),
  getUser: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  enableUser: vi.fn(),
  disableUser: vi.fn(),
  resetUserPassword: vi.fn(),
  getDepartmentTree: vi.fn(),
  createDepartment: vi.fn(),
  updateDepartment: vi.fn(),
  disableDepartment: vi.fn(),
  listSessions: vi.fn(),
  revokeSession: vi.fn(),
  listUserSessions: vi.fn(),
  revokeAllUserSessions: vi.fn(),
}))

import * as orgApi from '@/api/endpoints/organization'
import SessionListView from '@/views/system/SessionListView.vue'
import { useAppStore } from '@/stores/app'

const org = vi.mocked(orgApi)

beforeEach(() => {
  vi.clearAllMocks()
  org.listSessions.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(SessionListView)
  await flushPromises()
  await flushPromises()
  return wrapper
}

/** 最近一次 `listSessions` 的查询参数。 */
function lastQuery(): Record<string, unknown> | undefined {
  const calls = org.listSessions.mock.calls
  return calls.at(-1)?.[0] as Record<string, unknown> | undefined
}

/** 按可见文字点一个按钮（`查询` / `重置`）。 */
async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  await button.trigger('click')
  await flushPromises()
}

describe('会话筛选 —— 在线状态三态', () => {
  it('在线状态留空时查全部，请求里是 null 而不是 false', async () => {
    await mountView()

    // 首屏那次请求就是"不带任何筛选"。
    expect(lastQuery()?.online).toBeNull()
    expect(lastQuery()?.online).not.toBe(false)
  })

  it('下拉是 全部 / 仅在线 / 仅离线 三项，默认停在"全部"', async () => {
    const wrapper = await mountView()
    const select = wrapper.find('select')

    expect(select.findAll('option').map((option) => option.text())).toEqual([
      '全部',
      '仅在线',
      '仅离线',
    ])
    expect((select.element as HTMLSelectElement).value).toBe('')
  })

  it('选"仅在线"发 true、选"仅离线"发 false', async () => {
    const wrapper = await mountView()

    await wrapper.find('select').setValue('online')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.online).toBe(true)

    await wrapper.find('select').setValue('offline')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.online).toBe(false)
  })

  it('重置把状态清回"全部"并重新查询', async () => {
    const wrapper = await mountView()

    await wrapper.find('select').setValue('offline')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.online).toBe(false)

    await clickButton(wrapper, '重置')
    expect(lastQuery()?.online).toBeNull()
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('')
  })
})

describe('会话筛选 —— IP 与系统', () => {
  it('空串转 null，填了原样带上（并去掉首尾空格）', async () => {
    const wrapper = await mountView()

    expect(lastQuery()?.ip).toBeNull()
    expect(lastQuery()?.device).toBeNull()

    await wrapper.find('input[placeholder="如 192.168"]').setValue('  10.0.0  ')
    await wrapper.find('input[placeholder="如 Windows / Chrome"]').setValue(' Chrome ')
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.ip).toBe('10.0.0')
    expect(lastQuery()?.device).toBe('Chrome')
  })
})

describe('会话筛选 —— 登录时间区间', () => {
  it('本地日期被换算成 UTC 的时间戳，而不是当成 UTC 直接拼', async () => {
    const wrapper = await mountView()
    const dates = wrapper.findAll('input[type="date"]')

    await dates[0]?.setValue('2026-09-01')
    await dates[1]?.setValue('2026-09-02')
    await clickButton(wrapper, '查询')

    const from = lastQuery()?.login_from as string
    const to = lastQuery()?.login_to as string
    // 形态是 UTC 的 ISO 8601。
    expect(from).toMatch(/Z$/)
    expect(to).toMatch(/Z$/)

    // 起点是本地的 00:00、终点是本地的 23:59 —— 把 ISO 串解析回来，
    // 本地日历字段必须与用户填的一致（这正是"漏 8 小时"会破坏的性质）。
    const start = new Date(from)
    expect([
      start.getFullYear(),
      start.getMonth() + 1,
      start.getDate(),
      start.getHours(),
      start.getMinutes(),
      start.getSeconds(),
    ]).toEqual([2026, 9, 1, 0, 0, 0])

    const end = new Date(to)
    expect([
      end.getFullYear(),
      end.getMonth() + 1,
      end.getDate(),
      end.getHours(),
      end.getMinutes(),
      end.getSeconds(),
    ]).toEqual([2026, 9, 2, 23, 59, 59])
  })

  it('只填一端时另一端是 null', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('input[type="date"]')[0]?.setValue('2026-09-01')
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.login_from).not.toBeNull()
    expect(lastQuery()?.login_to).toBeNull()
  })

  it('起始晚于结束时拒绝查询并提示，不静默交换两端', async () => {
    const wrapper = await mountView()
    const callsBefore = org.listSessions.mock.calls.length
    const dates = wrapper.findAll('input[type="date"]')

    await dates[0]?.setValue('2026-09-10')
    await dates[1]?.setValue('2026-09-01')
    await clickButton(wrapper, '查询')

    expect(org.listSessions.mock.calls.length).toBe(callsBefore)
    expect(useAppStore().notice?.type).toBe('error')
    expect(useAppStore().notice?.message).toContain('登录时间')
  })
})
