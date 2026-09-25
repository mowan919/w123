<script setup lang="ts">
/**
 * ConfirmDialog（FE-09 §3）。
 *
 * 危险操作（删除、禁用、重置口令、撤销会话）一律走确认，
 * 且确认框要写清**后果**，不能只写一句"确定吗"。
 *
 * 外壳换成 naive 的 `NModal`：它自带焦点陷阱、Esc 关闭与遮罩滚动锁定，
 * 手写 `.dialog-mask` 全都做不到 —— 键盘用户在原生写法里会在弹窗背后
 * 继续 Tab 到页面上的按钮。对外 API（props / emits）保持一字不变。
 */
import { NButton, NModal } from 'naive-ui'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** 后果描述；危险操作必须提供。 */
    description?: string
    confirmText?: string
    danger?: boolean
    loading?: boolean
  }>(),
  { title: '确认操作', description: '', confirmText: '确定', danger: false, loading: false },
)

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

/**
 * 关闭统一走这里：遮罩点击、Esc、右上角叉三条路径都必须发出 cancel，
 * 否则父组件的 `open` 会一直停在 true —— 弹窗看起来第二次打不开。
 */
function onClose(): void {
  emit('cancel')
}
</script>

<template>
  <NModal
    :show="props.open"
    preset="card"
    :title="props.title"
    style="width: min(420px, calc(100vw - 32px))"
    @update:show="(value: boolean) => !value && onClose()"
  >
    <p class="confirm__desc">{{ props.description || '该操作不可撤销。' }}</p>

    <template #footer>
      <div class="confirm__actions">
        <NButton quaternary :disabled="props.loading" @click="onClose">取消</NButton>
        <NButton
          :type="props.danger ? 'error' : 'primary'"
          :loading="props.loading"
          @click="emit('confirm')"
        >
          {{ props.confirmText }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.confirm__desc {
  margin: 0;
  color: var(--vctn-text-weak);
  font-size: 14px;
}

.confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
