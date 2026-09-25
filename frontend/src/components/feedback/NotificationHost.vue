<script setup lang="ts">
/**
 * 全局提示（FE-09 §3）。
 *
 * 承载 appStore.notice，并**自动消失**。错误信息在 UI 上的默认停留时间是
 * 5 秒 —— 太短会让人看不清发生了什么，太长会长期遮挡内容。
 */
import { onMounted, onUnmounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
let timer: number | undefined

function scheduleClear(): void {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = window.setTimeout(() => appStore.clearNotice(), 5000)
}

watch(
  () => appStore.notice,
  (notice) => {
    if (notice !== null) scheduleClear()
  },
)

onMounted(scheduleClear)
onUnmounted(() => {
  if (timer !== undefined) window.clearTimeout(timer)
})
</script>

<template>
  <div v-if="appStore.notice" class="notice" :class="`notice--${appStore.notice.type}`" role="status">
    <span>{{ appStore.notice.message }}</span>
    <button type="button" class="notice__close" aria-label="关闭" @click="appStore.clearNotice()">×</button>
  </div>
</template>
