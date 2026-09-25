import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { Component } from 'vue'
import type { PageResult } from '@/types'

/**
 * 业务 store 的**消费端**冒烟（`08 §3` / `08 §4` / `08 §7` / `08 §9`）。
 *
 * 为什么需要这一组：store 自己的测试全绿，只能证明"store 的行为对"，
 * 证明不了"页面真的照它的实现对"。视图是一个 `<script setup>` 编译产物，
 * 引用错一个字段 vue-tsc 抓得到，但**引用错一个时机**（在 store 还没填数据
 * 时就去读派生 getter）只有真跑一次才会红 —— 表现是页面白屏或者下拉框空着，
 * 且不报任何错。
 *
 * 这里不做断言式的细粒度校验，只钉三件事：
 * 1. 挂载不抛异常（setup 里的异常会直接冒泡到 `mount`）；
 * 2. `onMounted` 触发的加载链路真的把 store 填上了；
 * 3. 关键的派生结果真的渲染到了 DOM 上。
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

vi.mock('@/api/endpoints/resources', () => ({
  listResources: vi.fn(),
  getResourceTree: vi.fn(),
  createResource: vi.fn(),
  updateResource: vi.fn(),
  deleteResource: vi.fn(),
  getMenuPages: vi.fn(),
  setMenuPages: vi.fn(),
}))

vi.mock('@/api/endpoints/params', () => ({
  listSystemParams: vi.fn(),
  createSystemParam: vi.fn(),
  updateSystemParam: vi.fn(),
  deleteSystemParam: vi.fn(),
}))

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
}))

import * as orgApi from '@/api/endpoints/organization'
import * as rolesApi from '@/api/endpoints/roles'
import * as resourcesApi from '@/api/endpoints/resources'
import * as paramsApi from '@/api/endpoints/params'
import * as dictApi from '@/api/endpoints/dictionaries'
import DepartmentListView from '@/views/system/DepartmentListView.vue'
import UserListView from '@/views/system/UserListView.vue'
import RoleListView from '@/views/system/RoleListView.vue'
import ParamListView from '@/views/system/ParamListView.vue'
import PermissionResourceListView from '@/views/system/PermissionResourceListView.vue'
import PermissionListView from '@/views/system/PermissionListView.vue'
import { usePermissionStore } from '@/stores/permission'
import { useOrganizationStore } from '@/stores/organization'
import { useRolesStore } from '@/stores/roles'
import { useResourcesStore } from '@/stores/resources'
import { useParamsStore } from '@/stores/params'

const org = vi.mocked(orgApi)
const roles = vi.mocked(rolesApi)
const resources = vi.mocked(resourcesApi)
const params = vi.mocked(paramsApi)
const dicts = vi.mocked(dictApi)

/**
 * 分页替身：回显请求参数，便于断言筛选条件被正确传递。
 *
 * 四个列表端点的返回都是同一个 `PageResult<T>`，可以共用一个构造器；
 * 查询参数的类型则由 `mockImplementation` 从被 mock 的函数签名里反推，
 * 不在这里重复声明（重复声明过一次，和真实的 `listUsers` 签名对不上）。
 */
function stubPage<T>(
  list: T[],
  query: { pageNum: number; pageSize: number },
): PageResult<T> {
  return {
    list,
    total: list.length,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }
}

/** 四个列表接口的默认替身：返回空页，需要数据的用例在自己的 `it` 里覆盖。 */
function stubListApis(): void {
  org.listUsers.mockImplementation(async (query) => stubPage([], query))
  roles.listRoles.mockImplementation(async (query) => stubPage([], query))
  resources.listResources.mockImplementation(async (query) => stubPage([], query))
  params.listSystemParams.mockImplementation(async (query) => stubPage([], query))
}

beforeEach(() => {
  vi.clearAllMocks()

  stubListApis()
  org.getDepartmentTree.mockResolvedValue([
    {
      id: '1001',
      parent_id: null,
      department_code: 'D001',
      department_name: '总公司',
      status: 'ACTIVE',
      children: [
        {
          id: '1002',
          parent_id: '1001',
          department_code: 'D002',
          department_name: '华东区',
          status: 'ACTIVE',
          children: [],
        },
      ],
    },
  ])
  roles.listRoles.mockResolvedValue({ list: [], total: 0, pageNum: 1, pageSize: 20 })
  resources.listResources.mockResolvedValue({ list: [], total: 0, pageNum: 1, pageSize: 20 })
  dicts.getPublicDict.mockResolvedValue({
    dict_code: 'user_status',
    dict_name: '用户状态',
    description: null,
    items: [],
  })
})

/**
 * 挂载一个视图并等它把首屏请求跑完。
 *
 * 参数类型刻意用 `Component` 而不是 `DefineComponent`：`DefineComponent`
 * 不带类型参数时是一个"默认泛型"的版本，和 `<script setup>` 编译出来的组件
 * 类型对不上，十几个调用点会全报 TS2345。
 */
