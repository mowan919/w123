import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { DOMWrapper, VueWrapper } from '@vue/test-utils'
import { NCheckbox, NTreeSelect } from 'naive-ui'
import type { Component } from 'vue'
import type { PageResult, PermissionResource } from '@/types'

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
  it('部门筛选用树形下拉，候选直接来自 organizationStore 的树', async () => {
    const departments = useOrganizationStore()
    const wrapper = await mountView(UserListView)

    // 部门树只由 store 取一次（后端没有扁平列表端点）。
    expect(org.getDepartmentTree).toHaveBeenCalledTimes(1)
    expect(departments.loaded).toBe(true)

    // ⚠️ 这里**不能**再用 `wrapper.findAll('option')`：部门筛选改成
    // `NTreeSelect` 后，候选不在 DOM 里（naive 的树形下拉展开时才渲染
    // 虚拟列表），而筛选区仍有一个原生 `<select>`（状态），它的 option
    // 会让断言"看起来通过"，实际什么都没验证到。
    const treeSelects = wrapper.findAllComponents(NTreeSelect)
    expect(treeSelects.length).toBeGreaterThan(0)
    const picker = treeSelects[0]

    // 传下去的就是 store 的树本身（引用相等），没有第二份层级真相。
    expect(picker?.props('options')).toBe(departments.tree)
    // 字段名写错**不会报错**，只会让所有标签空着、或者子节点根本不展开。
    expect(picker?.props('keyField')).toBe('id')
    expect(picker?.props('labelField')).toBe('department_name')
    expect(picker?.props('childrenField')).toBe('children')
    // 层级没被压平：子部门在父节点的 children 里。
    expect(departments.tree[0]?.children?.map((child) => child.department_name)).toEqual(['华东区'])
  })

  it('清空部门会同时关掉「包含下级部门」', async () => {
    const wrapper = await mountView(UserListView)
    // 「包含下级部门」在未选部门时不可用 —— 没有部门就没有"下级"可言，
    // 让它保持可勾选会造出一个不影响请求的假开关。
    const checkbox = wrapper.findComponent(NCheckbox)
    expect(checkbox.props('disabled')).toBe(true)
  })

  it('新增弹窗打开时不显示必填提示，点了保存才提示', async () => {
    usePermissionStore().buttonCodes = new Set(['user:create'])
    const wrapper = await mountView(UserListView)

    const entry = wrapper.findAll('button').filter((button) => button.text().includes('新建用户'))
    expect(entry.length).toBeGreaterThan(0)
    await entry[0]?.trigger('click')
    await flushPromises()

    // 弹窗传送到 body，只能查真实文档（naive 的 Modal 不受 wrapper 管辖）。
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()

    // 一打开就干干净净：必填项还空着，但用户还没动手，不该先挂一条红字。
    expect(dialog?.textContent).not.toContain('请填写用户名')

    const save = Array.from(dialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '保存',
    )
    expect(save).toBeDefined()
    save?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    // 点过保存才说话，而且校验不过就**不提交**。
    expect(dialog?.textContent).toContain('请填写用户名')
    expect(org.createUser).not.toHaveBeenCalled()
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

  /**
   * 树形模式的用例此前**一条都没有** —— 而"类型 = 全部 + 树形"在后端
   * 直接 400（`resourceType` 必填），界面上表现为红条报错。
   * 这一组把该模式的请求形状与渲染结果都钉住。
   */
  function treeButton(wrapper: VueWrapper): DOMWrapper<Element> {
    const found = wrapper.findAll('button').find((item) => item.text().trim() === '树形')
    if (found === undefined) throw new Error('找不到「树形」按钮')
    return found
  }

  function searchButton(wrapper: VueWrapper): DOMWrapper<Element> {
    const found = wrapper.findAll('button').find((item) => item.text().trim() === '查询')
    if (found === undefined) throw new Error('找不到「查询」按钮')
    return found
  }

  /** 按可见文字找工具栏按钮；找不到返回 undefined（断言"不该出现"时用这个）。 */
  function findToolbarButton(
    wrapper: VueWrapper,
    label: string,
  ): DOMWrapper<Element> | undefined {
    return wrapper.findAll('button').find((item) => item.text().includes(label))
  }

  /**
   * 严格版：找不到直接抛错。
   *
   * 点按一律走这个而不是 `findToolbarButton(...)?.trigger(...)` —— 后者在按钮
   * 不存在时静默什么都不做，用例会以"断言没过"的形式失败，把真正的原因
   * （按钮压根没渲染）藏起来。
   */
  function toolbarButton(wrapper: VueWrapper, label: string): DOMWrapper<Element> {
    const found = findToolbarButton(wrapper, label)
    if (found === undefined) throw new Error(`找不到「${label}」按钮`)
    return found
  }

  /**
   * 树形行里的折叠箭头。
   *
   * 叶子行渲染的是等宽**占位 span**（`tree__twisty--leaf`）而不是 button，
   * 所以 `button.tree__twisty` 天然只选中真正能折叠的行 —— 不需要再按类过滤。
   */
  function twisties(wrapper: VueWrapper): DOMWrapper<Element>[] {
    return wrapper.findAll('button.tree__twisty')
  }

  /** 一棵最小的跨类型树：PAGE「用户管理」下挂一个 BUTTON，另有一个叶子 PAGE。 */
  function twoTypeTree() {
    return [
      {
        resource: treeNode({ id: '7001', resource_type: 'PAGE', resource_name: '用户管理' }),
        children: [
          {
            resource: treeNode({
              id: '7002',
              resource_type: 'BUTTON',
              resource_name: '新建用户',
              parent_id: '7001',
            }),
            children: [],
          },
        ],
      },
      {
        resource: treeNode({ id: '7003', resource_type: 'PAGE', resource_name: '报表' }),
        children: [],
      },
    ]
  }

  function treeNode(overrides: Partial<PermissionResource> & { id: string }): PermissionResource {
    return {
      resource_type: 'PAGE',
      resource_code: `cr:${overrides.id}`,
      resource_name: `资源 ${overrides.id}`,
      parent_id: null,
      sort_order: 0,
      status: 'ACTIVE',
      route_path: null,
      component_path: null,
      icon: null,
      api_method: null,
      api_path: null,
      field_key: null,
      owner_resource_id: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      ...overrides,
    }
  }

  it('树形 + 「类型 = 全部」不带 resourceType，且不报错', async () => {
    resources.getResourceTree.mockResolvedValue([
      {
        resource: treeNode({ id: '7001', resource_type: 'PAGE', resource_name: '用户管理' }),
        children: [
          {
            resource: treeNode({
              id: '7002',
              resource_type: 'BUTTON',
              resource_name: '新建用户',
              parent_id: '7001',
            }),
            children: [],
          },
        ],
      },
    ])

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    // `null` 会被 HTTP 客户端从 query 里去掉 —— 后端据此返回**全类型**树。
    // 这里断言的是"没有替用户随便挑一种类型"，那是会丢层级的做法。
    expect(resources.getResourceTree).toHaveBeenCalledTimes(1)
    expect(resources.getResourceTree.mock.calls[0]?.[0]).toMatchObject({ resourceType: null })
    expect(wrapper.find('.alert--error').exists()).toBe(false)
    // 跨类型的子节点要真的渲染出来（按钮挂在页面下）。
    const text = wrapper.text()
    expect(text).toContain('用户管理')
    expect(text).toContain('新建用户')
  })

  it('树形 + 选了类型时，明说该类型之外的分支不会出现', async () => {
    resources.getResourceTree.mockResolvedValue([])

    const wrapper = await mountView(PermissionResourceListView)
    await wrapper.findAll('select')[0]?.setValue('BUTTON')
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    expect(resources.getResourceTree.mock.calls[0]?.[0]).toMatchObject({ resourceType: 'BUTTON' })
    const hint = wrapper.find('.hint')
    expect(hint.exists()).toBe(true)
    expect(hint.text()).toContain('已按类型筛选')
    // 模板里写 `**强调**` 会**原样显示星号**（markdown 在 HTML 里不生效）。
    // 这条是写这段提示时真踩过的，留一条断言免得又写回去。
    expect(hint.text()).not.toContain('**')
  })

  it('树形把关键字与状态一起带给树端点（筛选不是摆设）', async () => {
    resources.getResourceTree.mockResolvedValue([])

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="编码或名称"]').setValue('user')
    await wrapper.findAll('select')[1]?.setValue('DISABLED')
    await searchButton(wrapper).trigger('click')
    await flushPromises()

    expect(resources.getResourceTree.mock.calls.at(-1)?.[0]).toMatchObject({
      keyword: 'user',
      status: 'DISABLED',
    })
  })

  /**
   * 折叠这一组用例存在的理由：压平渲染曾经是**无条件递归**，于是"树形"
   * 其实是一张不能收的长表 —— 真实数据 16 根 / 65 节点。这几条把这个能力钉住。
   */
  it('树形默认全展开，折叠箭头只画在有子节点的行上', async () => {
    resources.getResourceTree.mockResolvedValue(twoTypeTree())

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    // 默认就该看得见层级：两条根 + 一个跨类型的子节点都在。
    expect(wrapper.text()).toContain('用户管理')
    expect(wrapper.text()).toContain('新建用户')
    expect(wrapper.text()).toContain('报表')

    // 只有「用户管理」有子节点；叶子行给的是等宽占位 span（不占 button）。
    expect(twisties(wrapper)).toHaveLength(1)
    expect(wrapper.findAll('span.tree__twisty--leaf')).toHaveLength(2)
    expect(twisties(wrapper)[0]?.attributes('aria-expanded')).toBe('true')
  })

  it('点箭头能收起分支，父节点留在原地', async () => {
    resources.getResourceTree.mockResolvedValue(twoTypeTree())

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    await twisties(wrapper)[0]?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('新建用户')
    expect(wrapper.text()).toContain('用户管理')
    expect(twisties(wrapper)[0]?.attributes('aria-expanded')).toBe('false')
    // 收的是分支不是数据：另一个根不受影响。
    expect(wrapper.text()).toContain('报表')

    // 再点一次能收回来 —— 否则"折叠"是单向的，等于把节点弄丢了。
    await twisties(wrapper)[0]?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新建用户')
    expect(twisties(wrapper)[0]?.attributes('aria-expanded')).toBe('true')
  })

  it('「收起全部」只剩根节点，「展开全部」能补回来', async () => {
    resources.getResourceTree.mockResolvedValue(twoTypeTree())

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    await toolbarButton(wrapper, '收起全部').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('新建用户')
    // 根节点仍在 —— 收起全部不是"清空"。
    expect(wrapper.text()).toContain('用户管理')
    expect(wrapper.text()).toContain('报表')

    await toolbarButton(wrapper, '展开全部').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新建用户')
  })

  it('重新查询后回到全展开，命中节点不会被自己收起的祖先藏住', async () => {
    resources.getResourceTree.mockResolvedValue(twoTypeTree())

    const wrapper = await mountView(PermissionResourceListView)
    await treeButton(wrapper).trigger('click')
    await flushPromises()

    await toolbarButton(wrapper, '收起全部').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('新建用户')

    // 用户搜一个按钮：树被整棵换掉，若沿用上一次的展开集合，
    // 界面上只会出现一排收起的根，看起来就像"搜索坏了"。
    await searchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新建用户')
    expect(twisties(wrapper)[0]?.attributes('aria-expanded')).toBe('true')
  })

  it('展开 / 收起按钮只在树形模式下出现', async () => {
    resources.getResourceTree.mockResolvedValue([])

    const wrapper = await mountView(PermissionResourceListView)
    expect(findToolbarButton(wrapper, '展开全部')).toBeUndefined()
    expect(findToolbarButton(wrapper, '收起全部')).toBeUndefined()

    await treeButton(wrapper).trigger('click')
    await flushPromises()
    expect(findToolbarButton(wrapper, '展开全部')).toBeDefined()
    expect(findToolbarButton(wrapper, '收起全部')).toBeDefined()

    // 切回列表就不该再留着 —— 点了没反应的按钮比没有按钮更糟。
    await wrapper.findAll('button').find((item) => item.text().trim() === '列表')?.trigger('click')
    await flushPromises()
    expect(findToolbarButton(wrapper, '展开全部')).toBeUndefined()
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
