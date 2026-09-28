import { describe, expect, it } from 'vitest'
import {
  ANOMALY_GROUP_NAME,
  ANOMALY_HINT,
  applyBulkSelection,
  applyCascade,
  buildPermissionTree,
  collectAnomalies,
  collectKeys,
  flattenTree,
  grantKey,
  keysOfTree,
  resolveSubmission,
  selectionToSet,
  unavailableCount,
  universeOf,
} from '@/composables/usePermissionTree'
import type { PermissionTreeInput } from '@/composables/usePermissionTree'
import { emptySelection } from '@/types'
import type { GrantSelection, PermissionResource, ResourceType } from '@/types'

/**
 * `usePermissionTree`（权限配置页 / 新增角色弹窗的层级列表）。
 *
 * 这里钉的是四条**行为契约**，每一条都对应一个真实事故面：
 *
 * 1. **父子不派生**：真实数据里 `DEPARTMENT_ADMIN` 持有页面但不持有
 *    该页面的全部按钮。若父项状态由子项推导，任何人保存一次都会把这个
 *    角色的授权改成另一个形状（页面被吞或按钮被放大）。
 * 2. **层级来自后端 `menu_pages`**，不是资源编码的命名规律 ——
 *    按约定推会在编码不规范时让页面从界面上**静默消失**。
 * 3. **资源不得消失**：未挂载的页面、父菜单缺失的菜单都必须仍然渲染出来，
 *    否则"授权了却不生效"无从排查。
 * 4. **清单之外的既有授权必须保留**：保存是"整体替换"语义，
 *    直接提交"清单内勾选"会静默删掉没被取回的授权。
 */

function res(
  id: string,
  type: ResourceType,
  code: string,
  extra: Partial<PermissionResource> = {},
): PermissionResource {
  return {
    id,
    resource_type: type,
    resource_code: code,
    resource_name: `名称-${code}`,
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
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...extra,
  }
}

/**
 * 一份刻意"编码不规范"的数据。
 *
 * `user-page` 这个页面**不叫** `system:user:page`，正是为了证明层级
 * 来自 `menu_pages` 而不是命名规律；`orphan-page` 完全没有被任何菜单挂载。
 */
function input(overrides: Partial<PermissionTreeInput> = {}): PermissionTreeInput {
  const menus = [
    res('m1', 'MENU', 'system:system', { sort_order: 10 }),
    res('m2', 'MENU', 'system:user', { parent_id: 'm1', sort_order: 20 }),
    res('m3', 'MENU', 'system:role', { parent_id: 'm1', sort_order: 30 }),
  ]
  const pages = [
    res('p1', 'PAGE', 'user-page', { sort_order: 10, route_path: '/system/users' }),
    res('p2', 'PAGE', 'role-page', { sort_order: 20, route_path: '/system/roles' }),
    res('p3', 'PAGE', 'orphan-page', { sort_order: 30, route_path: '/system/orphans' }),
  ]
  const buttons = [
    res('b1', 'BUTTON', 'user:create', { parent_id: 'p1' }),
    res('b2', 'BUTTON', 'user:update', { parent_id: 'p1' }),
    res('b3', 'BUTTON', 'role:create', { parent_id: 'p2' }),
  ]
  const apis = [
    res('a1', 'API', 'USER_MANAGE', { parent_id: 'p1', api_method: 'GET', api_path: '/users' }),
    res('a2', 'API', 'ROLE_MANAGE', { parent_id: 'p2', api_method: 'GET', api_path: '/roles' }),
  ]
  return {
    menus,
    pages,
    buttons,
    apis,
    // 菜单 → 页面来自后端 `menu_pages`：用户菜单挂的是 `user-page`（编码完全
    // 不同名），角色菜单挂 `role-page`；`orphan-page` 不挂任何菜单。
    menuPages: { m2: ['p1'], m3: ['p2'] },
    ...overrides,
  }
}

function select(partial: Partial<GrantSelection>): GrantSelection {
  return { ...emptySelection(), ...partial }
}

function rowKeys(rows: { key: string }[]): string[] {
  return rows.map((row) => row.key)
}

