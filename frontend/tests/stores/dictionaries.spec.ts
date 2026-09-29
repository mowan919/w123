import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDictionaryStore } from '@/stores/dictionaries'
import * as dictApi from '@/api/endpoints/dictionaries'
import { NetworkError } from '@/api/errors'
import type { PublicDictItem } from '@/types'

/**
 * dictionaryStore（FE-07 §3）。
 *
 * 关键不在"缓存对不对"，而在**取不到的时候页面该怎么办**：
 * 字典是运营可改的数据，它可能没配、可能被停用、也可能请求失败。
 * 这三种情况的正确表现都是"回落到本地文案"，而不是"页面空白"或
 * "直接显示 `ACTIVE` 这种裸枚举值" —— 后者正是字典要解决的问题本身。
 */

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
  listDictTypes: vi.fn(),
  createDictType: vi.fn(),
  updateDictType: vi.fn(),
  deleteDictType: vi.fn(),
  listDictItems: vi.fn(),
  createDictItem: vi.fn(),
  updateDictItem: vi.fn(),
  deleteDictItem: vi.fn(),
}))

const api = vi.mocked(dictApi)

function item(value: string, label: string): PublicDictItem {
  return {
    item_value: value,
    item_label: label,
    item_code: `${value.toLowerCase()}_code`,
    sort_order: 10,
    is_default: false,
    description: null,
  }
}

beforeEach(() => {
  useDictionaryStore().reset()
  api.getPublicDict.mockReset()
})

describe('labelOf', () => {
  it('命中字典时用字典的中文', async () => {
    api.getPublicDict.mockResolvedValue({
      dict_code: 'user_status',
      dict_name: '用户状态',
      description: null,
      items: [item('ACTIVE', '正常'), item('DISABLED', '停用')],
    })
    const store = useDictionaryStore()
    await store.ensure('user_status')

    expect(store.labelOf('user_status', 'ACTIVE')).toBe('正常')
  })

  it('字典还没到时用回落，而不是显示裸枚举值', () => {
    const store = useDictionaryStore()
    // 没请求过 → cache 里没有这一项。
    expect(store.labelOf('user_status', 'ACTIVE', '启用')).toBe('启用')
  })

  it('字典里有这一项才用字典，没有就用回落', async () => {
    api.getPublicDict.mockResolvedValue({
      dict_code: 'user_status',
      dict_name: '用户状态',
      description: null,
      items: [item('ACTIVE', '正常')],
    })
    const store = useDictionaryStore()
    await store.ensure('user_status')

    // 枚举新增了而字典还没补（运营还没录）—— 这时候显示裸值等于白做。
    expect(store.labelOf('user_status', 'LOCKED', '锁定')).toBe('锁定')
  })

  it('既没有字典项也没有回落时才显示原值（不说谎）', async () => {
    api.getPublicDict.mockResolvedValue({
      dict_code: 'user_status',
      dict_name: '用户状态',
      description: null,
      items: [item('ACTIVE', '正常')],
    })
    const store = useDictionaryStore()
    await store.ensure('user_status')

    expect(store.labelOf('user_status', 'LOCKED')).toBe('LOCKED')
  })
})

describe('optionsOr', () => {
  it('字典到了就用字典的选项', async () => {
    api.getPublicDict.mockResolvedValue({
      dict_code: 'audit_result',
      dict_name: '审计结果',
      description: null,
      items: [item('SUCCESS', '成功'), item('FAILURE', '失败')],
    })
    const store = useDictionaryStore()
    await store.ensure('audit_result')

    expect(store.optionsOr('audit_result', [{ label: '成功', value: 'SUCCESS' }])).toEqual([
      { label: '成功', value: 'SUCCESS' },
      { label: '失败', value: 'FAILURE' },
    ])
  })

  it('字典没到时用回落清单（筛选项不会因为一次请求失败而全空）', () => {
    const store = useDictionaryStore()
    const fallback = [{ label: '成功', value: 'SUCCESS' }]
    expect(store.optionsOr('audit_result', fallback)).toBe(fallback)
  })

  it('字典项是空数组时也回落 —— 空字典等于没配', async () => {
    api.getPublicDict.mockResolvedValue({
      dict_code: 'audit_result',
      dict_name: '审计结果',
      description: null,
      items: [],
    })
    const store = useDictionaryStore()
    await store.ensure('audit_result')

    const fallback = [{ label: '成功', value: 'SUCCESS' }]
    expect(store.optionsOr('audit_result', fallback)).toBe(fallback)
  })
})

describe('ensureMany', () => {
  it('一个字典失败不影响另一个（也不把页面拖挂）', async () => {
    api.getPublicDict.mockImplementation((code: string) => {
      if (code === 'broken') return Promise.reject(new NetworkError('网络请求失败', ''))
      return Promise.resolve({
        dict_code: code,
        dict_name: code,
        description: null,
        items: [item('X', '叉')],
      })
    })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const store = useDictionaryStore()

    await expect(store.ensureMany(['broken', 'ok'])).resolves.toBeUndefined()

    expect(store.labelOf('ok', 'X')).toBe('叉')
    // 失败必须留一条可观测的痕迹 —— 静默失败会让"字典没生效"变成玄学。
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })
})
