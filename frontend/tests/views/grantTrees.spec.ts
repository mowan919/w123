import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { DOMWrapper, VueWrapper } from '@vue/test-utils'
import type { GrantKind, GrantSelection, ID, PermissionResource, ResourceType, Role } from '@/types'

/**
 * 授权面（需求 4 / 5）：权限配置页与「新增角色」弹窗用的是**同一棵资源树**。
 *
 * 这里断的不是"树画出来了"，而是三条会静默出错的规则：
 *
 * 1. **层级来自后端关系**，页面挂在菜单下、按钮挂在页面下 —— 不是四列
 *    互不相干的扁平复选框（那正是这次要修掉的东西）。
 * 2. **提交是"清单内的勾选 ∪ 清单外的既有授权"**。资源清单是分类取回且
 *    有上限的，直接提交"清单内勾选"会把这个角色没被取回的授权静默删掉 ——
 *    表现是"我什么都没改，保存一下权限就少了一块"。
 * 3. **逐类提交、逐类报错**。四类是四次整体替换，用 `Promise.all` 只会
 *    报出第一个错误，其余类别是成是败无从得知，而界面此时显示的是本地勾选。
 */

vi.mock('@/api/endpoints/roles', async (importOriginal) => {
  // ⚠️ `putRoleGrant` 也要换成替身，虽然它是"按类别分派到四个端点"的那一层。
  // 原因：真实实现调用的是**同模块内的原始函数**，这里 `vi.mock` 出来的
  // 四个替身收不到调用 —— 断言会全绿，而"分派写错"根本测不出来（实测踩过）。
  // 所以分工是：
  //   · 本文件（视图层）断言 `putRoleGrant` 被按哪几类、用什么 id 调用；
  //   · `tests/api/roles.spec.ts`（真实实现 + 假 fetch）断言四类各自打到哪条 URL。
  const actual = await importOriginal<typeof rolesApi>()
  return {
    ...actual,
    listRoles: vi.fn(),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
    getRolePermissions: vi.fn(),
    putRoleGrant: vi.fn(),
    setRolePagePermissions: vi.fn(),
    setRoleMenuPermissions: vi.fn(),
    setRoleButtonPermissions: vi.fn(),
    setRoleApiPermissions: vi.fn(),
    setRoleFieldPermissions: vi.fn(),
    getRoleDataScope: vi.fn(),
    setRoleDataScope: vi.fn(),
  }
})

vi.mock('@/api/endpoints/resources', () => ({
  listResources: vi.fn(),
  getResourceTree: vi.fn(),
  createResource: vi.fn(),
  updateResource: vi.fn(),
  deleteResource: vi.fn(),
  getMenuPages: vi.fn(),
  setMenuPages: vi.fn(),
}))

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

import * as rolesApi from '@/api/endpoints/roles'
import * as resourcesApi from '@/api/endpoints/resources'
import * as orgApi from '@/api/endpoints/organization'
import PermissionListView from '@/views/system/PermissionListView.vue'
import RoleListView from '@/views/system/RoleListView.vue'
import PermissionTree from '@/components/permission/PermissionTree.vue'
import { usePermissionStore } from '@/stores/permission'
import { useAppStore } from '@/stores/app'

const roles = vi.mocked(rolesApi)
const resources = vi.mocked(resourcesApi)
const org = vi.mocked(orgApi)

// ---------------------------------------------------------------- 替身数据

function resource(
  id: string,
  type: ResourceType,
  name: string,
  extra: Partial<PermissionResource> = {},
): PermissionResource {
  return {
    id,
    resource_type: type,
    resource_code: `code-${id}`,
    resource_name: name,
    parent_id: null,
    sort_order: 10,
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
    ...extra,
  }
}

/**
 * 一棵刻意不按命名规律的数据：页面 `用户列表` 的编码与菜单 `用户管理`
 * 毫无关系，层级只能来自 `menu_pages`。
 */
