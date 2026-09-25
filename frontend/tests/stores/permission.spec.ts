import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePermissionStore } from '@/stores/permission'
import type { MenuNode } from '@/stores/permission'
import * as permissionApi from '@/api/endpoints/permissions'
import { buildContract, pageIdOf } from '../helpers/fixtures'

/**
 * permissionStore（FE-03 / FE-05 / FE-12 §2）。
 *
 * 两条不该被"顺手优化掉"的规则：
 *
 * 1. **`load()` 失败也要置 `loaded = true`** —— 它的目的是**停止等待**，
 *    不是假装成功。少了这一句，路由守卫会一直等契约、页面白屏；
 *    多了这一句，用户看到的是 403（而不是转圈）。
 * 2. **`department_ids` 的 `null` 与 `[]` 语义相反** —— `null` 是部门维度不
 *    限制，`[]` 是全拒。把它们互相顶替等于在契约层 fail-open。
 */

vi.mock('@/api/endpoints/permissions', () => ({
  getPermissionContract: vi.fn(),
  listPermissionResources: vi.fn(),
  createPermissionResource: vi.fn(),
  updatePermissionResource: vi.fn(),
  deletePermissionResource: vi.fn(),
}))

const api = vi.mocked(permissionApi)

/** 造一条菜单；`pageIds` 给 `['1000']` 即"关联用户管理页面"，便于断言路径可解。 */
function menu(id: string, code: string, parentId: string | null, pageIds: string[] = []) {
  return { id, code, name: code, icon: null, parent_id: parentId, sort_order: 10, page_ids: pageIds }
}

describe('apply：契约落库', () => {
  it('把七段拆成各类编码集合', () => {
    const store = usePermissionStore()
    store.apply(buildContract({ permissionVersion: 7 }))

    expect(store.isLoaded).toBe(true)
    expect(store.version).toBe(7)
    expect(store.userId).toBe('7001')
    expect(store.hasPagePermission('system:user:page')).toBe(true)
    expect(store.hasMenuPermission('system:system')).toBe(true)
    expect(store.hasButtonPermission('user:create')).toBe(true)
    expect(store.hasApiPermission('api:user:list')).toBe(true)
    expect(store.isSuperAdmin).toBe(false)
  })

  it('字段权限按 `field_key` 建索引，不按资源 id', () => {
    const store = usePermissionStore()
    store.apply(buildContract())

    expect(store.getFieldPermission('user.email')).toBe('EDITABLE')
    expect(store.getFieldPermission('user.phone')).toBe('READ_ONLY')
    expect(store.getFieldPermission('user.remark')).toBe('VISIBLE')
    // 契约里没出现的键：默认 HIDDEN —— 未知键不该默认可见。
    expect(store.getFieldPermission('user.secret')).toBe('HIDDEN')
  })

  it('记录持有的角色（含后端展开的继承角色）', () => {
    const store = usePermissionStore()
    store.apply(buildContract({ directRoleIds: ['9001'], inheritedRoleIds: ['9002'] }))

    expect(store.holdsAnyRole(['9002'])).toBe(true)
    expect(store.holdsAnyRole(['9001'])).toBe(true)
    expect(store.holdsAnyRole(['9999'])).toBe(false)
  })

  it('data_scope 的 null 与 [] 必须保持各自的语义', () => {
    const unrestricted = usePermissionStore()
    unrestricted.apply(buildContract({ dataScopePolicy: 'ALL', dataScopeDepartmentIds: null }))
    expect(unrestricted.dataScopePolicy).toBe('ALL')
    expect(unrestricted.dataScopeDepartmentIds).toBeNull()

    const empty = usePermissionStore()
    empty.apply(buildContract({ dataScopePolicy: 'CUSTOM', dataScopeDepartmentIds: [] }))
    expect(empty.dataScopePolicy).toBe('CUSTOM')
    // 关键：[] 不能被当成 null 顶掉，否则"全拒"会退化成"不限制"。
    expect(empty.dataScopeDepartmentIds).toEqual([])
    expect(empty.dataScopeDepartmentIds).not.toBeNull()
  })

  it('toContract 能原样还原数据范围三态', () => {
    const store = usePermissionStore()
    store.apply(buildContract({ dataScopePolicy: 'CUSTOM', dataScopeDepartmentIds: ['500'] }))

    const contract = store.toContract()
    expect(contract.data_scope).toEqual({
      policy: 'CUSTOM',
      department_ids: ['500'],
      include_self: true,
    })
    expect(contract.direct_role_ids).toEqual(['9001'])
  })
})

