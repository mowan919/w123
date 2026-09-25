<script setup lang="ts">
/**
 * 全局提示（FE-09 §3）。
 *
 * 承载 appStore.notice，并**自动消失**。错误信息在 UI 上的默认停留时间是
 * 5 秒 —— 太短会让人看不清发生了什么，太长会长期遮挡内容。
 *
 * 为什么仍然自己画，不用 naive 的 `useNotification()`：
 * 这个组件挂在 `AppLayout` 里，而单测经常**只挂载某个页面**。换成需要注入
 * Provider 的实现后，任何不带 Provider 的挂载都会在 setup 阶段就抛错 ——
 * 为了一条提示把整套视图测试搭进去，代价不对等。
 */
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { AlertCircleOutline, CheckmarkCircleOutline, InformationCircleOutline } from '@vicons/ionicons5'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
let timer: number | undefined

const icon = computed(() => {
  switch (appStore.notice?.type) {
    case 'error':
      return AlertCircleOutline
    case 'success':
      return CheckmarkCircleOutline
    default:
      return InformationCircleOutline
  }
})

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
    <span class="notice__icon"><component :is="icon" /></span>
    <span class="notice__text">{{ appStore.notice.message }}</span>
    <button type="button" class="notice__close" aria-label="关闭" @click="appStore.clearNotice()">
      ×
    </button>
  </div>
</template>

<style scoped>
.notice {
  position: fixed;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: min(560px, calc(100vw - 32px));
  padding: 10px 14px;
  border-radius: 999px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  box-shadow: var(--vctn-shadow-md);
  z-index: 200;
  animation: notice-in var(--vctn-motion);
}

.notice__icon {
  display: inline-flex;
  font-size: 18px;
  flex: 0 0 auto;
}

.notice__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.notice--error {
  border-color: rgba(229, 72, 77, 0.4);
  background: var(--vctn-danger-weak);
  color: var(--vctn-danger);
}

.notice--success {
  border-color: rgba(18, 161, 80, 0.4);
  background: var(--vctn-success-weak);
  color: var(--vctn-success);
}

.notice--info {
  border-color: rgba(59, 110, 246, 0.4);
  background: var(--vctn-primary-weak);
  color: var(--vctn-primary);
}

.notice__close {
  border: none;
  background: none;
  font-size: 18px;
  cursor: pointer;
  color: inherit;
  line-height: 1;
  opacity: 0.7;
  flex: 0 0 auto;
}

.notice__close:hover {
  opacity: 1;
}

@keyframes notice-in {
  from {
    opacity: 0;
    transform: translate(-50%, -10px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .notice {
    animation: none;
  }
}
</style>