const MENUS = [
  resource('m1', 'MENU', '系统管理', { sort_order: 10 }),
  resource('m2', 'MENU', '用户管理', { parent_id: 'm1', sort_order: 20 }),
]
const PAGES = [resource('p1', 'PAGE', '用户列表', { sort_order: 10 })]
const BUTTONS = [resource('b1', 'BUTTON', '新建用户', { parent_id: 'p1' })]
const APIS = [resource('a1', 'API', 'USER_MANAGE', { parent_id: 'p1', api_method: 'GET' })]

const CATALOG: Record<ResourceType, PermissionResource[]> = {
  MENU: MENUS,
  PAGE: PAGES,
  BUTTON: BUTTONS,
  API: APIS,
  FIELD: [],
}

/**
 * 直接挂 `PermissionTree` 组件（不经视图），为了构造视图层拿不到的状态：
 * 资源清单**尚未取回**（四类皆空）、或菜单挂载关系与常规不同。
 *
 * `menuPages` 必须显式传入而不是取默认值：它决定"哪些页面有导航入口"，
 * 而这恰恰是「未挂载菜单的页面」分组出不出现的唯一变量 ——
 * 悄悄给个默认值会让异常用例变成永远绿。
 */
function mountResourceTree(
  menus: PermissionResource[],
  pages: PermissionResource[],
  buttons: PermissionResource[],
  apis: PermissionResource[],
  menuPages: Record<ID, ID[]>,
  modelValue: GrantSelection = { PAGE: [], MENU: [], BUTTON: [], API: [] },
): VueWrapper {
  return mount(PermissionTree, {
    props: { menus, pages, buttons, apis, menuPages, modelValue },
  })
}

