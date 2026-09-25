import { defineStore } from 'pinia'
import type { PublicDictItem } from '@/types'
import { getPublicDict } from '@/api/endpoints/dictionaries'

/**
 * dictionaryStore：业务页面的枚举统一从这里取（FE-07 §3）。
 *
 * 目的不是"缓存方便"，而是**单一事实来源** —— 同一个枚举在十个页面各写一份
 * 字面量，改动时必然漏掉其中几个，且没有任何一处会报错。
 *
 * 键是 `dict_code`。值只保留页面渲染需要的字段（不含 `id` 等管理字段）。
 */
type DictCache = Record<string, PublicDictItem[]>

export const useDictionaryStore = defineStore('dictionaries', {
  state: () => ({
    cache: {} as DictCache,
    inflight: new Map<string, Promise<PublicDictItem[]>>(),
  }),

  actions: {
    /** 取字典项；未缓存则拉取（同一 code 并发只发一个请求）。 */
    async ensure(dictCode: string): Promise<PublicDictItem[]> {
      const cached = this.cache[dictCode]
      if (cached !== undefined) return cached
      const pending = this.inflight.get(dictCode)
      if (pending !== undefined) return pending

      const task = getPublicDict(dictCode)
        .then((dict) => {
          this.cache[dictCode] = dict.items
          return dict.items
        })
        .finally(() => {
          this.inflight.delete(dictCode)
        })
      this.inflight.set(dictCode, task)
      return task
    },

    /** 下拉选项。`label` 缺省回落到 `item_value`，保证永不出现空选项。 */
    options(dictCode: string): Array<{ label: string; value: string }> {
      const items = this.cache[dictCode]
      if (items === undefined) return []
      return items.map((item) => ({
        label: item.item_label || item.item_value,
        value: item.item_value,
      }))
    },

    labelOf(dictCode: string, value: string): string {
      const items = this.cache[dictCode]
      if (items === undefined) return value
      return items.find((item) => item.item_value === value)?.item_label ?? value
    },

    reset(): void {
      this.cache = {}
      this.inflight.clear()
    },
  },
})
