import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 用户管理的筛选面（需求：增加创建时间筛选，并可一键设为当前时间）。
 *
 * 单独一个 spec 的理由与 `sessionFilters.spec.ts` 相同：这里全是**静默错** ——
 * 传错一个值不报错，只会查出另一个结果集，界面上看起来完全正常。
 *
 * 1. **`datetime-local` 的值不能原样发出**。它是不带时区的本地时间串，
 *    后端会把它解析成 naive datetime 再绑到 `timestamptz` 列上比较，
 *    此时"它算几点"由**服务端时区**决定。实测本机 `TimeZone=Asia/Shanghai`：
 *    naive `09:35` 被当成 `01:35+00:00`。服务器一旦不在 +08:00，
 *    筛选会整块偏移且一个错都不报。
 * 2. **区间反了要如实拒绝**，不静默交换两端 —— 交换后用户以为筛的是
 *    自己填的区间，实际筛的是另一个。
 * 3. **「此刻」必须写出 `datetime-local` 认得的格式**：`2026-1-5T9:07`
 *    这种没补零的串会被浏览器判为非法并显示为空，点了等于没点。
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

vi.mock('@/api/endpoints/roles', () => ({
  listRoles: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
  getRolePermissions: vi.fn(),
  setRolePagePermissions: vi.fn(),
  setRoleMenuPermissions: vi.fn(),
  setRoleButtonPermissions: vi.fn(),
  setRoleApiPermissions: vi.fn(),
  setRoleFieldPermissions: vi.fn(),
  getRoleDataScope: vi.fn(),
  setRoleDataScope: vi.fn(),
}))

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
}))

import * as orgApi from '@/api/endpoints/organization'
import * as rolesApi from '@/api/endpoints/roles'
import * as dictApi from '@/api/endpoints/dictionaries'
import UserListView from '@/views/system/UserListView.vue'
import { useAppStore } from '@/stores/app'
import { usePermissionStore } from '@/stores/permission'

const org = vi.mocked(orgApi)
const roles = vi.mocked(rolesApi)
const dicts = vi.mocked(dictApi)

/** 最近一次 `listUsers` 的查询参数。 */
function lastQuery(): Record<string, unknown> | undefined {
  const call = org.listUsers.mock.calls.at(-1)
  return call === undefined ? undefined : (call[0] as unknown as Record<string, unknown>)
}

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(UserListView)
  await flushPromises()
  await flushPromises()
  return wrapper
}

async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((node) => node.text().includes(text))
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  await button.trigger('click')
  await flushPromises()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()

  org.getDepartmentTree.mockResolvedValue([])
  org.listUsers.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  roles.listRoles.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  dicts.getPublicDict.mockResolvedValue({
    dict_code: 'user_status',
    dict_name: '用户状态',
    description: null,
    items: [],
  })

  const permission = usePermissionStore()
  permission.reset()
  permission.fieldLevels = new Map([['phone', 'VISIBLE']])
})

afterEach(() => {
  vi.useRealTimers()
})

