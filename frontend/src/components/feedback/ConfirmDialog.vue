<script setup lang="ts">
/**
 * ConfirmDialog（FE-09 §3）。
 *
 * 危险操作（删除、禁用、重置口令、撤销会话）一律走确认，
 * 且确认框要写清**后果**，不能只写一句"确定吗"。
 */
import { ref } from 'vue'

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

const confirmed = ref(false)

function onConfirm(): void {
  if (props.loading) return
  confirmed.value = false
  emit('confirm')
}
</script>

<template>
  <div v-if="props.open" class="dialog-mask" role="dialog" aria-modal="true" @click.self="emit('cancel')">
    <div class="dialog">
      <h3 class="dialog__title">{{ props.title }}</h3>
      <p v-if="props.description" class="dialog__desc">{{ props.description }}</p>
      <p v-else-if="confirmed" class="dialog__desc dialog__desc--empty">该操作不可撤销。</p>
      <div class="dialog__actions">
        <button class="btn" type="button" :disabled="props.loading" @click="emit('cancel')">取消</button>
        <button
          class="btn"
          :class="props.danger ? 'btn--danger' : 'btn--primary'"
          type="button"
          :disabled="props.loading"
          @click="onConfirm"
        >
          <span v-if="props.loading" class="spinner spinner--sm" aria-hidden="true" />
          {{ props.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>
