<script setup lang="ts">
/**
 * 统一状态组件（FE-09 §2 / §5）：loading / empty / error。
 * 三个合在一个文件里，理由是它们共享同样的"容器 + 文案"结构，
 * 分开写会产生三份几乎相同的模板。
 */
defineProps<{
  loading?: boolean
  error?: string | null
  empty?: boolean
  emptyText?: string
}>()
</script>

<template>
  <div class="state">
    <div v-if="loading" class="state__item"><span class="spinner" aria-hidden="true" /><span>加载中…</span></div>
    <div v-else-if="error" class="state__item state__item--error">{{ error }}</div>
    <div v-else-if="empty" class="state__item state__item--empty">{{ emptyText ?? '暂无数据' }}</div>
    <slot v-else />
  </div>
</template>
