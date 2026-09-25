<script setup lang="ts">
/**
 * PermissionButton（FE-09 §4 / FE-03 §6 / FE-12 §5）。
 *
 * 无 BUTTON 权限时：
 * - `mode="hide"`（默认）：不渲染。
 * - `mode="disable"`：渲染但禁用。
 *
 * 两种都是**展示层**控制。后端 API 授权才是最终兜底 —— 直接调接口
 * 拿不到权限照样 403（`tests/components/permission.spec.ts` 里有两个方向的
 * 用例：按钮不显示，以及"绕过按钮直接请求"仍然被拒）。
 *
 * ⚠️ `emits` **必须**显式声明。曾经漏了这一句，结果一次点击会派发**两次**
 * `click` —— 根元素上模板自带的 `@click` 与"$emit 未声明时按 fallthrough
 * 合并"的兜底路径各触发一次，父组件 `@click="save"` 就会被调两遍（重复提交）。
 * 这条是单测里"一次点击只触发一次事件"的用例钉出来的，不是靠肉眼能看出来的。
 */
import { computed } from 'vue'
import { usePermissionStore } from '@/stores/permission'

const emit = defineEmits<{ click: [MouseEvent] }>()

const props = withDefaults(
  defineProps<{
    /** BUTTON 资源编码。 */
    code: string
    /** `hide` 不渲染；`disable` 渲染但禁用。 */
    mode?: 'hide' | 'disable'
    type?: 'primary' | 'default' | 'danger' | 'text'
    disabled?: boolean
    loading?: boolean
  }>(),
  { mode: 'hide', type: 'default', disabled: false, loading: false },
)

const permissionStore = usePermissionStore()
const allowed = computed(() => permissionStore.hasButtonPermission(props.code))
</script>

<template>
  <button
    v-if="allowed || props.mode === 'disable'"
    class="btn"
    :class="[`btn--${props.type}`, { 'is-disabled': props.disabled || props.loading }]"
    :disabled="props.disabled || props.loading || (props.mode === 'disable' && !allowed)"
    :aria-disabled="props.disabled || props.loading"
    @click="allowed && !props.disabled && !props.loading && emit('click', $event)"
  >
    <span v-if="props.loading" class="spinner spinner--sm" aria-hidden="true" />
    <slot />
  </button>
</template>