describe('buildPermissionTree — 层级来自后端关系', () => {
  it('菜单挂载按 menu_pages，而不是按资源编码的命名规律', () => {
    const tree = buildPermissionTree(input())
    const systemMenu = tree.find((node) => node.kind === 'MENU' && node.id === 'm1')
    const userMenu = systemMenu?.children.find((node) => node.id === 'm2')

    expect(userMenu?.children.map((node) => node.id)).toEqual(['p1'])
  })

  it('未挂载菜单的页面仍然出现，单独成组', () => {
    const rows = flattenTree(buildPermissionTree(input()), emptySelection(), new Set())
    const group = rows.find((row) => row.node.name === '未挂载菜单的页面')

    expect(group).toBeDefined()
    expect(rows.map((row) => row.node.id)).toContain('p3')
  })

  it('页面下挂它自己的按钮与接口，接口带方法+路径', () => {
    const rows = flattenTree(buildPermissionTree(input()), emptySelection(), new Set())
    const apiRow = rows.find((row) => row.node.id === 'a1')

    expect(apiRow?.node.meta).toBe('GET /users')
    expect(rows.map((row) => row.node.id)).toEqual(expect.arrayContaining(['b1', 'b2', 'a1']))
  })

  it('父菜单不在清单里时，子菜单不会被丢掉', () => {
    const data = input()
    const tree = buildPermissionTree({
      ...data,
      menus: data.menus.filter((menu) => menu.id !== 'm1'),
    })
    const group = tree.find((node) => node.name === '未归入上级菜单的菜单')

    expect(group).toBeDefined()
    expect(group?.children.map((node) => node.id)).toEqual(expect.arrayContaining(['m2', 'm3']))
  })

  it('菜单数据成环时递归终止且每个菜单只出现一次', () => {
    const cyclic = [
      res('m1', 'MENU', 'menu-a', { parent_id: 'm2' }),
      res('m2', 'MENU', 'menu-b', { parent_id: 'm1' }),
    ]
    const rows = flattenTree(
      buildPermissionTree({ menus: cyclic, pages: [], buttons: [], apis: [], menuPages: {} }),
      emptySelection(),
      new Set(),
    )
    const ids = rows.map((row) => row.node.id)

    expect(ids.filter((id) => id === 'm1')).toHaveLength(1)
    expect(ids.filter((id) => id === 'm2')).toHaveLength(1)
  })

  it('折叠的节点不渲染其子树', () => {
    const tree = buildPermissionTree(input())
    const collapsed = new Set([grantKey('MENU', 'm1')])
    const rows = flattenTree(tree, emptySelection(), collapsed)

    expect(rows.map((row) => row.node.id)).not.toContain('m2')
    expect(rows.map((row) => row.node.id)).toContain('m1')
  })
})

describe('异常分组 —— 「未挂载菜单的页面」不是普通分组', () => {
  /**
   * 这一组曾经让使用方直接发问"为什么会有 未挂载菜单的页面"：
   * 它长得像系统自带的分组，实际是**配置没配完**的信号。
   * 因此必须能被程序识别（`anomaly`）、必须自带解释（`meta`），
   * 且界面要能据此提示（`collectAnomalies`）。
   */

  it('没有菜单入口的页面分组被标记为 UNMOUNTED_PAGE', () => {
    const tree = buildPermissionTree(input())
    const group = tree.find((node) => node.name === ANOMALY_GROUP_NAME.UNMOUNTED_PAGE)

    expect(group?.anomaly).toBe('UNMOUNTED_PAGE')
    // 分组本身不带 kind/id —— 它不对应任何可授权资源（点不了、不参与级联）。
    expect(group?.kind).toBeNull()
    expect(group?.id).toBeNull()
    expect(group?.children.map((node) => node.id)).toEqual(['p3'])
    // 副标题是界面上唯一的解释来源，空串等于让用户对着分组名猜。
    expect(group?.meta).not.toBe('')
    expect(ANOMALY_HINT.UNMOUNTED_PAGE).not.toBe('')
  })

  it('上级菜单缺失的分组被标记为 ORPHAN_MENU', () => {
    const data = input()
    const tree = buildPermissionTree({
      ...data,
      menus: data.menus.filter((menu) => menu.id !== 'm1'),
    })
    const group = tree.find((node) => node.name === ANOMALY_GROUP_NAME.ORPHAN_MENU)

    expect(group?.anomaly).toBe('ORPHAN_MENU')
    expect(group?.children.map((node) => node.id)).toEqual(['m2', 'm3'])
    expect(group?.meta).not.toBe('')
    expect(ANOMALY_HINT.ORPHAN_MENU).not.toBe('')
  })

  it('正常菜单分组不带异常标记（否则提示条会一直亮着）', () => {
    const tree = buildPermissionTree(input())
    const menuNodes = tree.filter((node) => node.kind === 'MENU')

    expect(menuNodes.length).toBeGreaterThan(0)
    for (const node of menuNodes) expect(node.anomaly).toBeUndefined()
  })

  it('collectAnomalies 给出种类与受影响条数', () => {
    // 默认数据里 `m1` 在、`orphan-page` 没挂菜单 —— 只有一类异常。
    expect(collectAnomalies(buildPermissionTree(input()))).toEqual([
      { kind: 'UNMOUNTED_PAGE', count: 1 },
    ])

    // 再把父菜单拿掉，两类异常同时存在；顺序是"先孤儿菜单、后未挂载页面"
    // （`buildPermissionTree` 的 push 顺序），这里连顺序一起钉住 ——
    // 顺序变了提示条里的两句话就会对调，读起来会错位。
    const data = input()
    const both = collectAnomalies(
      buildPermissionTree({ ...data, menus: data.menus.filter((menu) => menu.id !== 'm1') }),
    )

    expect(both).toEqual([
      { kind: 'ORPHAN_MENU', count: 2 },
      { kind: 'UNMOUNTED_PAGE', count: 1 },
    ])
  })

  it('全部页面都挂上菜单时 collectAnomalies 返回空数组', () => {
    const data = input()
    // 把 `orphan-page` 也挂到一个菜单上 —— 这正是正常配置该有的样子。
    const tree = buildPermissionTree({ ...data, menuPages: { m2: ['p1', 'p3'], m3: ['p2'] } })

    expect(collectAnomalies(tree)).toEqual([])
  })
})

