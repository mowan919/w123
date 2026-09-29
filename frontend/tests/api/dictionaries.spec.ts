import { beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '@/api/client'
import { listDictItems } from '@/api/endpoints/dictionaries'
import type { AuthBridge } from '@/api/client'
import { ok, stubFetch } from '../helpers/fetchMock'
import { makeTokenPair } from '../helpers/fixtures'

/**
 * 字典项列表的响应解包（`08 §9`）。
 *
 * ⚠️ 后端 `GET /admin/dicts/{id}/items` 把列表包在 `items` 键里
 * （`DictItemListResponse`），**不是**裸数组。前端曾直接把整个 data
 * 当数组用：`v-for` 去遍历对象，字典页「展开字典项」渲染出一行
 * 全是"—"的怪数据 —— 表现为"只有字典（类型），没有资源类型（项）"，
 * 而请求其实一直是 200。断言解包行为，别再让它回归。
 */

beforeEach(() => {
  const bridge: AuthBridge = {
    getAccessToken: () => 'access-1',
    getRefreshToken: () => 'refresh-1',
    refresh: async () => makeTokenPair(),
    onSessionLost: () => undefined,
  }
  configureClient({ baseUrl: '/api/v1/', bridge })
})

describe('listDictItems 解包后端的 items 包装', () => {
  it('返回 data.items 数组，而不是整个 data 对象', async () => {
    const item = {
      id: '1',
      dict_type_id: '9001',
      item_label: '页面',
      item_value: 'PAGE',
      item_code: 'resource_type_page',
      sort_order: 10,
      status: 'ACTIVE',
      is_default: true,
      description: null,
      created_at: '2026-09-28T16:47:27Z',
      updated_at: '2026-09-28T16:47:27Z',
    }
    stubFetch(async () => ok({ items: [item, { ...item, id: '2', item_value: 'MENU' }] }))

    const result = await listDictItems('9001')

    expect(Array.isArray(result)).toBe(true)
    expect(result).toHaveLength(2)
    expect(result.map((entry) => entry.item_value)).toEqual(['PAGE', 'MENU'])
  })

  it('请求打到 /admin/dicts/{id}/items，status 缺省时不拼参数', async () => {
    const fetchStub = stubFetch(async () => ok({ items: [] }))

    await listDictItems('9001')

    expect(fetchStub.calls).toHaveLength(1)
    expect(fetchStub.calls[0]?.url).toBe('/api/v1/admin/dicts/9001/items')
    expect(fetchStub.calls[0]?.init.method).toBe('GET')
  })

  it('带 status 时拼进查询串', async () => {
    const fetchStub = stubFetch(async () => ok({ items: [] }))

    await listDictItems('9001', 'ACTIVE')

    expect(fetchStub.calls[0]?.url).toBe('/api/v1/admin/dicts/9001/items?status=ACTIVE')
  })
})
