<script setup lang="ts">
/**
 * PermissionTree —— 角色授权用的资源层级列表（菜单 → 页面 → 按钮 / 接口）。
 *
 * 逻辑全在 `usePermissionTree` 里（可单测），这里只管渲染与交互。
 *
 * ## 语义（与"常见权限树"不同，必须说清楚）
 *
 * - 勾选框表示该资源**自身**是否在授权集合里，与后端
 *   `role_permissions` 的存储形状一一对应（四类各自独立）。
 * - **点击会把同一状态带给该节点下的全部资源**（含自身）—— 这就是"联动"，
 *   但它只发生在点击时，不是状态推导。父节点不会因为"子节点都勾了"
 *   而自动变成已授权，也不会因为"子节点取消"而被取消。
 * - 原因见 `usePermissionTree` 模块注释：真实数据里
 *   `DEPARTMENT_ADMIN` 持有页面但不持有该页面的全部按钮。
 *   若父项状态由子项派生，任何人保存一次就会把这个角色的授权改成另一个形状。
 * - 有下级的分支显示 `已授权/总数`，让"页面在、按钮不全"这种混合态可见。
 */
import { computed, ref } from 'vue'
import { NButton, NCheckbox, NIcon } from 'naive-ui'
import { ChevronDownOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import {
  applyCascade,
  buildPermissionTree,
  expandableRowKeys,
  flattenTree,
  grantKey,
  keysOfTree,
  selectionToSet,
} from '@/composables/usePermissionTree'
import type { PermissionTreeNode } from '@/composables/usePermissionTree'
import { GRANT_KIND_LABEL } from '@/types'
import type { GrantSelection } from '@/types'
import type { ID } from '@/types/common'
import type { PermissionResource } from '@/types'

const props = withDefaults(
  defineProps<{
    menus: PermissionResource[]
    pages: PermissionResource[]
    buttons: PermissionResource[]
    apis: PermissionResource[]
    /** 菜单 ID → 已挂载页面 ID（来自后端 `menu_pages`，不是命名约定）。 */
    menuPages: Record<ID, ID[]>
    /** 四类已授权 id 集合；组件不修改它，只通过事件请求替换。 */
    modelValue: GrantSelection
    disabled?: boolean
  }>(),
  { disabled: false },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: GrantSelection): void }>()

const tree = computed<PermissionTreeNode[]>(() =>
  buildPermissionTree({
    menus: props.menus,
    pages: props.pages,
    buttons: props.buttons,
    apis: props.apis,
    menuPages: props.menuPages,
  }),
)

/** 折叠的节点键。默认全部展开 —— 看不见层级正是这次要解决的问题。 */
const collapsed = ref<Set<string>>(new Set())

const rows = computed(() => flattenTree(tree.value, props.modelValue, collapsed.value))
const grantedSet = computed(() => selectionToSet(props.modelValue))
const allKeys = computed(() => keysOfTree(tree.value))
const grantedTotal = computed(() => allKeys.value.filter((key) => grantedSet.value.has(key)).length)

function kindLabel(kind: PermissionTreeNode['kind']): string {
  return kind === null ? '分组' : GRANT_KIND_LABEL[kind]
}

function isGranted(node: PermissionTreeNode): boolean {
  return node.kind !== null && node.id !== null && grantedSet.value.has(grantKey(node.kind, node.id))
}

function toggleNode(node: PermissionTreeNode, checked: boolean): void {
  // 分组节点没有对应的资源，点它等于什么都没做 —— 直接不派发事件，
  // 免得父组件收到一个"内容没变"的更新而误以为用户改了什么。
  if (props.disabled || node.kind === null) return
  emit('update:modelValue', applyCascade(props.modelValue, node, checked))
}

function toggleCollapse(key: string): void {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}

function collapseAll(): void {
  collapsed.value = new Set(expandableRowKeys(tree.value))
}

function expandAll(): void {
  collapsed.value = new Set()
}

/** 分支的授权计数：`已授权/总数`，含该分支自身。 */
function countText(row: { grantedCount: number; totalCount: number }): string {
  return `${row.grantedCount}/${row.totalCount}`
}
</script>