describe('applyCascade — 联动只发生在点击时', () => {
  it('点菜单把子菜单、页面、按钮、接口一起带上', () => {
    const tree = buildPermissionTree(input())
    const root = tree.find((node) => node.id === 'm1')
    if (root === undefined) throw new Error('缺少根菜单')

    const next = applyCascade(emptySelection(), root, true)

    // m1 的分支 = m1 + 子菜单 m2 / m3 + 各自挂载的页面 + 页面的按钮与接口。
    expect(new Set(next.MENU)).toEqual(new Set(['m1', 'm2', 'm3']))
    expect(next.PAGE).toEqual(['p1', 'p2'])
    expect(new Set(next.BUTTON)).toEqual(new Set(['b1', 'b2', 'b3']))
    expect(new Set(next.API)).toEqual(new Set(['a1', 'a2']))
    // 未挂载的页面不属于任何菜单分支，不应被带上。
    expect(next.PAGE).not.toContain('p3')
  })

  it('取消勾选把同一块整体移除，其他分支不动', () => {
    const tree = buildPermissionTree(input())
    const root = tree.find((node) => node.id === 'm1')
    if (root === undefined) throw new Error('缺少根菜单')

    const before = select({ PAGE: ['p1', 'p3'], MENU: ['m1', 'm2'], BUTTON: ['b1'], API: ['a1'] })
    const after = applyCascade(before, root, false)

    expect(after.MENU).toEqual([])
    expect(after.PAGE).toEqual(['p3'])
    expect(after.BUTTON).toEqual([])
    expect(after.API).toEqual([])
  })

  it('取消子项不会连带取消父项（这才是 DEPARTMENT_ADMIN 的真实形状）', () => {
    // 点页面会级联带上它的按钮与接口；再单独取消一个按钮，页面必须留在
    // 授权里。若父项状态由子项派生，这一取消会把页面一起吞掉 ——
    // 而"页面在、按钮不全"正是真实数据里最常见的形状。
    const tree = buildPermissionTree(input())
    const systemMenu = tree.find((node) => node.id === 'm1')
    const userMenu = systemMenu?.children.find((node) => node.id === 'm2')
    const page = userMenu?.children.find((node) => node.id === 'p1')
    const button = page?.children.find((node) => node.id === 'b2')
    if (page === undefined || button === undefined) throw new Error('缺少用户页面 / 按钮')

    const all = applyCascade(emptySelection(), page, true)
    expect(new Set(all.BUTTON)).toEqual(new Set(['b1', 'b2']))

    const next = applyCascade(all, button, false)

    expect(next.PAGE).toEqual(['p1'])
    expect(next.BUTTON).toEqual(['b1'])
    expect(next.API).toEqual(['a1'])
  })

  it('不改入参（返回新对象）', () => {
    const tree = buildPermissionTree(input())
    const root = tree.find((node) => node.id === 'm1')
    if (root === undefined) throw new Error('缺少根菜单')
    const before = emptySelection()

    applyCascade(before, root, true)

    expect(before.MENU).toEqual([])
  })

  it('分组节点自身不可授权，但级联会带上组内的资源', () => {
    const tree = buildPermissionTree(input())
    const group = tree.find((node) => node.name === '未挂载菜单的页面')
    if (group === undefined) throw new Error('缺少未挂载分组')

    expect(group.kind).toBeNull()
    expect(collectKeys(group).every((entry) => entry.kind !== null)).toBe(true)
    expect(applyCascade(emptySelection(), group, true).PAGE).toEqual(['p3'])
  })
})

