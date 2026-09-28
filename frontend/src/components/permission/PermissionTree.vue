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
  ANOMALY_HINT,
  applyBulkSelection,
  applyCascade,
  buildPermissionTree,
  collectAnomalies,
  expandableRowKeys,
  flattenTree,
  grantKey,
  keysOfTree,
  selectionToSet,
} from '@/composables/usePermissionTree'
import type {
  BulkSelectionMode,
  PermissionTreeNode,
  TreeAnomaly,
} from '@/composables/usePermissionTree'
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

/**
 * 批量按钮是否不可用。
 *
 * 清单为空（资源还没取回来）时也必须禁用：此时"全选"什么都不会发生，
 * 但用户会以为已经选完了 —— 点完看不到变化比按钮灰着更难排查。
 */
const bulkDisabled = computed(() => props.disabled || allKeys.value.length === 0)

/**
 * 数据异常分组（无导航入口的页面 / 上级不存在的菜单）。
 *
 * 空数组是**正常状态**。非空时要主动说清楚，因为这两组出现在树里
 * 看起来像是"系统自带的分组"，实际是需要管理员去修的配置问题 ——
 * 不说的话，用户只会看到一个名叫「未挂载菜单的页面」的组，然后来问
 * "为什么会有这个"。
 */
const anomalies = computed(() => collectAnomalies(tree.value))

function anomalyText(kind: TreeAnomaly, count: number): string {
  return `${ANOMALY_HINT[kind]}（${count} 项）`
}

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

/**
 * 批量选择。
 *
 * 与单点勾选一样**只改本地选择、不直接提交** —— 是否落库仍由页面的
 * 「保存权限」决定。这里若顺手提交，一次误点"取消全部"就会立刻清空
 * 一个角色的全部授权，而这类操作没有撤销入口。
 */
function bulk(mode: BulkSelectionMode): void {
  if (props.disabled) return
  emit('update:modelValue', applyBulkSelection(props.modelValue, tree.value, mode))
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
      <span class="ptree-head__bulk">
        <NButton size="tiny" quaternary :disabled="bulkDisabled" @click="bulk('all')">全选</NButton>
        <NButton size="tiny" quaternary :disabled="bulkDisabled" @click="bulk('none')">
          取消全部
        </NButton>
        <NButton size="tiny" quaternary :disabled="bulkDisabled" @click="bulk('invert')">
          反选
        </NButton>
      </span>
      <span class="ptree-head__spacer" />
      <NButton size="tiny" quaternary :disabled="disabled" @click="expandAll">展开全部</NButton>
      <NButton size="tiny" quaternary :disabled="disabled" @click="collapseAll">收起全部</NButton>
    </header>

    <p class="ptree-head__hint">
      勾选框表示该资源「自身」是否授权；点一次会把同一状态带给它下面的所有资源。
      分支后的计数（如 <code>5/6</code>）表示该分支下已授权的项数，含它自己 ——
      页面已授权但按钮只勾了一部分时，这里就会显示成这样。
      「全选 / 取消全部 / 反选」作用于**上方清单里的全部资源**，改完仍需点「保存权限」才会生效。
    </p>

    <!--
      异常分组说明。只在真的出现异常时渲染 —— 正常情况下这一段根本不存在，
      而不是渲染一个空壳。
    -->
    <p v-if="anomalies.length > 0" class="ptree-anomaly">
      <strong>配置需要处理：</strong>
      <span v-for="item in anomalies" :key="item.kind" class="ptree-anomaly__item">
        {{ anomalyText(item.kind, item.count) }}
      </span>
    </p>

    <div v-if="rows.length === 0" class="ptree-empty">没有可授权的资源</div>

    <ul v-else class="ptree">
      <li
        v-for="row in rows"
        :key="row.key"
        class="ptree__row"
        :class="{
          'ptree__row--group': row.node.kind === null,
          'ptree__row--anomaly': row.node.anomaly !== undefined,
        }"
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
        <span
          v-if="row.node.anomaly !== undefined"
          class="ptree__flag"
          title="这不是一个正常分组，而是需要处理的配置问题"
        >
          待处理
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

/* 左侧「已授权 N / M 项」是只读读数，右侧三个按钮会**改内容**
   （其中"取消全部"还是破坏性的），中间用 1px 竖线把"读数"与"能点的东西"分开。
   没有这条线，一行里五个同款小号按钮挨在一起，看不出哪几个会动数据。

   ⚠️ 这条线加在 `.ptree-head__bulk` 的**左边**，所以它实际落在
   「摘要 | 批量」之间，而不是「批量 | 展开/收起」之间 —— DOM 顺序是
   摘要 → 批量 → 弹性空白 → 展开/收起。展开/收起 已被弹性空白推到最右，
   中间隔着整行空白，本来就不需要再加线；窄到弹性空白被压没时，
   这条线顺带成了「批量 | 展开/收起」的边界。
   两种情形下它都不会落在某一组**内部**，这正是它的作用。
   （`grantTrees.spec.ts` 有一条用例钉住这个 DOM 顺序 —— 顺序一变，线就跑到别处去了。） */
.ptree-head__bulk {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 6px;
  padding-left: 10px;
  border-left: 1px solid var(--vctn-border);
}

.ptree-head__hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--vctn-text-weak);
  line-height: 1.6;
}

/* 异常分组的说明条。用 warn 色而不是 danger：
   这两组不影响授权能否保存（页面照样可勾、可授权），
   只是"配置没配完"，用报错色会让人以为保存会失败。 */
.ptree-anomaly {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 0 0 8px;
  padding: 6px 10px;
  border-radius: var(--vctn-radius-sm);
  background: var(--vctn-warn-weak);
  color: var(--vctn-warn);
  font-size: 12px;
  line-height: 1.6;
}

.ptree-anomaly__item {
  flex: none;
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

/* 分组节点。树里 `kind === null` 的**只可能是**异常分组 ——
   菜单分组（系统管理 / 日志管理）是 MENU 资源，走的是 `kind === 'MENU'`。
   所以这里不需要"普通分组"的样式分支，加粗即是异常分组的外观。 */
.ptree__row--group {
  font-weight: 600;
}

/* 异常分组整行加底色，扫一眼就能找到它在哪一段 ——
   列表可能很长（十几个菜单 + 几十个资源），只靠加粗在滚动时容易错过。 */
.ptree__row--anomaly {
  background: var(--vctn-warn-weak);
}

/* 这条不是冗余：`.ptree__row:hover` 是 (0,2,0)，比 `.ptree__row--anomaly`
   的 (0,1,0) 权重高 —— 不写它，鼠标一划过这行底色就被 hover 色顶掉，
   而"鼠标停在上面"恰恰是管理员准备处理它的时候。 */
.ptree__row--anomaly:hover {
  background: var(--vctn-warn-weak);
}

.ptree__flag {
  flex: none;
  padding: 1px 6px;
  border-radius: var(--vctn-radius-sm);
  background: var(--vctn-warn);
  color: #fff;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.6;
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