async function mountView(component: Component) {
  const wrapper = mount(component)
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('部门管理页', () => {
  it('挂载后从 store 渲染出部门树与层级缩进', async () => {
    const departments = useOrganizationStore()
    const wrapper = await mountView(DepartmentListView)

    expect(org.getDepartmentTree).toHaveBeenCalledTimes(1)
    expect(departments.loaded).toBe(true)
    const text = wrapper.text()
    expect(text).toContain('总公司')
    expect(text).toContain('华东区')
  })

  it('写操作之后树被重拉（重拉由 store 负责，页面不再自己调 load）', async () => {
    org.disableDepartment.mockResolvedValue(undefined)
    // PermissionButton 默认 `mode="hide"`：没拿到 BUTTON 权限时压根不渲染，
    // 这里得先把按钮权限给它，否则点不到"禁用"。
    usePermissionStore().buttonCodes = new Set(['department:disable'])
    const wrapper = await mountView(DepartmentListView)
    expect(org.getDepartmentTree).toHaveBeenCalledTimes(1)

    const disable = wrapper.findAll('button').filter((button) => button.text() === '禁用')
    expect(disable.length).toBeGreaterThan(0)
    await disable[0]?.trigger('click')

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    // 确认框的"确认"按钮：点它就是走禁用流程（危险操作必须二次确认）。
    //
    // ⚠️ 弹窗不在 wrapper 里：naive 的 Modal 会传送到 `body`（避免被父级
    // 的 transform / overflow 裁切），所以这里必须查真实文档，而不是
    // `wrapper.find`。`role="dialog"` 仍在，无障碍语义没有退化。
    const buttons = Array.from(dialog?.querySelectorAll('button') ?? [])
    buttons.at(-1)?.click()
    await flushPromises()

    expect(org.disableDepartment).toHaveBeenCalledTimes(1)
    // 首次加载 + 写后重拉：页面里不该再出现第三处自己调的 load。
    expect(org.getDepartmentTree).toHaveBeenCalledTimes(2)
  })
})

describe('用户管理页', () => {
  it('部门下拉来自 organizationStore，不是自己再拉一次树', async () => {
    org.listUsers.mockResolvedValue({
      list: [],
      total: 0,
      pageNum: 1,
      pageSize: 20,
    })

    const wrapper = await mountView(UserListView)

    expect(org.getDepartmentTree).toHaveBeenCalledTimes(1)
    const options = wrapper.findAll('option').map((option) => option.text())
    // 标签是完整继承路径，子部门也在选项里。
    expect(options).toContain('总公司')
    expect(options).toContain('总公司 / 华东区')
  })
})

describe('角色管理页', () => {
  it('分页数据来自 rolesStore', async () => {
    roles.listRoles.mockResolvedValue({
      list: [
        {
          id: '9001',
          role_code: 'SUPER_ADMIN',
          role_name: '超级管理员',
          description: null,
          status: 'ACTIVE',
          data_scope: 'ALL',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })

    const wrapper = await mountView(RoleListView)

    expect(useRolesStore().rows).toHaveLength(1)
    expect(wrapper.text()).toContain('超级管理员')
  })
})

describe('系统参数页', () => {
  it('清空当前值是独立动作，不夹带 param_value', async () => {
    params.listSystemParams.mockResolvedValue({
      list: [
        {
          id: '700001',
          param_key: 'MFA_REQUIRED_DEFAULT',
          param_name: '默认强制 MFA',
          param_type: 'BOOL',
          param_value: 'true',
          default_value: 'false',
          effective_value: 'true',
          description: null,
          status: 'ACTIVE',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })
    const wrapper = await mountView(ParamListView)
    // 这个 store 没有 loaded 标记（不像 organization / roles / resources），
    // 用 `loading` 落回 false 来证明 onMounted 的加载链路真的跑完了。
    expect(useParamsStore().loading).toBe(false)
    expect(useParamsStore().rows).toHaveLength(1)
    // 参数键那一列渲染的是操作按钮，键名只出现在"参数名"列里 ——
    // 断言改落在参数名上，别去猜模板结构。
    expect(wrapper.text()).toContain('默认强制 MFA')
  })
})

describe('权限资源维护页', () => {
  it('列表与树两种模式都能挂载', async () => {
    resources.listResources.mockResolvedValue({
      list: [
        {
          id: '8001',
          resource_type: 'PAGE',
          resource_code: 'system:user:page',
          resource_name: '用户管理',
          parent_id: null,
          sort_order: 10,
          status: 'ACTIVE',
          route_path: '/system/users',
          component_path: '',
          icon: null,
          api_method: null,
          api_path: null,
          field_key: null,
          owner_resource_id: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })

    const wrapper = await mountView(PermissionResourceListView)

    expect(useResourcesStore().rows).toHaveLength(1)
    expect(wrapper.text()).toContain('用户管理')
  })
})

describe('权限配置页', () => {
  it('角色清单与资源清单都走 store，且能落到勾选框上', async () => {
    roles.listRoles.mockResolvedValue({
      list: [
        {
          id: '9001',
          role_code: 'SUPER_ADMIN',
          role_name: '超级管理员',
          description: null,
          status: 'ACTIVE',
          data_scope: 'ALL',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })
    resources.listResources.mockImplementation(async (query) => ({
      list:
        query.resourceType === 'PAGE'
          ? [
              {
                id: '8001',
                resource_type: 'PAGE' as const,
                resource_code: 'system:user:page',
                resource_name: '用户管理',
                parent_id: null,
                sort_order: 10,
                status: 'ACTIVE' as const,
                route_path: '/system/users',
                component_path: '',
                icon: null,
                api_method: null,
                api_path: null,
                field_key: null,
                owner_resource_id: null,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
              },
            ]
          : [],
      total: 1,
      pageNum: query.pageNum,
      pageSize: query.pageSize,
    }))
    roles.getRolePermissions.mockResolvedValue({
      role_id: '9001',
      page_ids: [],
      menu_ids: [],
      button_ids: [],
      api_ids: [],
      field_levels: {},
    })
    roles.getRoleDataScope.mockResolvedValue({
      role_id: '9001',
      data_scope: 'ALL',
      department_ids: [],
    })

    const wrapper = await mountView(PermissionListView)

    const rolesStore = useRolesStore()
    expect(rolesStore.pickerLoaded).toBe(true)
    expect(useResourcesStore().grantableLoaded).toBe(true)
    expect(wrapper.text()).toContain('超级管理员')
    expect(wrapper.text()).toContain('用户管理')
  })
})