<template>
  <section class="ptree-wrap">
    <header class="ptree-head">
      <span class="ptree-head__summary">
        已授权 <strong>{{ grantedTotal }}</strong> / {{ allKeys.length }} 项
      </span>
      <span class="ptree-head__spacer" />
      <NButton size="tiny" quaternary :disabled="disabled" @click="expandAll">展开全部</NButton>
      <NButton size="tiny" quaternary :disabled="disabled" @click="collapseAll">收起全部</NButton>
    </header>

    <p class="ptree-head__hint">
      勾选框表示该资源「自身」是否授权；点一次会把同一状态带给它下面的所有资源。
      分支后的计数（如 <code>5/6</code>）表示该分支下已授权的项数，含它自己 ——
      页面已授权但按钮只勾了一部分时，这里就会显示成这样。
    </p>

    <div v-if="rows.length === 0" class="ptree-empty">没有可授权的资源</div>

    <ul v-else class="ptree">
      <li
        v-for="row in rows"
        :key="row.key"
        class="ptree__row"
        :class="{ 'ptree__row--group': row.node.kind === null }"
        :style="{ paddingLeft: `${8 + row.depth * 22}px` }"
      >
        <button
          v-if="row.hasChildren"
          type="button"
          class="ptree__caret"
          :aria-expanded="!collapsed.has(row.key)"
          :aria-label="`${collapsed.has(row.key) ? '展开' : '收起'} ${row.node.name}`"
          @click="toggleCollapse(row.key)"
        >
          <NIcon :component="collapsed.has(row.key) ? ChevronForwardOutline : ChevronDownOutline" />
        </button>
        <span v-else class="ptree__caret ptree__caret--leaf" aria-hidden="true" />

        <NCheckbox
          v-if="row.node.kind !== null"
          :checked="isGranted(row.node)"
          :disabled="disabled"
          :aria-label="row.node.name"
          @update:checked="(checked: boolean) => toggleNode(row.node, checked)"
        />
        <span v-else class="ptree__nogrant" aria-hidden="true" />

        <span class="ptree__kind" :class="`ptree__kind--${(row.node.kind ?? 'GROUP').toLowerCase()}`">
          {{ kindLabel(row.node.kind) }}
        </span>
        <span class="ptree__name">{{ row.node.name }}</span>
        <code v-if="row.node.code" class="ptree__code">{{ row.node.code }}</code>
        <span v-if="row.node.meta" class="ptree__meta">{{ row.node.meta }}</span>

        <span
          v-if="row.hasChildren"
          class="ptree__count"
          :class="{
            'is-full': row.grantedCount === row.totalCount,
            'is-none': row.grantedCount === 0,
          }"
          :title="`该分支下共 ${row.totalCount} 项可授权资源，其中 ${row.grantedCount} 项已授权（含本级）`"
        >
          {{ countText(row) }}
        </span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ptree-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.ptree-head__summary {
  font-size: 13px;
  color: var(--vctn-text-weak);
}

.ptree-head__spacer {
  flex: 1;
}

.ptree-head__hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--vctn-text-weak);
  line-height: 1.6;
}

.ptree-empty {
  padding: 16px 0;
  color: var(--vctn-text-weak);
  font-size: 13px;
}

.ptree {
  list-style: none;
  margin: 0;
  padding: 4px 6px;
  max-height: 460px;
  overflow: auto;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  background: var(--vctn-surface);
}

.ptree__row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 3px;
  padding-bottom: 3px;
  border-radius: var(--vctn-radius-sm);
}

.ptree__row:hover {
  background: var(--vctn-fill-muted);
}

.ptree__row--group {
  font-weight: 600;
}

.ptree__caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--vctn-text-weak);
  cursor: pointer;
  flex: none;
}

.ptree__caret--leaf {
  cursor: default;
}

.ptree__nogrant {
  display: inline-block;
  width: 22px;
  flex: none;
}

.ptree__kind {
  flex: none;
  min-width: 34px;
  padding: 1px 5px;
  border-radius: var(--vctn-radius-sm);
  font-size: 11px;
  text-align: center;
  background: var(--vctn-fill-muted);
  color: var(--vctn-text-weak);
}

.ptree__name {
  font-size: 13px;
}

.ptree__code {
  font-size: 11px;
  color: var(--vctn-text-weak);
}

.ptree__meta {
  font-size: 11px;
  color: var(--vctn-text-weak);
}

.ptree__count {
  margin-left: auto;
  flex: none;
  font-size: 11px;
  color: var(--vctn-text-weak);
  font-variant-numeric: tabular-nums;
}

.ptree__count.is-full {
  color: var(--vctn-primary);
}

.ptree__count.is-none {
  opacity: 0.55;
}
</style>
