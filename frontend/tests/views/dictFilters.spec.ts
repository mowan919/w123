import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 数据字典页的筛选面与字典项子表。
 *
 * 两条都是**静默错**：
 * 1. 状态筛选默认 `null`，select 里没有哪个 option 与 null 匹配 →
 *    下拉显示**空白**而不是「全部」；且「全部」（空串）若原样发出，
 *    后端 enum 校验直接 422 —— 用户点查询就报 validation error。
 *    口径与其余列表页一致：空串 = 全部 = 请求里**不带** status。
 * 2. 字典项子表：后端把列表包在 `items` 键里，前端曾把整个 data
 *    当数组渲染 → 面板里只有一行全是"—"的怪数据
 *    （"只有字典，没有资源类型"）。
 */

vi.mock('@/api/endpoints/dictionaries', () => ({
  listDictTypes: vi.fn(),
  createDictType: vi.fn(),
  updateDictType: vi.fn(),
  deleteDictType: vi.fn(),
  listDictItems: vi.fn(),
  createDictItem: vi.fn(),
  updateDictItem: vi.fn(),
  deleteDictItem: vi.fn(),
}))

import * as dictApi from '@/api/endpoints/dictionaries'
import DictionaryListView from '@/views/system/DictionaryListView.vue'
import { usePermissionStore } from '@/stores/permission'

const dicts = vi.mocked(dictApi)

function lastTypeQuery(): Record<string, unknown> | undefined {
  const call = dicts.listDictTypes.mock.calls.at(-1)
  return call === undefined ? undefined : (call[0] as unknown as Record<string, unknown>)
}

const A_TYPE = {
  id: '9001',
  dict_code: 'resource_type',
  dict_name: '资源类型',
  description: '权限资源的五分类',
  status: 'ACTIVE' as const,
  created_at: '2026-09-28T16:47:27Z',
  updated_at: '2026-09-28T16:47:27Z',
}

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(DictionaryListView)
  await flushPromises()
  await flushPromises()
  return wrapper
}

async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((node) => node.text().includes(text))
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  await button.trigger('click')
  await flushPromises()
  await flushPromises()
}

/** 筛选区的状态下拉（页面里第一个 select）。 */
function statusSelect(wrapper: VueWrapper): HTMLSelectElement {
  const select = wrapper.find('select')
  if (!select.exists()) throw new Error('找不到状态下拉')
  return select.element as HTMLSelectElement
}

beforeEach(() => {
  vi.clearAllMocks()

  dicts.listDictTypes.mockImplementation(async (query) => ({
    list: [A_TYPE],
    total: 1,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  dicts.listDictItems.mockResolvedValue([])

  const permission = usePermissionStore()
  permission.reset()
  permission.fieldLevels = new Map()
})

describe('状态筛选 —— 默认就是「全部」', () => {
  it('进入页面时下拉显示「全部」，不是空白', async () => {
    const wrapper = await mountView()

    expect(statusSelect(wrapper).value).toBe('')
    expect(wrapper.find('select').element.selectedOptions[0]?.text).toBe('全部')
  })

  it('默认（全部）查询不带 status —— 原样发空串会被后端 enum 校验 422 拒掉', async () => {
    const wrapper = await mountView()
    dicts.listDictTypes.mockClear()

    await clickButton(wrapper, '查询')

    expect(dicts.listDictTypes).toHaveBeenCalledTimes(1)
    expect(lastTypeQuery()?.['status']).toBeNull()
  })

  it('选「启用」查询带 ACTIVE，选回「全部」又归 null', async () => {
    const wrapper = await mountView()

    await wrapper.find('select').setValue('ACTIVE')
    await clickButton(wrapper, '查询')
    expect(lastTypeQuery()?.['status']).toBe('ACTIVE')

    await wrapper.find('select').setValue('')
    await clickButton(wrapper, '查询')
    expect(lastTypeQuery()?.['status']).toBeNull()
  })

  it('重置回到「全部」并重新查询', async () => {
    const wrapper = await mountView()

    await wrapper.find('select').setValue('DISABLED')
    await clickButton(wrapper, '查询')
    expect(lastTypeQuery()?.['status']).toBe('DISABLED')

    await clickButton(wrapper, '重置')

    expect(statusSelect(wrapper).value).toBe('')
    expect(lastTypeQuery()?.['status']).toBeNull()
  })
})

describe('字典项子表 —— 渲染后端 items 键里的数组', () => {
  it('展开字典后逐行显示字典项，不再是一行怪数据', async () => {
    dicts.listDictItems.mockResolvedValue([
      {
        id: 'i1',
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
      },
      {
        id: 'i2',
        dict_type_id: '9001',
        item_label: '字段',
        item_value: 'FIELD',
        item_code: 'resource_type_field',
        sort_order: 50,
        status: 'ACTIVE',
        is_default: false,
        description: null,
        created_at: '2026-09-28T16:47:27Z',
        updated_at: '2026-09-28T16:47:27Z',
      },
    ])
    const wrapper = await mountView()

    await clickButton(wrapper, '展开字典项')

    expect(dicts.listDictItems).toHaveBeenCalledWith('9001')
    const body = wrapper.find('table.mini-table tbody')
    expect(body.exists()).toBe(true)
    const rows = body.findAll('tr')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.text()).toContain('页面')
    expect(rows[0]?.text()).toContain('PAGE')
    expect(rows[1]?.text()).toContain('字段')
    expect(wrapper.text()).not.toContain('该字典下还没有字典项')
  })

  it('展开后确实没有项时给出空态文案', async () => {
    const wrapper = await mountView()

    await clickButton(wrapper, '展开字典项')

    expect(dicts.listDictItems).toHaveBeenCalledWith('9001')
    expect(wrapper.text()).toContain('该字典下还没有字典项')
  })
})
