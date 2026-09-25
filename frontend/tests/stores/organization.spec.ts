import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useOrganizationStore } from '@/stores/organization'
import * as orgApi from '@/api/endpoints/organization'
import type { DepartmentTreeNode } from '@/types'

/**
 * organizationStore（`08 §4`）。
 *
 * 三条不可动摇的规则：
 *
 * 1. **缓存必须跨账号清掉** —— 部门树是数据范围的骨架。超管拿到的树比部门
 *    管理员宽，缓存一旦留到换账号之后，就是一次静默的越权信息泄露。清缓存
 *    的动作在 `router/index.ts` 的 `resetAllSessionState()`，这里只保证
 *    `reset()` 真的把东西清干净。
 * 2. **失败不留 `loaded = true`** —— 它与 permissionStore 的语义相反：
 *    那里置 `true` 是"别让路由守卫一直等"，这里保持 `false` 是因为没有任何
 *    人等这棵树，留着 false 才能让下一次导航重试，而不是让下拉框永远空着。
 * 3. **`create` / `update` / `disable` 必须重拉整棵树** —— 父节点下多出一颗
 *    子树、或某个分支被禁用，只改内存里的一层会立刻对不上。
 */

vi.mock('@/api/endpoints/organization', () => ({
  getDepartmentTree: vi.fn(),
  createDepartment: vi.fn(),
  updateDepartment: vi.fn(),
  disableDepartment: vi.fn(),
}))

const api = vi.mocked(orgApi)

function node(
  id: string,
  name: string,
  children: DepartmentTreeNode[] = [],
  parentId: string | null = null,
): DepartmentTreeNode {
  return {
    id,
    parent_id: parentId,
    department_code: `D-${id}`,
    department_name: name,
    status: 'ACTIVE',
    children,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getDepartmentTree.mockResolvedValue([])
})

describe('ensure：缓存与去重', () => {
  it('同一个会话里只发一次请求', async () => {
    const tree = [node('1', '总公司')]
    api.getDepartmentTree.mockResolvedValue(tree)

    const store = useOrganizationStore()
    await store.ensure()
    await store.ensure()
    await store.ensure()

    expect(api.getDepartmentTree).toHaveBeenCalledTimes(1)
    expect(store.tree).toEqual(tree)
    expect(store.loaded).toBe(true)
  })

  it('并发调用合并成一个请求', async () => {
    api.getDepartmentTree.mockResolvedValue([node('1', '总公司')])

    const store = useOrganizationStore()
    await Promise.all([store.ensure(), store.ensure()])

    expect(api.getDepartmentTree).toHaveBeenCalledTimes(1)
  })

  it('加载失败不留 loaded=true，下次导航会重试', async () => {
    api.getDepartmentTree.mockRejectedValueOnce(new Error('boom'))

    const store = useOrganizationStore()
    // `ensure()` 不向上抛：调用方都是 `void ensure()` / `await ensure()`，
    // 抛出去会变成未捕获的拒绝。失败由 `store.error` 表达，模板直接渲染。
    await store.ensure()

    expect(store.loaded).toBe(false)
    expect(store.error).toBe('boom')
    expect(store.tree).toEqual([])
    // inflight 已经放开，下一次导航会真的重试。
    expect(store.inflight).toBeNull()

    api.getDepartmentTree.mockResolvedValue([node('2', '总公司')])
    await store.ensure()
    expect(api.getDepartmentTree).toHaveBeenCalledTimes(2)
    expect(store.loaded).toBe(true)
  })

  it('reload 无视缓存，强制重拉', async () => {
    api.getDepartmentTree.mockResolvedValue([node('1', '总公司')])

    const store = useOrganizationStore()
    await store.ensure()
    await store.reload()

    expect(api.getDepartmentTree).toHaveBeenCalledTimes(2)
  })
})

describe('派生视图', () => {
  it('flat 带层级深度', () => {
    const store = useOrganizationStore()
    store.tree = [node('1', '总公司', [node('2', '华东区', [node('3', '上海分公司')], '1')])]

    expect(store.flat).toEqual([
      { id: '1', name: '总公司', depth: 0 },
      { id: '2', name: '华东区', depth: 1 },
      { id: '3', name: '上海分公司', depth: 2 },
    ])
  })

  it('options 的标签是完整继承路径（同名部门靠路径区分）', () => {
    const store = useOrganizationStore()
    store.tree = [
      node('1', '总公司', [
        node('2', '华东区'),
        node('3', '华南区', [node('4', '华东区')]),
      ]),
    ]

    expect(store.options.map((option) => option.label)).toEqual([
      '总公司',
      '总公司 / 华东区',
      '总公司 / 华南区',
      '总公司 / 华南区 / 华东区',
    ])
  })

  it('byId 能按 id 反查任意层级的节点', () => {
    const store = useOrganizationStore()
    store.tree = [node('1', '总公司', [node('2', '华东区', [], '1')])]

    expect(store.byId.get('2')?.department_name).toBe('华东区')
    expect(store.byId.size).toBe(2)
  })
})

describe('写操作后的缓存失效', () => {
  it('create 成功即重拉树', async () => {
    const tree = [node('1', '总公司')]
    api.createDepartment.mockResolvedValue(undefined)
    api.getDepartmentTree.mockResolvedValue(tree)

    const store = useOrganizationStore()
    await store.create({ department_code: 'D9', department_name: '新部门' })

    expect(api.createDepartment).toHaveBeenCalledWith({
      department_code: 'D9',
      department_name: '新部门',
    })
    expect(store.tree).toEqual(tree)
  })

  it('update 把改动原样带上（endpoint 层再剔除 undefined）', async () => {
    api.updateDepartment.mockResolvedValue(undefined)
    api.getDepartmentTree.mockResolvedValue([])

    const store = useOrganizationStore()
    await store.update('1', { department_name: '改名' })

    expect(api.updateDepartment).toHaveBeenCalledWith('1', { department_name: '改名' })
  })

  it('disable 之后树被重拉', async () => {
    api.disableDepartment.mockResolvedValue(undefined)
    const after = [node('1', '总公司')]
    api.getDepartmentTree.mockResolvedValue(after)

    const store = useOrganizationStore()
    await store.disable('1')

    expect(api.disableDepartment).toHaveBeenCalledWith('1')
    expect(store.tree).toEqual(after)
  })
})

describe('reset', () => {
  it('把树、加载态与失败信息一起清掉', async () => {
    api.getDepartmentTree.mockResolvedValue([node('1', '总公司')])
    const store = useOrganizationStore()
    await store.ensure()

    store.reset()

    expect(store.tree).toEqual([])
    expect(store.loaded).toBe(false)
    expect(store.error).toBeNull()
    // inflight 必须一起清，否则残留的 promise 会在下次 ensure 时被直接复用。
    expect(store.inflight).toBeNull()
  })
})
