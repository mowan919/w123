<script setup lang="ts">
/**
 * 部门管理（FE-06 / `08 §4`）。
 *
 * 两条容易被忽略的约束：
 * 1. 后端只有 `/admin/departments/tree` 一个查询入口，**没有**扁平列表端点。
 *    所以这里直接渲染树，不做前端分页（分页只对列表接口才有意义）。
 * 2. 部门维度的数据范围由**后端下推到 SQL**，前端不参与判权（FE-05 §4）。
 *    页面上不出现"按数据范围过滤"的开关，那是重复实现后端职责。
 */
import { computed, ref, watch } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
import { useOrganizationStore } from '@/stores/organization'
import type { DepartmentTreeNode } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const organizationStore = useOrganizationStore()

interface DepartmentDraft {
  id: ID | null
  parent_id: ID | null
  department_code: string
  department_name: string
}

interface FlatRow {
  node: DepartmentTreeNode
  depth: number
  hasChildren: boolean
}

function draftFrom(node: DepartmentTreeNode): DepartmentDraft {
  return {
    id: node.id,
    parent_id: node.parent_id,
    department_code: node.department_code,
    department_name: node.department_name,
  }
}

const expanded = ref<Set<ID>>(new Set())
const draft = ref<DepartmentDraft | null>(null)
const saving = ref(false)
const pendingDisable = ref<DepartmentTreeNode | null>(null)
const disabling = ref(false)

const rows = computed<FlatRow[]>(() => {
  const out: FlatRow[] = []
  const walk = (nodes: DepartmentTreeNode[], depth: number): void => {
    for (const node of nodes) {
      out.push({ node, depth, hasChildren: node.children.length > 0 })
      if (node.children.length > 0 && expanded.value.has(node.id)) walk(node.children, depth + 1)
    }
  }
  walk(organizationStore.tree, 0)
  return out
})

/**
 * 展开状态跟随树的内容。
 *
 * 任何一次成功写入（新建 / 禁用）都会让 store 重拉整棵树，而新出现的分支
 * 默认是折叠的 —— 用户会把"我新建的部门怎么看不见"当成数据丢了。这里在
 * 树换掉时统一重新展开，与重拉树的时机保持一致。
 */
watch(
  () => organizationStore.tree,
  (tree) => {
    if (tree.length > 0) expandAll()
  },
)

function flatten(nodes: DepartmentTreeNode[]): DepartmentTreeNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)])
}

function expandAll(): void {
  expanded.value = new Set(flatten(organizationStore.tree).map((node) => node.id))
}

function collapseAll(): void {
  expanded.value = new Set()
}

/** 首次进入：走 store 的缓存（同一会话里别的页面已经取过就不重复发请求）。 */
function boot(): void {
  void organizationStore.ensure()
}

function startCreate(parentId: ID | null): void {
  draft.value = { id: null, parent_id: parentId, department_code: '', department_name: '' }
}

function startEdit(node: DepartmentTreeNode): void {
  draft.value = draftFrom(node)
}

