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

    /**
     * 一次拉取多个字典（页面通常要用 2~3 个）。
     *
     * 失败**吞掉**而不是向上抛：字典缺席的正确表现是"页面退回硬编码文案"，
     * 不是"页面打不开"。逐个 `await` 会让第一个失败拖住后面的 ——
     * 用 `allSettled` 让"其中一个字典没配"不影响其它字典生效。
     */
    async ensureMany(dictCodes: string[]): Promise<void> {
      const results = await Promise.allSettled(dictCodes.map((code) => this.ensure(code)))
      for (const result of results) {
        if (result.status === 'rejected') {
          // 留一条可观测的痕迹：静默失败会让"字典没生效"变成玄学问题。
          console.warn('[dictionaries] 字典加载失败', result.reason)
        }
      }
    },

    /** 下拉选项。`label` 缺省回落到 `item_value`，保证永不出现空选项。 */
    options(dictCode: string): Array<{ label: string; value: string }> {
      return this.optionsOr(dictCode, [])
    },

    /**
     * 带**本地回落**的选项。
     *
     * 字典还没到（首屏）或被停用（运营改了字典）时用 `fallback` ——
     * 少了回落，"字典服务抖一下"就表现为"筛选框里一个选项都没有"。
     */
    optionsOr(
      dictCode: string,
      fallback: Array<{ label: string; value: string }>,
    ): Array<{ label: string; value: string }> {
      const items = this.cache[dictCode]
      if (items === undefined || items.length === 0) return fallback
      return items.map((item) => ({
        label: item.item_label || item.item_value,
        value: item.item_value,
      }))
    },

    /**
     * 把原始值翻成中文标签。
     *
     * `fallback` 是**不说谎**的底线：字典没到、或者字典里根本没这一项
     * （枚举新增了而字典还没补）时，显示它；查不到又不给回落就会显示
     * 裸枚举值 `ACTIVE`，那正是字典要解决的问题。
     */
    labelOf(dictCode: string, value: string, fallback?: string): string {
      const items = this.cache[dictCode]
      if (items === undefined) return fallback ?? value
      const hit = items.find((item) => item.item_value === value)
      return hit?.item_label || fallback || value
    },

    reset(): void {
      this.cache = {}
      this.inflight.clear()
    },
  },
})
