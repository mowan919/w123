import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useParamsStore } from '@/stores/params'
import * as paramsApi from '@/api/endpoints/params'
import type { SystemParam } from '@/types'

/**
 * paramsStore（`08 §9`）。
 *
 * 两条不该被"顺手加功能"破坏的规则：
 *
 * 1. **这里没有历史视图，也不该有。** 审计是 append-only、保留 2 年的，
 *    而审计不记录参数值（参数可能承载密钥类配置）。页面上一出现"看变更
 *    历史"，就是一条不可撤回的泄漏通道。
 * 2. **`clear_value` 与 `param_value` 互斥**：清空当前值是**独立动作**，
 *    不是"把值改成空串"。同时给出两者后端会拒绝。
 */

vi.mock('@/api/endpoints/params', () => ({
  listSystemParams: vi.fn(),
  createSystemParam: vi.fn(),
  updateSystemParam: vi.fn(),
  deleteSystemParam: vi.fn(),
}))

const api = vi.mocked(paramsApi)

function param(id: string, key: string): SystemParam {
  return {
    id,
    param_key: key,
    param_name: `${key} 名称`,
    param_type: 'STRING',
    param_value: 'v1',
    default_value: 'd1',
    effective_value: 'v1',
    description: null,
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

/** 回显请求参数，便于断言空串被转成 null。 */
function page(list: SystemParam[]): void {
  api.listSystemParams.mockImplementation(async (query) => ({
    list,
    total: list.length,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listSystemParams.mockResolvedValue({ list: [], total: 0, pageNum: 1, pageSize: 20 })
})

describe('分页与筛选', () => {
  it('空串关键字与状态转成 null 发给后端', async () => {
    page([param('1', 'MFA_REQUIRED_DEFAULT')])

    const store = useParamsStore()
    await store.goToPage(2, 50)

    expect(api.listSystemParams).toHaveBeenCalledWith({
      pageNum: 2,
      pageSize: 50,
      keyword: null,
      status: null,
    })
    expect(store.rows).toHaveLength(1)
  })

  it('setFilters 回到第 1 页', async () => {
    page([])

    const store = useParamsStore()
    await store.goToPage(4, 20)
    await store.setFilters({ keyword: 'MFA', status: 'ACTIVE' })

    expect(store.pageNum).toBe(1)
    expect(api.listSystemParams).toHaveBeenLastCalledWith({
      pageNum: 1,
      pageSize: 20,
      keyword: 'MFA',
      status: 'ACTIVE',
    })
  })

  it('失败时清空 rows 并留下错误文案', async () => {
    const store = useParamsStore()
    store.rows = [param('1', 'x')]
    api.listSystemParams.mockRejectedValueOnce(new Error('boom'))

    await store.load()

    expect(store.error).toBe('boom')
    expect(store.rows).toEqual([])
  })
})

describe('写操作都会重拉列表', () => {
  it('create 之后列表跟着更新', async () => {
    page([param('1', 'KEY')])
    api.createSystemParam.mockResolvedValue(param('1', 'KEY'))

    const store = useParamsStore()
    await store.create({
      param_key: 'KEY',
      param_name: '键',
      param_type: 'STRING',
      default_value: '',
      param_value: null,
      description: null,
      status: 'ACTIVE',
    })

    expect(api.createSystemParam).toHaveBeenCalledTimes(1)
    expect(store.rows).toHaveLength(1)
  })

  it('update 之后列表跟着更新', async () => {
    page([param('1', 'KEY')])
    api.updateSystemParam.mockResolvedValue(param('1', 'KEY'))

    const store = useParamsStore()
    await store.update('1', { param_name: '新名', clear_value: false })

    expect(api.updateSystemParam).toHaveBeenCalledWith('1', {
      param_name: '新名',
      clear_value: false,
    })
    expect(store.rows).toHaveLength(1)
  })

  it('clearValue 提交 `clear_value: true` 且**不夹带** param_value', async () => {
    page([param('1', 'KEY')])
    api.updateSystemParam.mockResolvedValue({ ...param('1', 'KEY'), param_value: null })

    const store = useParamsStore()
    const updated = await store.clearValue('1', {
      param_name: '键',
      description: null,
      status: 'ACTIVE',
    })

    const [sentId, sentBody] = api.updateSystemParam.mock.calls[0] ?? []
    expect(sentId).toBe('1')
    // `param_value` 出现在这里就意味着"清空"退化成了"写入空串"，
    // 而后端对两者是不同处理（后者会被当成显式清空）。
    expect(sentBody).not.toHaveProperty('param_value')
    expect(sentBody?.clear_value).toBe(true)
    expect(updated.param_value).toBeNull()
  })

  it('remove 之后列表跟着更新', async () => {
    page([])
    api.deleteSystemParam.mockResolvedValue(undefined)

    const store = useParamsStore()
    store.rows = [param('1', 'KEY')]

    await store.remove('1')

    expect(api.deleteSystemParam).toHaveBeenCalledWith('1')
    expect(store.rows).toEqual([])
  })

  it('写操作失败不该清空已加载的列表', async () => {
    page([param('1', 'KEY')])
    api.deleteSystemParam.mockRejectedValueOnce(new Error('boom'))

    const store = useParamsStore()
    await store.load()
    await expect(store.remove('1')).rejects.toThrow('boom')

    expect(store.rows).toHaveLength(1)
  })
})

describe('reset', () => {
  it('清掉分页状态与筛选条件', async () => {
    page([])
    const store = useParamsStore()
    await store.goToPage(3, 50)
    await store.setFilters({ keyword: 'MFA', status: 'DISABLED' })

    store.reset()

    expect(store.rows).toEqual([])
    expect(store.total).toBe(0)
    expect(store.pageNum).toBe(1)
    expect(store.pageSize).toBe(20)
    expect(store.keyword).toBe('')
    expect(store.statusFilter).toBe('')
    expect(store.error).toBeNull()
  })
})