async function save(): Promise<void> {
  const current = draft.value
  if (current === null) return
  saving.value = true
  try {
    if (current.id === null) {
      await organizationStore.create({
        department_code: current.department_code,
        department_name: current.department_name,
        parent_id: current.parent_id,
      })
    } else {
      await organizationStore.update(current.id, {
        department_code: current.department_code,
        department_name: current.department_name,
      })
    }
    draft.value = null
    // 树已由 store 重拉，这里只还原编辑区。
  } catch (cause) {
    // 原样回显后端错误 —— 后端会拒绝"禁用最后一个 SUPER_ADMIN"这类安全不变量
    // （RISK-002），改写一句"操作失败"会把真实的拒绝原因丢掉。
    appStore.showNotice('error', cause instanceof Error ? cause.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDisable(): Promise<void> {
  const target = pendingDisable.value
  if (target === null) return
  disabling.value = true
  try {
    await organizationStore.disable(target.id)
    pendingDisable.value = null
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '禁用失败')
  } finally {
    disabling.value = false
  }
}

boot()
</script>

<template>
  <PageContainer title="部门管理" description="部门树是全系统数据范围的骨架，父子关系由后端在数据范围下推时使用。">
    <div class="toolbar">
      <PermissionButton code="department:create" type="primary" @click="startCreate(null)">
        新增顶级部门
      </PermissionButton>
      <PermissionButton code="department:create" @click="expandAll">展开全部</PermissionButton>
      <PermissionButton code="department:create" @click="collapseAll">收起全部</PermissionButton>
      <PermissionButton code="department:edit" mode="disable" @click="organizationStore.reload()">
        刷新
      </PermissionButton>
    </div>

    <div v-if="organizationStore.error" class="alert alert--error">
      {{ organizationStore.error }}
    </div>

    <div v-else-if="organizationStore.loading" class="state">
      <span class="spinner" aria-hidden="true" /><span>加载中…</span>
    </div>

    <div v-else-if="rows.length === 0" class="state"><span class="state__item">暂无部门</span></div>

    <div v-else class="tree">
      <div
        v-for="row in rows"
        :key="row.node.id"
        class="tree__row"
        :style="{ paddingLeft: `${row.depth * 20 + 12}px` }"
      >
        <button
          v-if="row.hasChildren"
          class="tree__twisty"
          type="button"
          :aria-expanded="expanded.has(row.node.id)"
          @click="
            expanded.has(row.node.id)
              ? expanded.delete(row.node.id)
              : expanded.add(row.node.id)
          "
        >
          {{ expanded.has(row.node.id) ? '−' : '+' }}
        </button>
        <span v-else class="tree__twisty tree__twisty--leaf" aria-hidden="true" />

        <span class="tree__name">{{ row.node.department_name }}</span>
        <code class="tree__code">{{ row.node.department_code }}</code>
        <span class="tag" :class="row.node.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.node.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>

        <span class="tree__actions">
          <PermissionButton code="department:create" type="text" @click="startCreate(row.node.id)">
            新增下级
          </PermissionButton>
          <PermissionButton code="department:edit" type="text" @click="startEdit(row.node)">
            编辑
          </PermissionButton>
          <PermissionButton
            v-if="row.node.status === 'ACTIVE'"
            code="department:disable"
            type="text"
            @click="pendingDisable = row.node"
          >
            禁用
          </PermissionButton>
        </span>
      </div>
    </div>

    <div v-if="draft !== null" class="editor">
      <h3 class="editor__title">{{ draft.id === null ? '新增部门' : '编辑部门' }}</h3>
      <label class="field">
        <span class="field__label">部门编码</span>
        <input v-model="draft.department_code" class="field__control" placeholder="如 D001" />
      </label>
      <label class="field">
        <span class="field__label">部门名称</span>
        <input v-model="draft.department_name" class="field__control" />
      </label>
      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="saving" @click="save">
          <span v-if="saving" class="spinner spinner--sm" aria-hidden="true" />
          保存
        </button>
        <button class="btn" type="button" :disabled="saving" @click="draft = null">取消</button>
      </div>
    </div>

    <ConfirmDialog
      :open="pendingDisable !== null"
      title="禁用部门"
      danger
      :confirm-text="disabling ? '禁用中…' : '确认禁用'"
      :loading="disabling"
      :description="`禁用后该部门及其下级不再参与数据范围下推；已绑定的用户不受影响，但其可见范围会按后端规则重新计算。${pendingDisable === null ? '' : `部门：${pendingDisable.department_name}`}`"
      @cancel="pendingDisable = null"
      @confirm="confirmDisable"
    />
  </PageContainer>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.tree {
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  overflow: hidden;
}

.tree__row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--vctn-border);
}

.tree__row:last-child {
  border-bottom: none;
}

.tree__twisty {
  width: 18px;
  height: 18px;
  border: 1px solid var(--vctn-border);
  border-radius: 4px;
  background: var(--vctn-surface);
  cursor: pointer;
  font: inherit;
  line-height: 1;
}

.tree__twisty--leaf {
  border: none;
  background: none;
  cursor: default;
}

.tree__name {
  font-weight: 500;
}

.tree__code {
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.tree__actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.editor {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-top: 12px;
  padding: 14px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.editor__title {
  width: 100%;
  font-size: 15px;
}

.editor__actions {
  display: flex;
  gap: 8px;
}

.alert {
  padding: 10px 14px;
  border-radius: var(--vctn-radius);
  margin-bottom: 12px;
}

.alert--error {
  background: #fdeceb;
  color: var(--vctn-danger);
}
</style>
