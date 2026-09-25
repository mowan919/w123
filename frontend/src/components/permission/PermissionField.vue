<script setup lang="ts">
/**
 * PermissionField（FE-09 §4 / FE-05 §3 / FE-12 §5）。
 *
 * 字段权限四态：
 * - VISIBLE / EDITABLE → 正常渲染；EDITABLE 时 `editable` 为 true
 * - READ_ONLY          → 渲染但不可编辑（`editable === false`）
 * - HIDDEN             → 完全不渲染
 *
 * 后端在写入时会**再次**校验字段权限，前端这层只决定"让不让改"。
 */
import { computed } from 'vue'
import type { FieldAccessLevel } from '@/types'
import { usePermissionStore } from '@/stores/permission'

const props = defineProps<{
  /** FIELD 的 `field_key`。 */
  code: string
}>()

const permissionStore = usePermissionStore()

const level = computed<FieldAccessLevel>(() => permissionStore.getFieldPermission(props.code))
const editable = computed<boolean>(() => level.value === 'EDITABLE')

/** 未授权（HIDDEN 或键不存在）时返回 null，调用方用 `v-if` 决定不渲染。 */
const visible = computed<boolean>(() => level.value !== 'HIDDEN')
</script>

<template>
  <div v-if="visible" class="permission-field" :class="{ 'is-readonly': !editable }">
    <!-- 只读态不传原生 disabled，避免把"可读"与"可提交"两种状态混为一谈；
         两者由 `editable` 明确表达。 -->
    <slot :editable="editable" :level="level" />
  </div>
</template>
