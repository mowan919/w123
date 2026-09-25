import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useResourcesStore } from '@/stores/resources'
import * as resourcesApi from '@/api/endpoints/resources'
import type { PermissionResource, ResourceType } from '@/types'
import type { ResourceListQuery } from '@/api/endpoints/resources'

/**
 * resourcesStore（DD-20 / `08 §3`）。
 *
 * 三条不该被"顺手优化掉"的规则：
 *
 * 1. **清单来自 `/admin/permission-resources`，不是当前用户的权限契约**。
 *    被授权的角色可能持有当前管理员看不到的资源，拿契约当候选来源会静默
 *    丢掉它们（表现为"这个权限就是勾不上"）。
 * 2. **五类并行取，任何一类失败都不该让整份清单不可用** —— 否则授权页里
 *    "API 那一列空着"会被误读成"该类别还没有资源"。
 * 3. **写操作必须连带作废清单** —— 新增一个 BUTTON 资源之后，权限配置页的
 *    勾选框里得能马上勾上它。
 */

vi.mock('@/api/endpoints/resources', () => ({
  listResources: vi.fn(),
  createResource: vi.fn(),
  updateResource: vi.fn(),
  deleteResource: vi.fn(),
}))

const api = vi.mocked(resourcesApi)

function resource(id: string, type: ResourceType, code = `C-${id}`): PermissionResource {
  return {
    id,
    resource_type: type,
    resource_code: code,
    resource_name: `资源${id}`,
    parent_id: null,
    sort_order: 10,
    status: 'ACTIVE',
    route_path: null,
    component_path: null,
    icon: null,
    api_method: null,
    api_path: null,
    field_key: type === 'FIELD' ? code : null,
    owner_resource_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

/** 分页结果：回显请求参数，便于断言筛选被正确转换。 */
function page(list: PermissionResource[]): void {
  api.listResources.mockImplementation(async (query) => ({
    list,
    total: list.length,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
}

/**
 * 取出"取某类授权清单"的那一次调用。
 *
 * 不能用 `toHaveBeenCalledWith`：分组清单是五类并行发的，断言会命中其中的
 * 任意一次（上一次运行是 PAGE，下一次就可能变成 FIELD），而
 * `ensureGrantable` 只传 `pageNum / pageSize / resourceType` 三个键，
 * 和分页 `load()` 那五个键也不是同一个形状。
 */
function callOfKind(kind: ResourceType): ResourceListQuery | undefined {
  return api.listResources.mock.calls.find((call) => call[0]?.resourceType === kind)?.[0]
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listResources.mockResolvedValue({ list: [], total: 0, pageNum: 1, pageSize: 20 })
})

describe('分页列表', () => {
  it('空串关键字转成 null，类型 / 状态原样带过去', async () => {
    page([resource('1', 'PAGE')])

    const store = useResourcesStore()
    await store.goToPage(2, 50)

    expect(api.listResources).toHaveBeenCalledWith({
      pageNum: 2,
      pageSize: 50,
      resourceType: null,
      status: null,
      keyword: null,
    })
    expect(store.rows).toHaveLength(1)
  })

  it('setFilters 把类型与状态一起换成 null 表示"不限"', async () => {
    page([])

    const store = useResourcesStore()
    await store.setFilters({
      keyword: 'user',
      kind: 'BUTTON',
      status: 'DISABLED',
    })

    expect(api.listResources).toHaveBeenLastCalledWith({
      pageNum: 1,
      pageSize: 20,
      resourceType: 'BUTTON',
      status: 'DISABLED',
      keyword: 'user',
    })
    expect(store.pageNum).toBe(1)
  })
})

describe('授权候选清单', () => {
  it('按类型分组，五类各取一次', async () => {
    const kinds: ResourceType[] = ['PAGE', 'MENU', 'BUTTON', 'API', 'FIELD']
    kinds.forEach((kind, index) => {
      api.listResources.mockImplementationOnce(async () => ({
        list: [resource(`1${index}`, kind)],
        total: 1,
        pageNum: 1,
        pageSize: 100,
      }))
    })

    const store = useResourcesStore()
    await store.ensureGrantable()

    expect(store.grantable).not.toBeNull()
    expect(store.grantableLoaded).toBe(true)
    kinds.forEach((kind) => {
      expect(store.grantable?.[kind]).toHaveLength(1)
    })
    expect(store.grantable?.FIELD).toHaveLength(1)
    expect(callOfKind('FIELD')).toEqual({
      pageNum: 1,
      pageSize: 100,
      resourceType: 'FIELD',
    })
  })

  it('任何一类失败，整份清单为 null 而不是半套数据', async () => {
    api.listResources.mockImplementationOnce(async () => ({
      list: [resource('1', 'PAGE')],
      total: 1,
      pageNum: 1,
      pageSize: 100,
    }))
    api.listResources.mockRejectedValueOnce(new Error('boom'))

    const store = useResourcesStore()
    await store.ensureGrantable()

    // 半套清单更危险：授权页会把"API 那一列空着"读成"该类别还没有资源"。
    expect(store.grantable).toBeNull()
    expect(store.grantableLoaded).toBe(false)
    expect(store.grantableError).toBe('boom')
  })

  it('已加载过就不再发请求', async () => {
    const store = useResourcesStore()
    await store.ensureGrantable()
    const calls = api.listResources.mock.calls.length

    await store.ensureGrantable()

    expect(api.listResources.mock.calls.length).toBe(calls)
  })

  it('某一类取满上限时必须被标记为"可能没取全"', () => {
    const store = useResourcesStore()
    store.grantableLoaded = true
    store.grantable = {
      PAGE: [],
      MENU: [],
      BUTTON: Array.from({ length: 100 }, (_, index) => resource(String(index), 'BUTTON')),
      API: [],
      FIELD: [],
    }

    expect(store.grantableMightBeTruncated).toBe(true)

    store.grantable.BUTTON = [resource('1', 'BUTTON')]
    expect(store.grantableMightBeTruncated).toBe(false)
  })
})

describe('写操作连带失效清单', () => {
  it('create 之后清单作废，再取会重发请求', async () => {
    page([])
    api.createResource.mockResolvedValue(resource('99', 'BUTTON'))

    const store = useResourcesStore()
    await store.ensureGrantable()
    expect(store.grantableLoaded).toBe(true)

    await store.create({
      resource_type: 'BUTTON',
      resource_code: 'user:export',
      resource_name: '导出用户',
    })

    expect(store.grantableLoaded).toBe(false)

    api.listResources.mockImplementation(async () => ({
      list: [],
      total: 0,
      pageNum: 1,
      pageSize: 100,
    }))
    await store.ensureGrantable()
    expect(callOfKind('BUTTON')).toEqual({ pageNum: 1, pageSize: 100, resourceType: 'BUTTON' })
  })

  it('update 与 remove 同样作废清单', async () => {
    api.updateResource.mockResolvedValue(resource('1', 'PAGE'))
    api.deleteResource.mockResolvedValue(undefined)
    page([])

    const store = useResourcesStore()
    await store.ensureGrantable()

    await store.update('1', { resource_name: '改名' })
    expect(store.grantableLoaded).toBe(false)

    await store.ensureGrantable()
    await store.remove('1')
    expect(store.grantableLoaded).toBe(false)
  })
})

describe('reset', () => {
  it('清掉分页与清单两套状态', async () => {
    const store = useResourcesStore()
    await store.ensureGrantable()
    await store.load()

    store.reset()

    expect(store.rows).toEqual([])
    expect(store.grantable).toBeNull()
    expect(store.grantableLoaded).toBe(false)
    expect(store.kindFilter).toBeNull()
  })
})
