<script setup lang="ts">
/**
 * Pagination（FE-09 §6）。
 *
 * 分页语义完全来自后端冻结的分页约定（请求 `pageNum` / `pageSize`，
 * 响应 `{ list, total, pageNum, pageSize }`）。这里**不**引入
 * "第几页从 0 开始""每页多少条"的本地概念，避免与后端错位一格。
 *
 * 渲染交给 naive 的 `NPagination`：手写版需要自己维护页码窗口、
 * 省略号位置、按钮禁用态与键盘可达性，每一项都容易只差一点点；
 * 换掉之后这些边界（末页、跳到末页、每页条数变化后页码越界）都由组件库负责。
 *
 * ⚠️ 对外 API（props / emits）与手写版**逐字保持一致**：10 个列表页
 * 只传 `total / page-num / page-size` 并监听 `change`，替换渲染层不需要
 * 动任何一个调用点。
 */
import { computed } from 'vue'
import { NPagination } from 'naive-ui'

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

function onPage(page: number): void {
  if (props.disabled || page === props.pageNum) return
  emit('change', { pageNum: page, pageSize: props.pageSize })
}

/**
 * 每页条数变化后**必须回到第 1 页**。
 *
 * 停留在原页码上是错的：在第 5 页把每页 10 条改成 100 条，结果集只有
 * 1 页，用户会看到一个空列表 —— 而数据其实还在。`update:page-size`
 * 不保证会同时给出修正后的页码（naive 内部只在**渲染**时夹取），
 * 所以这里显式归 1。
 */
function onPageSize(size: number): void {
  if (props.disabled || size === props.pageSize) return
  emit('change', { pageNum: 1, pageSize: size })
}

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
    <NPagination
      :page="props.pageNum"
      :page-size="props.pageSize"
      :item-count="props.total"
      :page-sizes="props.pageSizes"
      :disabled="props.disabled"
      :page-slot="7"
      show-size-picker
      @update:page="onPage"
      @update:page-size="onPageSize"
    />
  </div>
</template>
