import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 部门管理（需求：列表里不要出现 ID）。
 *
 * 为什么值得单钉一条：`id` / `parent_id` 是后端一直在返回的字段，
 * 把它们显示出来**不会报错**，只是让每一行多两串 18 位雪花 ID ——
 * 而这类"多加了一行"的改动在 diff 里看起来完全无害，
 * 于是很容易在某次"把字段都用上"的批量补全里又被加回来。
 *
 * 层级已经由缩进表达，无需再写一串 ID；
 * 需要 ID 沟通时走详情/接口，不占列表的横向空间。
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
import DepartmentListView from '@/views/system/DepartmentListView.vue'
import { usePermissionStore } from '@/stores/permission'

const org = vi.mocked(orgApi)

const DEPARTMENT_ID = '229270485224001536'

beforeEach(() => {
  vi.clearAllMocks()
  org.getDepartmentTree.mockResolvedValue([
    {
      id: DEPARTMENT_ID,
      parent_id: null,
      department_code: 'D001',
      department_name: '集团',
      status: 'ACTIVE',
      children: [
        {
          id: '229270485224001537',
          parent_id: DEPARTMENT_ID,
          department_code: 'D002',
          department_name: '技术部',
          status: 'ACTIVE',
          children: [],
        },
      ],
    },
  ])
  const permission = usePermissionStore()
  permission.reset()
  permission.buttonCodes = new Set(['department:create', 'department:update'])
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(DepartmentListView)
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('部门管理 —— 列表内容', () => {
  it('每一行都不显示 `id` / `parent_id`', async () => {
    const wrapper = await mountView()

    expect(wrapper.findAll('.tree__row')).toHaveLength(2)
    // 断言的是"整个列表里不出现这两个值"，而不是某一行 ——
    // 换个装饰文案（`ID xxx`、`#xxx`、`id=xxx`）也躲不过。
    const text = wrapper.text()
    expect(text).not.toContain(DEPARTMENT_ID)
    expect(text).not.toContain('229270485224001537')
    expect(text).not.toContain('上级')
  })

  it('部门名与编码仍然在（去掉的是 ID，不是整行的信息）', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('集团')
    expect(wrapper.text()).toContain('技术部')
    expect(wrapper.text()).toContain('D001')
    expect(wrapper.text()).toContain('D002')
  })
})
