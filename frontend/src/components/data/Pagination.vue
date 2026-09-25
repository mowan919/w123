<script setup lang="ts">
/**
 * Pagination（FE-09 §6）。
 *
 * 分页语义完全来自后端冻结的分页约定（请求 `pageNum` / `pageSize`，
 * 响应 `{ list, total, pageNum, pageSize }`）。这里**不**引入
 * "第几页从 0 开始""每页多少条"的本地概念，避免与后端错位一格。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    total: number
    pageNum: number
    pageSize: number
    /** 可选的每页条数。 */
    pageSizes?: number[]
    disabled?: boolean
  }>(),
  { pageSizes: () => [10, 20, 50, 100], disabled: false },
)

const emit = defineEmits<{
  (e: 'change', page: { pageNum: number; pageSize: number }): void
}>()

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize))))

function go(page: number): void {
  if (props.disabled) return
  const target = Math.min(Math.max(1, page), pageCount.value)
  if (target === props.pageNum) return
  emit('change', { pageNum: target, pageSize: props.pageSize })
}

function changeSize(event: Event): void {
  if (props.disabled) return
  const size = Number((event.target as HTMLSelectElement).value)
  emit('change', { pageNum: 1, pageSize: size })
}

/** 页码窗口，两端固定，中间按需展开。 */
const pages = computed<number[]>(() => {
  const current = props.pageNum
  const last = pageCount.value
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1)
  const items: number[] = [1, last]
  const start = Math.max(2, current - 1)
  const end = Math.min(last - 1, current + 1)
  if (start > 2) items.push(-1)
  for (let i = start; i <= end; i += 1) items.push(i)
  if (end < last - 1) items.push(-1)
  return items
})

const rangeText = computed(() => {
  if (props.total === 0) return '共 0 条'
  const from = (props.pageNum - 1) * props.pageSize + 1
  const to = Math.min(props.pageNum * props.pageSize, props.total)
  return `第 ${from}–${to} 条 / 共 ${props.total} 条`
})
</script>

<template>
  <div class="pagination" :class="{ 'is-disabled': props.disabled }">
    <span class="pagination__range">{{ rangeText }}</span>
    <select
      class="pagination__size"
      :value="props.pageSize"
      :disabled="props.disabled"
      aria-label="每页条数"
      @change="changeSize"
    >
      <option v-for="size in props.pageSizes" :key="size" :value="size">{{ size }} 条/页</option>
    </select>
    <button class="pagination__btn" :disabled="props.disabled || props.pageNum <= 1" @click="go(props.pageNum - 1)">
      上一页
    </button>
    <template v-for="(item, index) in pages" :key="`${item}-${index}`">
      <span v-if="item === -1" class="pagination__gap">…</span>
      <button
        v-else
        class="pagination__btn pagination__btn--page"
        :class="{ 'is-active': item === props.pageNum }"
        :aria-current="item === props.pageNum ? 'page' : undefined"
        :disabled="props.disabled"
        @click="go(item)"
      >
        {{ item }}
      </button>
    </template>
    <button class="pagination__btn" :disabled="props.disabled || props.pageNum >= pageCount" @click="go(props.pageNum + 1)">
      下一页
    </button>
  </div>
</template>