function role(id: string): Role {
  return {
    id,
    role_code: 'AUDITOR',
    role_name: '审计员',
    description: null,
    status: 'ACTIVE',
    data_scope: 'ALL',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

beforeEach(() => {
  vi.clearAllMocks()

  roles.listRoles.mockImplementation(async (query) => ({
    list: [role('9001')],
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
  roles.createRole.mockResolvedValue(role('9100'))

  resources.listResources.mockImplementation(async (query) => {
    const list = query.resourceType === undefined || query.resourceType === null
      ? []
      : CATALOG[query.resourceType]
    return { list, total: list.length, pageNum: query.pageNum, pageSize: query.pageSize }
  })
  resources.getMenuPages.mockResolvedValue({ menu_id: 'm2', pages: PAGES })

  org.getDepartmentTree.mockResolvedValue([])
})

// ---------------------------------------------------------------- 交互辅助

/** 挂到 document 上的实例，`afterEach` 统一卸载（否则 DOM 会跨用例累积）。 */
const mounted: VueWrapper[] = []

afterEach(() => {
  while (mounted.length > 0) {
    mounted.pop()?.unmount()
  }
})

async function mountView(component: unknown): Promise<VueWrapper> {
  // ⚠️ 必须 `attachTo`：本文件断言的是 `document.querySelectorAll('.ptree__row')`，
  // 不挂到文档上，组件就渲染在一个游离容器里 —— 文档级查询只会查到空气，
  // 表现为"每个用例都找不到树节点"，而组件本身完全正常（见 zzDebug 对照）。
  const wrapper = mount(component as never, { attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  await flushPromises()
  await flushPromises()
  return wrapper
}

/** 树里某一行的名称（用于断言渲染出了哪些节点）。 */
function treeNames(): string[] {
  return Array.from(document.querySelectorAll('.ptree__row')).map(
    (row) => row.querySelector('.ptree__name')?.textContent?.trim() ?? '',
  )
}

/** 树里某一行的缩进深度（`paddingLeft = 8 + depth * 22`）。 */
function treeDepth(name: string): number | null {
  const row = Array.from(document.querySelectorAll('.ptree__row')).find(
    (item) => item.querySelector('.ptree__name')?.textContent?.trim() === name,
  )
  if (row === undefined) return null
  const padding = Number.parseInt((row as HTMLElement).style.paddingLeft, 10)
  return Number.isNaN(padding) ? null : (padding - 8) / 22
}

/** 某一类最近一次提交的 id 清单。 */
function lastGrant(kind: GrantKind): ID[] {
  const calls = roles.putRoleGrant.mock.calls.filter((call) => call[0] === kind)
  return calls.at(-1)?.[2] ?? []
}

/** 某一类被提交了几次。 */
function grantCallCount(kind: GrantKind): number {
  return roles.putRoleGrant.mock.calls.filter((call) => call[0] === kind).length
}

/** 勾选 / 取消树上的某个节点（点它的勾选框，触发向下级联）。 */
async function toggleTreeNode(name: string): Promise<void> {
  const row = Array.from(document.querySelectorAll('.ptree__row')).find(
    (item) => item.querySelector('.ptree__name')?.textContent?.trim() === name,
  )
  if (row === undefined) throw new Error(`找不到树节点：${name}`)
  const box = row.querySelector('.n-checkbox')
  if (box === null) throw new Error(`该节点不可勾选：${name}`)
  box.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

/** 在某个容器（页面或弹窗）里按文字点按钮。 */
async function clickButton(scope: ParentNode, text: string): Promise<void> {
  const button = Array.from(scope.querySelectorAll('button')).find(
    (item) => item.textContent?.trim() === text,
  )
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

/** 给原生 input 赋值并触发 Vue 的 v-model。 */
function setInput(input: Element | null, value: string): void {
  if (input === null) throw new Error('找不到输入框')
  ;(input as HTMLInputElement).value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function dialog(): Element {
  const found = document.querySelector('[role="dialog"]')
  if (found === null) throw new Error('弹窗未打开')
  return found
}

/** 在权限树头部按文字点批量按钮（「全选 / 取消全部 / 反选」）。 */
async function clickBulk(text: string): Promise<void> {
  const head = document.querySelector('.ptree-head')
  if (head === null) throw new Error('权限树头部未渲染')
  await clickButton(head, text)
}

/** 树头部的「已授权 N / M 项」摘要（模板换行压成单空格，便于整体比对）。 */
function grantSummary(): string {
  const node = document.querySelector('.ptree-head__summary')
  return node?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
}

// ---------------------------------------------------------------- 需求 4

describe('权限配置页 —— 资源按真实层级联动（需求 4）', () => {
  it('菜单 → 页面 → 按钮 / 接口 逐层嵌套，不是四列扁平复选框', async () => {
    await mountView(PermissionListView)

    expect(treeNames()).toEqual(expect.arrayContaining(['系统管理', '用户管理', '用户列表', '新建用户']))
    expect(treeDepth('系统管理')).toBe(0)
    expect(treeDepth('用户管理')).toBe(1)
    // 页面挂在**菜单**下（层级来自 menu_pages，不是编码命名规律）。
    expect(treeDepth('用户列表')).toBe(2)
    expect(treeDepth('新建用户')).toBe(3)
  })

  it('点菜单把整支勾上，保存时按类别分别提交', async () => {
    usePermissionStore().buttonCodes = new Set(['role:assign-permission'])
    const wrapper = await mountView(PermissionListView)

    await toggleTreeNode('系统管理')
    await clickButton(wrapper.element, '保存权限')

    // 点菜单把整支带上：菜单自身 + 子菜单 + 挂载的页面 + 页面的按钮与接口。
    expect(roles.putRoleGrant).toHaveBeenCalledWith('MENU', '9001', ['m1', 'm2'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('PAGE', '9001', ['p1'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('BUTTON', '9001', ['b1'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('API', '9001', ['a1'])
  })

  it('只勾页面不勾按钮：页面留下、按钮不会被动带上', async () => {
    usePermissionStore().buttonCodes = new Set(['role:assign-permission'])
    const wrapper = await mountView(PermissionListView)

    // 点页面会级联带出它的按钮与接口；再单独取消按钮，页面必须留着。
    await toggleTreeNode('用户列表')
    await toggleTreeNode('新建用户')
    await clickButton(wrapper.element, '保存权限')

    expect(lastGrant('PAGE')).toEqual(['p1'])
    expect(lastGrant('BUTTON')).toEqual([])
  })

  it('清单之外的既有授权被原样保留，不会被整体替换静默删掉', async () => {
    roles.getRolePermissions.mockResolvedValue({
      role_id: '9001',
      page_ids: [],
      menu_ids: [],
      button_ids: [],
      // `a-out` 不在候选清单里（被截断 / 分类未取回），界面必须先说出来。
      api_ids: ['a-out'],
      field_levels: {},
    })
    usePermissionStore().buttonCodes = new Set(['role:assign-permission'])
    const wrapper = await mountView(PermissionListView)

    expect(wrapper.text()).toContain('未出现在上方清单中')

    await toggleTreeNode('用户列表')
    await clickButton(wrapper.element, '保存权限')

    // `a-out` 没出现在候选清单里，但它本来就在库中 —— 整体替换必须把它带上。
    expect(new Set(lastGrant('API'))).toEqual(new Set(['a1', 'a-out']))
  })
})

// ---------------------------------------------------------------- 需求 4（批量选择）

/**
 * 批量选择：全选 / 取消全部 / 反选。
 *
 * 这一组刻意放在**视图层**，而不是只留 `applyBulkSelection` 的纯函数单测。
 * 原因就是本项目反复踩的那条：分层各自 PASS ≠ 串联成立 ——
 * 按钮渲染出来、纯函数算对了，都不代表点下去真的会走到提交。
 * 所以每条断言都落到「点按钮 → 保存 → `putRoleGrant` 收到什么」。
 */
describe('权限配置页 —— 批量选择（需求 4）', () => {
  beforeEach(() => {
    usePermissionStore().buttonCodes = new Set(['role:assign-permission'])
  })

  it('「全选」把清单内的四类资源一次带上，摘要同步为 5/5', async () => {
    const wrapper = await mountView(PermissionListView)

    // 清单一共 5 项可授权资源：菜单 2 + 页面 1 + 按钮 1 + 接口 1。
    expect(grantSummary()).toBe('已授权 0 / 5 项')

    await clickBulk('全选')

    expect(grantSummary()).toBe('已授权 5 / 5 项')

    await clickButton(wrapper.element, '保存权限')

    expect(roles.putRoleGrant).toHaveBeenCalledWith('MENU', '9001', ['m1', 'm2'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('PAGE', '9001', ['p1'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('BUTTON', '9001', ['b1'])
    expect(roles.putRoleGrant).toHaveBeenCalledWith('API', '9001', ['a1'])
  })

  it('「取消全部」清掉清单内的勾选，清单之外的既有授权不会被顺手抹掉', async () => {
    roles.getRolePermissions.mockResolvedValue({
      role_id: '9001',
      page_ids: ['p1'],
      menu_ids: [],
      button_ids: [],
      // `a-out` 没有被取回到候选清单里（分类清单有上限），树上根本看不见它。
      api_ids: ['a-out'],
      field_levels: {},
    })
    const wrapper = await mountView(PermissionListView)

    await clickBulk('取消全部')
    await clickButton(wrapper.element, '保存权限')

    expect(lastGrant('PAGE')).toEqual([])
    // 看得见的清掉、看不见的原样保留 —— 否则一次「取消全部」会静默删掉
    // 这个角色没被取回的那部分授权，而界面上完全看不出来。
    expect(lastGrant('API')).toEqual(['a-out'])
  })

  it('「反选」逐个取反：勾上的变没勾、没勾的变勾上', async () => {
    const wrapper = await mountView(PermissionListView)

    // 先把「用户列表」整支勾上（页面 + 它的按钮与接口），菜单两项仍未勾。
    await toggleTreeNode('用户列表')
    expect(grantSummary()).toBe('已授权 3 / 5 项')

    await clickBulk('反选')

    expect(grantSummary()).toBe('已授权 2 / 5 项')

    await clickButton(wrapper.element, '保存权限')

    expect(new Set(lastGrant('MENU'))).toEqual(new Set(['m1', 'm2']))
    expect(lastGrant('PAGE')).toEqual([])
    expect(lastGrant('BUTTON')).toEqual([])
    expect(lastGrant('API')).toEqual([])
  })

  it('批量按钮只改本地勾选，一条授权请求都不发 —— 落库仍由「保存权限」决定', async () => {
    await mountView(PermissionListView)

    await clickBulk('全选')
    expect(grantSummary()).toBe('已授权 5 / 5 项')

    await clickBulk('取消全部')
    expect(grantSummary()).toBe('已授权 0 / 5 项')

    // 批量操作没有撤销入口：误点一次「取消全部」若当场落库，
    // 就是一次没有退路的权限清空。所以它必须只改本地状态。
    expect(roles.putRoleGrant).not.toHaveBeenCalled()
  })
})

describe('PermissionTree 组件 —— 批量按钮的可用性与载荷', () => {
  function mountTree(
    menus: PermissionResource[],
    pages: PermissionResource[],
    buttons: PermissionResource[],
    apis: PermissionResource[],
    modelValue: GrantSelection = { PAGE: [], MENU: [], BUTTON: [], API: [] },
  ): VueWrapper {
    // 常规挂载走模块级的 `mountResourceTree`：这份数据里 `p1` 挂在 `m2` 下，
    // 因此**没有**任何页面掉进异常分组（那些用例在下一个 describe 里）。
    return mountResourceTree(menus, pages, buttons, apis, { m2: ['p1'] }, modelValue)
  }

  function bulkButton(wrapper: VueWrapper, text: string): DOMWrapper<Element> {
    const found = wrapper.findAll('button').find((item) => item.text().trim() === text)
    if (found === undefined) throw new Error(`找不到按钮：${text}`)
    return found
  }

  it('清单为空时三个批量按钮都禁用', () => {
    // 此时「全选」什么都不会发生，但用户会以为已经选完了 ——
    // 点完看不到变化比按钮灰着更难排查。
    const wrapper = mountTree([], [], [], [])

    for (const text of ['全选', '取消全部', '反选']) {
      expect(bulkButton(wrapper, text).attributes('disabled')).toBeDefined()
    }
    wrapper.unmount()
  })

  it('有资源时三个批量按钮可用', () => {
    const wrapper = mountTree(MENUS, PAGES, BUTTONS, APIS)

    for (const text of ['全选', '取消全部', '反选']) {
      expect(bulkButton(wrapper, text).attributes('disabled')).toBeUndefined()
    }
    wrapper.unmount()
  })

  it('头部顺序固定为 摘要 → 批量 → 展开/收起（那条竖线的位置依赖它）', () => {
    // `.ptree-head__bulk` 的 `border-left` 只会落在它**前面**那个元素与本组之间。
    // 顺序一旦被改成"批量在最前"，这条线就会变成一堆按钮的起始装饰线，
    // 而"读数与可点项分开"的意图就没了 —— 这类失效在画面上很轻微，
    // 只能靠钉住 DOM 顺序来防。
    const wrapper = mountTree(MENUS, PAGES, BUTTONS, APIS)
    const head = wrapper.find('.ptree-head')
    const order = ['ptree-head__summary', 'ptree-head__bulk', 'ptree-head__spacer']

    let cursor = -1
    for (const cls of order) {
      const found = head.find(`.${cls}`)
      expect(found.exists()).toBe(true)
      const element = found.element
      const position = Array.from(head.element.children).indexOf(element)
      expect(position).toBeGreaterThan(cursor)
      cursor = position
    }
    // 展开/收起 在弹性空白之后（被推到最右）。
    const spacer = Array.from(head.element.children).indexOf(
      head.find('.ptree-head__spacer').element,
    )
    for (const text of ['展开全部', '收起全部']) {
      const child = head.findAll('button').find((b) => b.text().trim() === text)
      expect(child).toBeDefined()
      expect(Array.from(head.element.children).indexOf(child?.element as Element)).toBeGreaterThan(
        spacer,
      )
    }
    wrapper.unmount()
  })

  it('点「全选」派发一次 update:modelValue，只加树上看得见的资源、不动清单外的', async () => {
    // 起点里放一条树上不存在的既有授权，直接验"批量只碰看得见的东西"。
    const wrapper = mountTree(MENUS, PAGES, BUTTONS, APIS, {
      PAGE: [],
      MENU: [],
      BUTTON: [],
      API: ['a-out'],
    })

    await bulkButton(wrapper, '全选').trigger('click')

    const events = wrapper.emitted('update:modelValue')
    expect(events).toHaveLength(1)
    const next = events?.[0]?.[0] as GrantSelection

    expect(new Set(next.MENU)).toEqual(new Set(['m1', 'm2']))
    expect(new Set(next.PAGE)).toEqual(new Set(['p1']))
    expect(new Set(next.BUTTON)).toEqual(new Set(['b1']))
    // 清单外的 `a-out` 留在选择里，同时也带上了树上那个 `a1`。
    expect(new Set(next.API)).toEqual(new Set(['a-out', 'a1']))
    wrapper.unmount()
  })

  it('再点「取消全部」把 a1 摘掉，清单外的 a-out 仍然留着', async () => {
    const wrapper = mountTree(MENUS, PAGES, BUTTONS, APIS, {
      PAGE: ['p1'],
      MENU: ['m1', 'm2'],
      BUTTON: ['b1'],
      API: ['a1', 'a-out'],
    })

    await bulkButton(wrapper, '取消全部').trigger('click')

    const next = wrapper.emitted('update:modelValue')?.[0]?.[0] as GrantSelection
    expect(next.PAGE).toEqual([])
    expect(next.MENU).toEqual([])
    expect(next.BUTTON).toEqual([])
    expect(next.API).toEqual(['a-out'])
    wrapper.unmount()
  })
})

// ---------------------------------------------------------------- 未挂载的页面

describe('PermissionTree 组件 —— 「未挂载菜单的页面」要说清楚原因', () => {
  /**
   * 这一组曾经直接引出"为什么有 未挂载菜单的页面"这个问题 ——
   * 它长得像系统自带的分组，实际是**配置没配完**。
   * 组件必须做两件事：正常时**不出现**（不制造噪音），
   * 出现时**自带原因与条数**（不让用户对着分组名猜）。
   */

  it('全部页面都挂了菜单时不渲染提示条', () => {
    const wrapper = mountResourceTree(MENUS, PAGES, BUTTONS, APIS, { m2: ['p1'] })

    expect(wrapper.find('.ptree-anomaly').exists()).toBe(false)
    expect(wrapper.find('.ptree__row--anomaly').exists()).toBe(false)
    wrapper.unmount()
  })

  it('有页面没挂菜单时，提示条给出原因与条数，分组行被标记为待处理', () => {
    const orphan = resource('p2', 'PAGE', '权限资源', { sort_order: 20 })
    const wrapper = mountResourceTree(MENUS, [...PAGES, orphan], BUTTONS, APIS, { m2: ['p1'] })

    const bar = wrapper.find('.ptree-anomaly')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).toContain('没有导航入口')
    expect(bar.text()).toContain('1 项')

    // 分组本身仍然列出来（资源不得消失），并且带「待处理」标记。
    expect(wrapper.text()).toContain('未挂载菜单的页面')
    const row = wrapper.find('.ptree__row--anomaly')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('待处理')
    expect(row.text()).toContain('没有导航入口')
    wrapper.unmount()
  })

  it('上级菜单缺失时同样给出提示（另一类需要处理的配置）', () => {
    // 只给子菜单、不给它的父菜单 —— `m2` 会掉进「未归入上级菜单的菜单」。
    const wrapper = mountResourceTree(
      MENUS.filter((menu) => menu.id !== 'm1'),
      PAGES,
      BUTTONS,
      APIS,
      { m2: ['p1'] },
    )

    const bar = wrapper.find('.ptree-anomaly')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).toContain('上级菜单不存在')
    expect(wrapper.text()).toContain('未归入上级菜单的菜单')
    wrapper.unmount()
  })
})

// ---------------------------------------------------------------- 需求 5

describe('新增角色 —— 弹窗内勾选初始权限（需求 5）', () => {
  beforeEach(() => {
    usePermissionStore().buttonCodes = new Set(['role:create'])
  })

  /** 打开弹窗、填好必填字段，并返回弹窗元素。 */
  async function openCreateDialog(): Promise<Element> {
    const wrapper = await mountView(RoleListView)
    await clickButton(wrapper.element, '新增角色')
    const box = dialog()

    setInput(box.querySelector('input[placeholder="如 SUPER_ADMIN"]'), 'AUDITOR')
    setInput(box.querySelector('input[placeholder="如 超级管理员"]'), '审计员')
    await flushPromises()
    return box
  }

  it('弹窗里有「拥有哪些权限」小节与同一棵资源树', async () => {
    const box = await openCreateDialog()

    expect(box.textContent).toContain('拥有哪些权限')
    expect(treeNames()).toEqual(expect.arrayContaining(['系统管理', '用户列表', '新建用户']))
  })

  it('创建后按勾选的类别提交初始授权，没勾的类别不发请求', async () => {
    const box = await openCreateDialog()

    await toggleTreeNode('用户列表')
    await clickButton(box, '保存')

    expect(roles.createRole).toHaveBeenCalledTimes(1)
    expect(lastGrant('PAGE')).toEqual(['p1'])
    expect(lastGrant('BUTTON')).toEqual(['b1'])
    expect(lastGrant('API')).toEqual(['a1'])
    // 菜单一类一项都没勾 → 空操作不该发出去（否则平白多一条审计）。
    expect(grantCallCount('MENU')).toBe(0)
  })

  it('一项都不勾也能建角色，且不发任何授权请求', async () => {
    const box = await openCreateDialog()

    await clickButton(box, '保存')

    expect(roles.createRole).toHaveBeenCalledTimes(1)
    // 一项都没勾 ⇒ 四类都是空集 ⇒ 一条授权请求都不该发（否则平白多四条审计）。
    expect(roles.putRoleGrant).not.toHaveBeenCalled()
    expect(useAppStore().notice?.type).toBe('success')
  })

  it('某一类授权失败时如实说出是哪一类，而不是笼统地"保存失败"', async () => {
    roles.putRoleGrant.mockImplementation(async (kind) => {
      if (kind === 'API') throw new Error('boom')
    })
    const box = await openCreateDialog()

    await toggleTreeNode('用户列表')
    await clickButton(box, '保存')

    // 角色本身已经建好了：说"失败"是假话，说"成功"更假。
    expect(roles.createRole).toHaveBeenCalledTimes(1)
    expect(useAppStore().notice?.type).toBe('error')
    expect(useAppStore().notice?.message).toContain('接口')
    expect(useAppStore().notice?.message).toContain('已创建')
  })

  it('编辑角色时不出现权限树（调整授权是权限配置页的职责）', async () => {
    const wrapper = await mountView(RoleListView)
    usePermissionStore().buttonCodes = new Set(['role:update'])
    await flushPromises()

    await clickButton(wrapper.element, '编辑')
    const box = dialog()

    expect(box.textContent).not.toContain('拥有哪些权限')
    expect(treeNames()).toEqual([])
  })
})
