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
import { NButton, NIcon } from 'naive-ui'
import {
  AddOutline,
  BusinessOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CreateOutline,
  GitBranchOutline,
  RefreshOutline,
  RemoveCircleOutline,
} from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
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
/**
 * 草稿**始终是对象**，另用 `draftOpen` 控制显隐：`v-model` 不允许绑定
 * 可选链表达式，草稿可空的话每个字段都得写 `draft!.x`，漏一个就是运行时空指针。
 */
const draft = ref<DepartmentDraft>({ id: null, parent_id: null, department_code: '', department_name: '' })
const draftOpen = ref(false)
const saving = ref(false)
const pendingDisable = ref<DepartmentTreeNode | null>(null)
const disabling = ref(false)

const isEditing = computed(() => draft.value.id !== null)

const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  if (draft.value.department_code.trim() === '') return '请填写部门编码'
  if (draft.value.department_name.trim() === '') return '请填写部门名称'
  return null
})

/** 编辑态下的父部门名：判断"挂在谁下面"比看一串 ID 有用。 */
const parentLabel = computed<string>(() => {
  const parentId = draft.value.parent_id
  if (parentId === null) return '顶级部门'
  const node = flatten(organizationStore.tree).find((item) => item.id === parentId)
  return node?.department_name ?? '—'
})

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

function toggleExpand(id: ID): void {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

/** 首次进入：走 store 的缓存（同一会话里别的页面已经取过就不重复发请求）。 */
function boot(): void {
  void organizationStore.ensure()
}

function startCreate(parentId: ID | null): void {
  draft.value = { id: null, parent_id: parentId, department_code: '', department_name: '' }
  draftOpen.value = true
}

function startEdit(node: DepartmentTreeNode): void {
  draft.value = draftFrom(node)
  draftOpen.value = true
}

async function save(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  saving.value = true
  try {
    if (current.id === null) {
      await organizationStore.create({
        department_code: current.department_code.trim(),
        department_name: current.department_name.trim(),
        parent_id: current.parent_id,
      })
      appStore.showNotice('success', `已创建部门 ${current.department_name.trim()}`)
    } else {
      await organizationStore.update(current.id, {
        department_code: current.department_code.trim(),
        department_name: current.department_name.trim(),
      })
      appStore.showNotice('success', '部门已更新')
    }
    draftOpen.value = false
    // 树已由 store 重拉，这里只还原编辑区。
  } catch (cause) {
    // 原样回显后端错误 —— 改写一句"操作失败"会把真实的拒绝原因丢掉。
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
    appStore.showNotice('success', `已禁用部门 ${target.department_name}`)
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '禁用失败')
  } finally {
    disabling.value = false
  }
}

boot()
</script>

<template>
  <PageContainer
    title="部门管理"
    description="维护组织架构。部门的层级关系决定了成员在各自范围内能看到的数据。"
    :icon="BusinessOutline"
  >
    <div class="toolbar">
      <PermissionButton code="department:create" type="primary" @click="startCreate(null)">
        <NIcon :component="AddOutline" />
        新增顶级部门
      </PermissionButton>
      <NButton size="small" @click="expandAll">
        <template #icon>
          <NIcon :component="ChevronDownOutline" />
        </template>
        展开全部
      </NButton>
      <NButton size="small" @click="collapseAll">
        <template #icon>
          <NIcon :component="ChevronUpOutline" />
        </template>
        收起全部
      </NButton>
      <NButton size="small" :loading="organizationStore.loading" @click="organizationStore.reload()">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
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
          @click="toggleExpand(row.node.id)"
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
          <PermissionButton code="department:create" type="text-primary" @click="startCreate(row.node.id)">
            <NIcon :component="GitBranchOutline" />
            新增下级
          </PermissionButton>
          <PermissionButton code="department:update" type="text-primary" @click="startEdit(row.node)">
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton
            v-if="row.node.status === 'ACTIVE'"
            code="department:disable"
            type="text-danger"
            @click="pendingDisable = row.node"
          >
            <NIcon :component="RemoveCircleOutline" />
            禁用
          </PermissionButton>
        </span>
      </div>
    </div>

    <FormDialog
      :open="draftOpen"
      :title="isEditing ? '编辑部门' : '新增部门'"
      :loading="saving"
      :error="draftError"
      @cancel="draftOpen = false"
      @submit="save"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">部门编码</span>
          <input v-model.trim="draft.department_code" class="field__control" placeholder="如 D001" />
        </label>
        <label class="field">
          <span class="field__label">部门名称</span>
          <input v-model.trim="draft.department_name" class="field__control" placeholder="如 技术部" />
        </label>
      </div>
      <p class="hint">
        <template v-if="isEditing">上级部门：{{ parentLabel }}（调整层级请使用「新增下级」重建）</template>
        <template v-else>上级部门：{{ parentLabel }}；新建后可在其下继续新增下级。</template>
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingDisable !== null"
      title="禁用部门"
      danger
      :confirm-text="disabling ? '禁用中…' : '确认禁用'"
      :loading="disabling"
      :description="`禁用后该部门及其下级不再参与数据范围计算，成员能看到的范围会随之收缩。${pendingDisable === null ? '' : `部门：${pendingDisable.department_name}`}`"
      @cancel="pendingDisable = null"
      @confirm="confirmDisable"
    />
  </PageContainer>
</template>