describe('menuTree', () => {
  it('按 parent_id 挂成树并按 sort_order 排序', () => {
    const store = usePermissionStore()
    store.apply(buildContract())

    const tree = store.menuTree
    expect(tree).toHaveLength(1)
    const root = tree[0]
    expect(root?.code).toBe('system:system')
    // 子菜单按 sort_order 升序：role(10) 排在 user(20) 前面。
    expect(root?.children.map((child) => child.code)).toEqual(['system:role', 'system:user'])
  })

  it('菜单的目标路径来自关联页面的 route_path', () => {
    const store = usePermissionStore()
    store.apply(buildContract())

    const roles = store.menuTree[0]?.children.find((child) => child.code === 'system:role')
    // 菜单自身没有路径，只有 page_ids；路径要由页面解出来。
    expect(roles?.path).toBe('/system/roles')
  })

  it('未关联任何页面的菜单落不到路径上（前端不猜）', () => {
    const store = usePermissionStore()
    store.apply(buildContract())

    const root = store.menuTree[0]
    expect(root?.path).toBe('')
  })

  // 「菜单里有、点进去没反应」这类问题的根源都在这一组不变式上：
  // 无论后端给的父子关系多离谱，**每个菜单都必须恰好出现一次**。
  function flatten(nodes: MenuNode[]): string[] {
    return nodes.flatMap((node) => [node.code, ...flatten(node.children)])
  }

  it('父菜单指向已删除的节点时不丢菜单（缺父即当根，子菜单仍挂在它下面）', () => {
    const store = usePermissionStore()
    store.apply(
      buildContract({
        menus: [
          {
            id: '5001',
            code: 'system:system',
            name: '系统管理',
            icon: null,
            parent_id: '0000',
            sort_order: 10,
            page_ids: [],
          },
          {
            id: '5002',
            code: 'system:user',
            name: '用户管理',
            icon: null,
            parent_id: '5001',
            sort_order: 20,
            page_ids: [pageIdOf('system:user:page')],
          },
        ],
      }),
    )

    const tree = store.menuTree
    expect(flatten(tree).sort()).toEqual(['system:system', 'system:user'])
    // 缺父的那个自己当根，它的子菜单仍挂在它下面（不是跟着一起升为根）。
    expect(tree).toHaveLength(1)
    expect(tree[0]?.code).toBe('system:system')
    // 路径照样解得出来 —— 挂在哪一层不影响菜单能不能点进去。
    const user = tree[0]?.children.find((child) => child.code === 'system:user')
    expect(user?.path).toBe('/system/users')
  })

  it('父链成环时断开成根，菜单不会丢也不会让树无限递归', () => {
    const store = usePermissionStore()
    // 两条互相指父的脏数据（ Grant 手误配一次就能造出来）。
    store.apply(
      buildContract({
        menus: [
          menu('6001', 'system:a', '6002', ['1000']),
          menu('6002', 'system:b', '6001', ['1000']),
        ],
      }),
    )

    // 能返回就说明没无限递归；关键是每条恰好出现一次。
    expect(flatten(store.menuTree).sort()).toEqual(['system:a', 'system:b'])
  })

  it('自己指向自己的菜单不产生自引用子节点', () => {
    const store = usePermissionStore()
    store.apply(buildContract({ menus: [menu('6001', 'system:a', '6001', ['1000'])] }))

    const tree = store.menuTree
    expect(flatten(tree)).toEqual(['system:a'])
  })
})

describe('load', () => {
  beforeEach(() => {
    api.getPermissionContract.mockReset()
  })

  it('拉取并应用契约', async () => {
    api.getPermissionContract.mockResolvedValue(buildContract())

    const store = usePermissionStore()
    await store.load()

    expect(store.isLoaded).toBe(true)
    expect(store.hasPagePermission('system:user:page')).toBe(true)
    expect(store.loading).toBe(false)
  })

  it('已加载且非强制时不重复请求', async () => {
    api.getPermissionContract.mockResolvedValue(buildContract())

    const store = usePermissionStore()
    await store.load()
    await store.load()

    expect(api.getPermissionContract).toHaveBeenCalledTimes(1)
  })

  it('强制刷新时一定重新请求（FE-03 §5）', async () => {
    api.getPermissionContract.mockResolvedValue(buildContract())

    const store = usePermissionStore()
    await store.load()
    await store.refresh()

    expect(api.getPermissionContract).toHaveBeenCalledTimes(2)
  })

  it('加载失败也要停止等待：loaded 置真，页面落到 403 而不是白屏', async () => {
    api.getPermissionContract.mockRejectedValue(new Error('网络请求失败'))

    const store = usePermissionStore()
    await expect(store.load()).rejects.toThrow('网络请求失败')

    // 这一行的目的不是"假装权限已就绪"，而是让守卫停止等待。
    expect(store.isLoaded).toBe(true)
    expect(store.error).toBe('网络请求失败')
    expect(store.hasPagePermission('system:user:page')).toBe(false)
  })

  it('加载失败后集合为空，所有受保护页面都判无权限', async () => {
    api.getPermissionContract.mockRejectedValue(new Error('boom'))

    const store = usePermissionStore()
    await expect(store.load()).rejects.toThrow()
    expect(store.hasPagePermission('system:user:page')).toBe(false)
    expect(store.hasButtonPermission('user:create')).toBe(false)
    expect(store.getFieldPermission('user.email')).toBe('HIDDEN')
  })
})

describe('reset', () => {
  it('清空全部权限状态并回到未加载', () => {
    const store = usePermissionStore()
    store.apply(buildContract())
    store.reset()

    expect(store.isLoaded).toBe(false)
    expect(store.version).toBe(0)
    expect(store.hasPagePermission('system:user:page')).toBe(false)
    expect(store.getFieldPermission('user.email')).toBe('HIDDEN')
    expect(store.dataScopePolicy).toBeNull()
    expect(store.pages).toEqual([])
    expect(store.menus).toEqual([])
  })

  it('reset 之后再 load 会真的重新请求', async () => {
    api.getPermissionContract.mockResolvedValue(buildContract())

    const store = usePermissionStore()
    await store.load()
    store.reset()
    await store.load()

    expect(api.getPermissionContract).toHaveBeenCalledTimes(2)
  })
})
