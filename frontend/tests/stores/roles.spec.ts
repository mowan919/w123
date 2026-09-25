import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRolesStore } from '@/stores/roles'
import * as rolesApi from '@/api/endpoints/roles'
import type { Role } from '@/types'

/**
 * rolesStore（`08 §7`）。
 *
 * 两条不该被"顺手合并"的规则：
 *
 * 1. **分页 `rows` 与选择器 `picker` 是两份数据，不能是一个数组**。
 *    角色管理页翻到第 3 页时，权限配置页的下拉框会跟着只剩第 3 页那几条；
 *    反过来，权限页"选中第一个角色"也会把用户刚筛出来的结果覆盖掉。
 * 2. **写操作必须连带失效 `picker`** —— 新建的角色在其他页面的下拉框里
 *    应当立刻出现。原来每个页面各写一遍 `await api.x(); await load()`，
 *    漏一次就是"新建的角色在别处还看不到"。
 */

vi.mock('@/api/endpoints/roles', () => ({
  listRoles: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
}))

const api = vi.mocked(rolesApi)

function role(id: string, name: string): Role {
  return {
    id,
    role_code: `R-${id}`,
    role_name: name,
    description: null,
    status: 'ACTIVE',
    data_scope: 'ALL',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

/**
 * 分页结果。默认给 3 条，够覆盖筛选与翻页。
 *
 * 回显**请求里的** `pageNum` / `pageSize`：写死成 1 的话，翻页参数既验不出来
 * 也观察不到，而"请求第 3 页、store 记住第 3 页"正是这条用例要看的东西。
 */
function page(list: Role[], total = list.length): Role[] {
  api.listRoles.mockImplementation(async (query) => ({
    list,
    total,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  return list
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listRoles.mockResolvedValue({ list: [], total: 0, pageNum: 1, pageSize: 20 })
})

describe('分页列表', () => {
  it('把接口的筛选转换掉：空串表示"不限"，发给后端的是 null', async () => {
    page([role('1', '超管')])

    const store = useRolesStore()
    await store.goToPage(2, 50)

    expect(api.listRoles).toHaveBeenCalledWith({
      pageNum: 2,
      pageSize: 50,
      keyword: null,
      status: null,
    })
    expect(store.rows).toHaveLength(1)
    expect(store.total).toBe(1)
  })

  it('setFilters 回到第 1 页（否则会停在一个不存在的页码上）', async () => {
    page([])
    const store = useRolesStore()
    await store.goToPage(3, 20)
    expect(store.pageNum).toBe(3)

    await store.setFilters({ keyword: 'admin' })

    expect(store.pageNum).toBe(1)
    expect(store.keyword).toBe('admin')
    expect(api.listRoles).toHaveBeenLastCalledWith({
      pageNum: 1,
      pageSize: 20,
      keyword: 'admin',
      status: null,
    })
  })

  it('失败时把 rows 清空并留下错误文案', async () => {
    const store = useRolesStore()
    store.rows = [role('1', 'x')]
    api.listRoles.mockRejectedValueOnce(new Error('boom'))

    await store.load()

    expect(store.error).toBe('boom')
    expect(store.rows).toEqual([])
  })
})

describe('选择器清单', () => {
  it('不分页，一次取满 PICKER_LIMIT 条', async () => {
    page([role('1', '超管'), role('2', '部门管理员')])

    const store = useRolesStore()
    await store.ensurePicker()

    expect(api.listRoles).toHaveBeenCalledWith({ pageNum: 1, pageSize: 100 })
    expect(store.picker).toHaveLength(2)
    expect(store.pickerLoaded).toBe(true)
  })

  it('已加载过就不再发请求，即使分页刚被刷新过', async () => {
    page([role('1', '超管')])

    const store = useRolesStore()
    await store.ensurePicker()
    await store.ensurePicker()
    await store.load()

    // 只有 ensurePicker 那一次是取清单，load 用的是分页参数。
    expect(api.listRoles).toHaveBeenCalledTimes(2)
    expect(store.picker).toHaveLength(1)
  })

  it('失败后 pickerLoaded 回到 false，下次进来重试', async () => {
    page([])
    const store = useRolesStore()
    api.listRoles.mockRejectedValueOnce(new Error('boom'))

    await store.ensurePicker()

    expect(store.pickerError).toBe('boom')
    expect(store.pickerLoaded).toBe(false)
    expect(store.picker).toEqual([])

    page([role('9', '补救')])
    await store.ensurePicker()
    expect(store.picker).toHaveLength(1)
  })

  it('取回数量正好等于上限时必须被标记为"可能没取全"', () => {
    const store = useRolesStore()
    // 只设 state，不触发请求：这条判据与请求无关。
    store.pickerLoaded = true
    store.picker = Array.from({ length: 100 }, (_, index) => role(String(index), `r${index}`))

    expect(store.pickerMightBeTruncated).toBe(true)

    store.picker = [role('1', '只有一个')]
    expect(store.pickerMightBeTruncated).toBe(false)
  })
})

describe('写操作连带失效缓存', () => {
  it('create 后清单被作废并重拉分页', async () => {
    page([role('1', '超管')])
    api.createRole.mockResolvedValue(role('2', '新角色'))

    const store = useRolesStore()
    await store.ensurePicker()
    expect(store.pickerLoaded).toBe(true)

    const created = await store.create({
      role_code: 'R-2',
      role_name: '新角色',
      description: '',
      status: 'ACTIVE',
    })

    expect(created.id).toBe('2')
    expect(store.pickerLoaded).toBe(false)
    // 作废之后，下一次 ensurePicker 会重新发请求。
    await store.ensurePicker()
    expect(api.listRoles).toHaveBeenCalledWith({ pageNum: 1, pageSize: 100 })
  })

  it('update 同样作废清单', async () => {
    page([role('1', '超管')])
    api.updateRole.mockResolvedValue(role('1', '改名'))

    const store = useRolesStore()
    await store.ensurePicker()
    await store.update('1', { role_name: '改名' })

    expect(store.pickerLoaded).toBe(false)
  })

  it('remove 之后分页跟着重拉', async () => {
    page([role('1', '超管')])
    api.deleteRole.mockResolvedValue(undefined)

    const store = useRolesStore()
    await store.remove('1')

    expect(api.deleteRole).toHaveBeenCalledWith('1')
    expect(store.rows).toHaveLength(1)
  })

  it('写操作失败时不清缓存（失败不是"数据变了"）', async () => {
    page([role('1', '超管')])
    api.createRole.mockRejectedValueOnce(new Error('boom'))

    const store = useRolesStore()
    await store.ensurePicker()
    await expect(
      store.create({ role_code: 'X', role_name: 'X', description: '', status: 'ACTIVE' }),
    ).rejects.toThrow('boom')

    expect(store.pickerLoaded).toBe(true)
  })
})

describe('reset', () => {
  it('清掉分页与清单两套状态', async () => {
    page([role('1', '超管')])
    const store = useRolesStore()
    await store.ensurePicker()
    await store.load()

    store.reset()

    expect(store.rows).toEqual([])
    expect(store.picker).toEqual([])
    expect(store.pickerLoaded).toBe(false)
    expect(store.pageNum).toBe(1)
    expect(store.keyword).toBe('')
    expect(store.status).toBe('')
  })
})