describe('flattenTree — 混合态必须可见', () => {
  it('页面已授权而按钮未授权时，分支计数显示 1/4 而不是整块已授权', () => {
    const tree = buildPermissionTree(input())
    const rows = flattenTree(tree, select({ PAGE: ['p1'] }), new Set())
    const pageRow = rows.find((row) => row.node.id === 'p1')

    // p1 自身 + b1 + b2 + a1 = 4
    expect(pageRow?.totalCount).toBe(4)
    expect(pageRow?.grantedCount).toBe(1)
  })

  it('整块授权时计数相等', () => {
    const tree = buildPermissionTree(input())
    const rows = flattenTree(
      tree,
      select({ PAGE: ['p1'], BUTTON: ['b1', 'b2'], API: ['a1'] }),
      new Set(),
    )
    const pageRow = rows.find((row) => row.node.id === 'p1')

    expect(pageRow?.grantedCount).toBe(pageRow?.totalCount)
  })

  it('父菜单的计数涵盖子孙（含未挂载分组之外的全部）', () => {
    const tree = buildPermissionTree(input())
    const rows = flattenTree(tree, emptySelection(), new Set())
    const rootRow = rows.find((row) => row.node.id === 'm1')

    // m1 + m2 + p1 + b1 + b2 + a1 + m3 + p2 + b3 + a2 = 10
    expect(rootRow?.totalCount).toBe(10)
    // `orphan-page`（p3）挂在「未挂载菜单的页面」分组下，不属于 m1 分支。
    expect(rootRow?.node.children.flatMap((node) => node.id)).not.toContain('p3')
  })
})

describe('selectionToSet / keysOfTree', () => {
  it('计数涵盖四类且不含分组节点', () => {
    const tree = buildPermissionTree(input())

    expect(keysOfTree(tree)).toHaveLength(3 + 3 + 3 + 2)
    expect(selectionToSet(select({ MENU: ['m1'], BUTTON: ['b1'] }))).toEqual(
      new Set([grantKey('MENU', 'm1'), grantKey('BUTTON', 'b1')]),
    )
  })
})

