import { ref } from 'vue'
import type { PageResult } from '@/types'

/**
 * 分页编排（FE-09 §6）。
 *
 * 分页语义**只**存在于这里：请求 `pageNum` / `pageSize`，响应
 * `{ list, total, pageNum, pageSize }`。页面只提供筛选条件，不重新定义分页。
 */
export interface PageQuery {
  pageNum: number
  pageSize: number
  [key: string]: string | number | boolean | null | undefined
}

export function usePageQuery<T>(fetcher: (query: PageQuery) => Promise<PageResult<T>>) {
  const rows = ref<T[]>([])
  const total = ref(0)
  const pageNum = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let latestToken = 0

  /** 触发一次加载。`filters` 变化后先回到第 1 页。 */
  async function reload(filters: Record<string, string | number | null> = {}): Promise<void> {
    const token = latestToken + 1
    latestToken = token
    loading.value = true
    error.value = null
    try {
      const result = await fetcher({ pageNum: pageNum.value, pageSize: pageSize.value, ...filters })
      // 竞态保护：慢请求回来时页面可能已经翻页了，晚到的结果必须丢弃，
      // 否则会出现"翻到第 3 页却显示第 1 页的数据"。
      if (token !== latestToken) return
      rows.value = result.list
      total.value = result.total
      pageNum.value = result.pageNum
      pageSize.value = result.pageSize
    } catch (cause) {
      if (token !== latestToken) return
      error.value = cause instanceof Error ? cause.message : '加载失败'
      rows.value = []
      total.value = 0
    } finally {
      if (token === latestToken) loading.value = false
    }
  }

  function onPageChange(next: { pageNum: number; pageSize: number }): void {
    pageNum.value = next.pageNum
    pageSize.value = next.pageSize
    void reload()
  }

  function goFirstPage(): void {
    pageNum.value = 1
  }

  return { rows, total, pageNum, pageSize, loading, error, reload, onPageChange, goFirstPage }
}
