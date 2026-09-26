import { computed, ref, watch } from 'vue'
import type { DataTableColumn } from '@/components/data/types'

/**
 * 列表字段的自定义显示与排序（FE-09 §2 的展示层增强）。
 *
 * 需求是"列表页可以自定义显示哪些字段、以及字段顺序"。这件事有两个
 * 容易做错的地方：
 *
 * 1. **持久化**：选完换个页面再回来就复位，等于每次进列表都要重设一遍。
 *    因此结果写进 `localStorage`，按页面（`storageKey`）分桶。
 *    ⚠️ 这是**纯展示偏好**，不含任何权限信息 —— 隐藏某一列不会让用户
 *    少拿到数据，数据早就跟着响应到了，能看到的范围仍由后端决定。
 *    反过来也必须成立：这里的设置**不能**用来"显示"后端没给的字段。
 * 2. **列集合变化**：后端字段演进（新增一列）或页面改版（删掉一列）之后，
 *    旧偏好里会出现"存在但已不存在"和"存在但没记录顺序"两种键。
 *    前者留着会让 `visible` 少一列（用户以为数据没了），后者会让新列
 *    永远不出现。所以每次列集合变化都要做一次**对账**。
 *
 * 顺序与可见性分开存（而不是存一个'最终列表'）：新增列时只需把它追加到
 * 顺序末尾，用户的既有排列完全不受影响。
 */

const STORAGE_PREFIX = 'vctn.columns.'

interface Persisted {
  v: 1
  order: string[]
  hidden: string[]
}

function read(key: string): Persisted | null {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${key}`)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object') return null
    const value = parsed as Partial<Persisted>
    if (!Array.isArray(value.order) || !Array.isArray(value.hidden)) return null
    return {
      v: 1,
      order: value.order.filter((item): item is string => typeof item === 'string'),
      hidden: value.hidden.filter((item): item is string => typeof item === 'string'),
    }
  } catch {
    // 隐私模式 / 存的是别的形状的脏数据：当作"没有偏好"，绝不因此白屏。
    return null
  }
}

function write(key: string, value: Persisted): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, JSON.stringify(value))
  } catch {
    // 配额耗尽 / 隐私模式：偏好失效但不影响本次会话的使用。
  }
}

export interface ColumnSettingItem {
  key: string
  title: string
  visible: boolean
}

/**
 * @param storageKey 页面标识（如 `users`），用于分桶持久化。
 * @param columns    列定义，顺序与可见性以它为准做对账。
 */
export function useColumnSettings<T>(storageKey: string, columns: Array<DataTableColumn<T>>) {
  const allKeys = columns.map((column) => column.key as string)

  function reconcile(saved: Persisted | null): { order: string[]; hidden: string[] } {
    const known = new Set(allKeys)
    // 顺序：保留仍存在的已记录列，再按列定义顺序补上新增列。
    const kept = (saved?.order ?? []).filter((key) => known.has(key))
    const seen = new Set(kept)
    const order = [...kept, ...allKeys.filter((key) => !seen.has(key))]
    // 隐藏集合：丢掉已经不存在的列。
    const hidden = (saved?.hidden ?? []).filter((key) => known.has(key))
    return { order, hidden }
  }

  const initial = reconcile(read(storageKey))
  const order = ref<string[]>(initial.order)
  const hidden = ref<Set<string>>(new Set(initial.hidden))

  function persist(): void {
    write(storageKey, { v: 1, order: order.value, hidden: [...hidden.value] })
  }

  // 列集合变化（新增/删除列）时对账，而不是等用户下次手动重置。
  watch(
    () => allKeys.join('|'),
    () => {
      const next = reconcile({ v: 1, order: order.value, hidden: [...hidden.value] })
      order.value = next.order
      hidden.value = new Set(next.hidden)
      persist()
    },
  )

  const byKey = computed(() => new Map(columns.map((column) => [column.key as string, column])))
  const titleOf = (key: string): string => byKey.value.get(key)?.title ?? key

  /** 实际渲染的列：按自定义顺序，且过滤掉隐藏列。 */
  const visible = computed<Array<DataTableColumn<T>>>(() => {
    const out: Array<DataTableColumn<T>> = []
    for (const key of order.value) {
      const column = byKey.value.get(key)
      if (column !== undefined && !hidden.value.has(key)) out.push(column)
    }
    return out
  })

  /** 供设置面板渲染的条目（含已隐藏的列）。 */
  const items = computed<ColumnSettingItem[]>(() =>
    order.value.map((key) => ({ key, title: titleOf(key), visible: !hidden.value.has(key) })),
  )

  const visibleCount = computed(() => allKeys.length - hidden.value.size)

  function toggle(key: string): void {
    const next = new Set(hidden.value)
    if (next.has(key)) {
      next.delete(key)
    } else {
      // 至少留一列：全部隐藏会得到一张没有表头的空表格，用户会以为加载失败。
      if (allKeys.length - next.size <= 0) return
      next.add(key)
    }
    hidden.value = next
    persist()
  }

  function move(key: string, delta: -1 | 1): void {
    const index = order.value.indexOf(key)
    const target = index + delta
    if (index < 0 || target < 0 || target >= order.value.length) return
    const next = [...order.value]
    const [moved] = next.splice(index, 1)
    if (moved === undefined) return
    next.splice(target, 0, moved)
    order.value = next
    persist()
  }

  function reset(): void {
    order.value = [...allKeys]
    hidden.value = new Set()
    persist()
  }

  const isDirty = computed(
    () => order.value.join('|') !== allKeys.join('|') || hidden.value.size > 0,
  )

  return { visible, items, visibleCount, order, hidden, toggle, move, reset, isDirty }
}

/** 供测试与"清空偏好"入口使用。 */
export function columnSettingsStorageKey(pageKey: string): string {
  return `${STORAGE_PREFIX}${pageKey}`
}