describe('applyBulkSelection — 批量选择', () => {
  const empty = emptySelection()

  /** 树上全部资源（3 菜单 + 3 页面 + 3 按钮 + 2 接口 = 11）。 */
  function fullSelection(): GrantSelection {
    return select({
      MENU: ['m1', 'm2', 'm3'],
      PAGE: ['p1', 'p2', 'p3'],
      BUTTON: ['b1', 'b2', 'b3'],
      API: ['a1', 'a2'],
    })
  }

  it('全选：树上 11 项全部进授权集合', () => {
    const next = applyBulkSelection(empty, buildPermissionTree(input()), 'all')

    expect(new Set(next.PAGE)).toEqual(new Set(['p1', 'p2', 'p3']))
    expect(new Set(next.MENU)).toEqual(new Set(['m1', 'm2', 'm3']))
    expect(new Set(next.BUTTON)).toEqual(new Set(['b1', 'b2', 'b3']))
    expect(new Set(next.API)).toEqual(new Set(['a1', 'a2']))
  })

  it('取消全部：树上 11 项清空，但**清单之外**的既有授权原样保留', () => {
    // `b-out` 是一条没被取回的资源（清单分类取回且有上限）。
    // 它在树上根本看不见，所以"取消全部"不能顺手把它删掉 ——
    // 否则界面显示"全空"、保存后却还留着几条（`resolveSubmission` 会保留它），
    // 用户会以为保存失灵。
    const next = applyBulkSelection(
      select({ ...fullSelection(), BUTTON: ['b1', 'b2', 'b3', 'b-out'] }),
      buildPermissionTree(input()),
      'none',
    )

    expect(next.PAGE).toEqual([])
    expect(next.MENU).toEqual([])
    expect(next.API).toEqual([])
    expect(next.BUTTON).toEqual(['b-out'])
  })

  it('反选：逐项取反，而不是"取补集后连清单外的也一起翻"', () => {
    const next = applyBulkSelection(
      select({ PAGE: ['p1'], MENU: ['m1', 'm2'], BUTTON: ['b-out'] }),
      buildPermissionTree(input()),
      'invert',
    )

    // p1 已勾 → 取消；p2 / p3 未勾 → 勾上。
    expect(new Set(next.PAGE)).toEqual(new Set(['p2', 'p3']))
    // m1 / m2 → 取消，m3 → 勾上。
    expect(new Set(next.MENU)).toEqual(new Set(['m3']))
    // 树上三个按钮全部未勾 → 全部勾上；清单外的 b-out 不在树上，不受影响。
    expect(new Set(next.BUTTON)).toEqual(new Set(['b1', 'b2', 'b3', 'b-out']))
  })

  it('反选两次回到原状（幂等）', () => {
    const start = select({ PAGE: ['p1'], MENU: ['m2'], API: ['a1'] })
    const tree = buildPermissionTree(input())

    const once = applyBulkSelection(start, tree, 'invert')
    const twice = applyBulkSelection(once, tree, 'invert')

    expect(twice).toEqual(start)
  })

  it('空选择反选 = 全选（不是"什么都不做"）', () => {
    const next = applyBulkSelection(empty, buildPermissionTree(input()), 'invert')

    expect(next).toEqual(fullSelection())
  })

  it('树上没有该类别资源时，"取消全部"不得清空该类别', () => {
    // 候选清单里一个 API 都没有（接口被截断 / 该环境未定义）。
    // 此时 `none` 若把 API 整类清空，用户按"取消全部"就会顺手丢掉
    // 自己没看见、也没打算动的接口授权 —— 那是权限事故，不是"取消"。
    const tree = buildPermissionTree(input({ apis: [] }))
    const next = applyBulkSelection(select({ API: ['a-out'] }), tree, 'none')

    expect(next.API).toEqual(['a-out'])
  })

  it('不改入参（返回新对象）', () => {
    const start = select({ PAGE: ['p1'] })
    const next = applyBulkSelection(start, buildPermissionTree(input()), 'all')

    expect(start.PAGE).toEqual(['p1'])
    expect(next).not.toBe(start)
  })
})

describe('resolveSubmission — 清单之外的既有授权不得丢失', () => {
  it('清单外的授权原样保留，清单内的按勾选提交', () => {
    const universe = new Set(['b1', 'b2'])
    const submitted = resolveSubmission('BUTTON', select({ BUTTON: ['b1'] }), universe, ['b2', 'b-out'])

    expect(new Set(submitted)).toEqual(new Set(['b1', 'b-out']))
  })

  it('清单外的授权即便不在勾选里也不会被提交清空', () => {
    const submitted = resolveSubmission('BUTTON', select({ BUTTON: [] }), new Set(['b1']), ['b-out'])

    expect(submitted).toEqual(['b-out'])
  })

  it('清单内、未勾选的授权会被提交移除（这是"整体替换"该有的行为）', () => {
    const submitted = resolveSubmission('BUTTON', select({ BUTTON: [] }), new Set(['b1']), ['b1'])

    expect(submitted).toEqual([])
  })

  it('unavailableCount 只数清单之外的部分', () => {
    expect(unavailableCount(new Set(['b1']), ['b1', 'b-out'])).toBe(1)
    expect(unavailableCount(new Set(['b1', 'b2']), ['b1', 'b2'])).toBe(0)
  })

  it('universeOf 覆盖四类资源', () => {
    const universe = universeOf(input())

    expect(universe.PAGE.size).toBe(3)
    expect(universe.MENU.size).toBe(3)
    expect(universe.BUTTON.size).toBe(3)
    expect(universe.API.size).toBe(2)
  })
})

describe('flattenTree — 深度与顺序', () => {
  it('深度反映真实层级，子菜单排在挂载页面之前', () => {
    const rows = flattenTree(buildPermissionTree(input()), emptySelection(), new Set())
    const m1 = rows.find((row) => row.node.id === 'm1')
    const m2 = rows.find((row) => row.node.id === 'm2')
    const p1 = rows.find((row) => row.node.id === 'p1')
    const b1 = rows.find((row) => row.node.id === 'b1')

    expect(m1?.depth).toBe(0)
    expect(m2?.depth).toBe(1)
    expect(p1?.depth).toBe(2)
    expect(b1?.depth).toBe(3)
    expect(rowKeys(rows).indexOf(grantKey('MENU', 'm2'))).toBeLessThan(
      rowKeys(rows).indexOf(grantKey('PAGE', 'p1')),
    )
  })
})