describe('用户管理筛选 —— 创建时间', () => {
  it('本地时间被换算成 UTC 的 ISO 串，而不是原样发出', async () => {
    const wrapper = await mountView()
    const inputs = wrapper.findAll('input[type="datetime-local"]')

    expect(inputs).toHaveLength(2)
    await inputs[0]?.setValue('2026-09-01T08:00')
    await inputs[1]?.setValue('2026-09-30T18:00')
    await clickButton(wrapper, '查询')

    const from = lastQuery()?.['created_from'] as string
    const to = lastQuery()?.['created_to'] as string

    // 形态必须是 UTC —— 不带 `Z` 的串到了后端又会被当成 naive，问题原封不动。
    expect(from).toMatch(/Z$/)
    expect(to).toMatch(/Z$/)

    // 把 ISO 串解析回来，**本地**日历字段必须与用户填的一致。
    // 这正是"时区算错 8 小时"会破坏的性质，而它不依赖跑测试的机器在哪个时区。
    const start = new Date(from)
    const end = new Date(to)
    expect([
      start.getFullYear(),
      start.getMonth() + 1,
      start.getDate(),
      start.getHours(),
      start.getMinutes(),
    ]).toEqual([2026, 9, 1, 8, 0])
    expect([
      end.getFullYear(),
      end.getMonth() + 1,
      end.getDate(),
      end.getHours(),
      end.getMinutes(),
    ]).toEqual([2026, 9, 30, 18, 0])
  })

  it('不填时两端都是 null（后端据此不加条件，而不是"筛一个空区间"）', async () => {
    const wrapper = await mountView()
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.['created_from']).toBeNull()
    expect(lastQuery()?.['created_to']).toBeNull()
  })

  it('只填一端时另一端仍是 null', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('input[type="datetime-local"]')[0]?.setValue('2026-09-01T00:00')
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.['created_from']).not.toBeNull()
    expect(lastQuery()?.['created_to']).toBeNull()
  })

  it('「此刻」把结束时间填成当前时间', async () => {
    vi.useFakeTimers({ now: new Date(2026, 8, 28, 17, 33, 45) })
    const wrapper = await mountView()

    await clickButton(wrapper, '此刻')

    const inputs = wrapper.findAll('input[type="datetime-local"]')
    expect((inputs[1]?.element as HTMLInputElement).value).toBe('2026-09-28T17:33')
    // 起始时间不被动过：那才是需要人自己选的一端。
    expect((inputs[0]?.element as HTMLInputElement).value).toBe('')
  })

  it('「此刻」不覆盖已经填好的起始时间', async () => {
    vi.useFakeTimers({ now: new Date(2026, 8, 28, 17, 33, 45) })
    const wrapper = await mountView()
    const inputs = wrapper.findAll('input[type="datetime-local"]')

    await inputs[0]?.setValue('2026-09-01T00:00')
    await clickButton(wrapper, '此刻')

    expect((inputs[0]?.element as HTMLInputElement).value).toBe('2026-09-01T00:00')
  })

  it('起始晚于结束时拒绝查询并提示，不静默交换两端', async () => {
    const wrapper = await mountView()
    const callsBefore = org.listUsers.mock.calls.length
    const inputs = wrapper.findAll('input[type="datetime-local"]')

    await inputs[0]?.setValue('2026-09-30T00:00')
    await inputs[1]?.setValue('2026-09-01T00:00')
    await clickButton(wrapper, '查询')

    expect(org.listUsers.mock.calls.length).toBe(callsBefore)
    expect(useAppStore().notice?.type).toBe('error')
    expect(useAppStore().notice?.message).toContain('创建时间')
  })

  it('两端相等是合法区间（含边界），不当作"填反了"', async () => {
    const wrapper = await mountView()
    const inputs = wrapper.findAll('input[type="datetime-local"]')

    await inputs[0]?.setValue('2026-09-01T08:00')
    await inputs[1]?.setValue('2026-09-01T08:00')
    await clickButton(wrapper, '查询')

    expect(lastQuery()?.['created_from']).toBe(lastQuery()?.['created_to'])
  })

  it('重置把时间范围清空并重新查询', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('input[type="datetime-local"]')[0]?.setValue('2026-09-01T00:00')
    await clickButton(wrapper, '查询')
    expect(lastQuery()?.['created_from']).not.toBeNull()

    await clickButton(wrapper, '重置')

    // 重置走的是 `reload({})`：键**根本不存在**（而不是显式 `null`）。
    // 两者对请求等价 —— `buildUrl` 对 `undefined` / `null` / 空串一律不拼参数，
    // 所以这里断言的是"没有时间条件"，不是某个具体空值。
    expect(lastQuery()?.['created_from']).toBeFalsy()
    expect(lastQuery()?.['created_to']).toBeFalsy()
    expect((wrapper.findAll('input[type="datetime-local"]')[0]?.element as HTMLInputElement).value).toBe(
      '',
    )
  })
})
