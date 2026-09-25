<script setup lang="ts">
/**
 * 权限资源维护（DD-20 / `08 §3`）。
 *
 * 这五类资源（PAGE / MENU / BUTTON / API / FIELD）是**权限的元数据**：
 * 没有它们就没有可授权的对象。因此这一页是"定义权限"的入口，而不是
 * "给用户分配权限"的入口 —— 后者按角色维度，在权限配置页。
 *
 * 注意两个反直觉的点：
 * 1. 删除端点是 `POST /{id}/delete` 而不是 `DELETE` —— 后端冻结的路径。
 * 2. 树形查询 `/permission-resources/tree` 与 `/{resource_id}` 的路由顺序
 *    由后端注册顺序保证；前端只要别自己拼错路径。
 *
 * 树形不做递归组件：模板不能自引用，用一个自定义递归组件反而更难测。
 * 这里先把树压平成带层级的行列表再渲染，与部门页同一套做法。
 */
import { computed, onMounted, ref } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
import {
  createResource,
  deleteResource,
  getMenuPages,
  getResourceTree,
  listResources,
  setMenuPages,
  updateResource,
} from '@/api/endpoints/resources'
import type { DataTableColumn } from '@/components/data/types'
import type {
  PermissionResource,
  PermissionResourceTreeNode,
  PermissionStatus,
  ResourceType,
} from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()

const columns: Array<DataTableColumn<PermissionResource>> = [
  { key: 'resource_name', title: '名称' },
  { key: 'resource_code', title: '编码' },
  { key: 'resource_type', title: '类型', width: '90px' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
  { key: 'route_path', title: '路由 / 路径' },
]

const KINDS: ResourceType[] = ['PAGE', 'MENU', 'BUTTON', 'API', 'FIELD']

interface ResourceDraft {
  id: ID | null
  resource_type: ResourceType
  resource_code: string
  resource_name: string
  route_path: string
  component_path: string
  api_method: string
  api_path: string
  field_key: string
}

interface FlatTreeNode {
  node: PermissionResourceTreeNode
  depth: number
}

const rows = ref<PermissionResource[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

const keyword = ref('')
const kindFilter = ref<ResourceType | null>(null)
const statusFilter = ref<PermissionStatus | null>(null)

const mode = ref<'list' | 'tree'>('list')
const treeNodes = ref<PermissionResourceTreeNode[]>([])

const draft = ref<ResourceDraft | null>(null)
const saving = ref(false)
const pendingDelete = ref<PermissionResource | null>(null)
const deleting = ref(false)

/** 菜单 → 页面 的子表。只有 MENU 类型才有意义。 */
const menuPages = ref<{ menu_id: ID; pages: PermissionResource[] } | null>(null)
const menuPageSelection = ref<ID[]>([])
const pageLoading = ref(false)

const flatTree = computed<FlatTreeNode[]>(() => {
  const out: FlatTreeNode[] = []
  const walk = (nodes: PermissionResourceTreeNode[], depth: number): void => {
    for (const node of nodes) {
      out.push({ node, depth })
      walk(node.children, depth + 1)
    }
  }
  walk(treeNodes.value, 0)
  return out
})

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listResources({
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      resourceType: kindFilter.value,
      status: statusFilter.value,
      keyword: keyword.value,
    })
    rows.value = result.list
    total.value = result.total
    pageNum.value = result.pageNum
    pageSize.value = result.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '资源加载失败'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function loadTree(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    treeNodes.value = await getResourceTree({
      resourceType: kindFilter.value,
      status: statusFilter.value,
      keyword: keyword.value,
    })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '资源树加载失败'
    treeNodes.value = []
  } finally {
    loading.value = false
  }
}

function reload(): void {
  if (mode.value === 'list') void load()
  else void loadTree()
}

function search(): void {
  pageNum.value = 1
  reload()
}

function resetFilters(): void {
  keyword.value = ''
  kindFilter.value = null
  statusFilter.value = null
  pageNum.value = 1
  reload()
}

function onPageChange(next: { pageNum: number; pageSize: number }): void {
  pageNum.value = next.pageNum
  pageSize.value = next.pageSize
  void load()
}

function switchMode(next: 'list' | 'tree'): void {
  mode.value = next
  pageNum.value = 1
  reload()
}

function startCreate(kind: ResourceType): void {
  draft.value = {
    id: null,
    resource_type: kind,
    resource_code: '',
    resource_name: '',
    route_path: '',
    component_path: '',
    api_method: '',
    api_path: '',
    field_key: '',
  }
}

function startEdit(resource: PermissionResource): void {
  draft.value = {
    id: resource.id,
    resource_type: resource.resource_type,
    resource_code: resource.resource_code,
    resource_name: resource.resource_name,
    route_path: resource.route_path ?? '',
    component_path: resource.component_path ?? '',
    api_method: resource.api_method ?? '',
    api_path: resource.api_path ?? '',
    field_key: resource.field_key ?? '',
  }
}

function submit(): void {
  const current = draft.value
  if (current === null) return
  saving.value = true
  void (async () => {
    try {
      if (current.id === null) {
        await createResource({
          resource_type: current.resource_type,
          resource_code: current.resource_code,
          resource_name: current.resource_name,
          route_path: current.route_path || null,
          component_path: current.component_path || null,
          api_method: current.api_method || null,
          api_path: current.api_path || null,
          field_key: current.field_key || null,
        })
      } else {
        await updateResource(current.id, {
          resource_name: current.resource_name,
          route_path: current.route_path || null,
          component_path: current.component_path || null,
          api_method: current.api_method || null,
          api_path: current.api_path || null,
          field_key: current.field_key || null,
        })
      }
      draft.value = null
      reload()
    } catch (cause) {
      notice(cause, '保存失败')
    } finally {
      saving.value = false
    }
  })()
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deleting.value = true
  try {
    await deleteResource(target.id)
    pendingDelete.value = null
    reload()
  } catch (cause) {
    notice(cause, '删除失败')
  } finally {
    deleting.value = false
  }
}

async function openMenuPages(resource: PermissionResource): Promise<void> {
  pageLoading.value = true
  try {
    menuPages.value = await getMenuPages(resource.id)
    menuPageSelection.value = menuPages.value.pages.map((page) => page.id)
  } catch (cause) {
    notice(cause, '页面清单加载失败')
  } finally {
    pageLoading.value = false
  }
}

function toggleMenuPage(id: ID): void {
  const next = new Set(menuPageSelection.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  menuPageSelection.value = [...next]
}

async function saveMenuPages(): Promise<void> {
  const current = menuPages.value
  if (current === null) return
  pageLoading.value = true
  try {
    await setMenuPages(current.menu_id, menuPageSelection.value)
    menuPages.value = null
    reload()
  } catch (cause) {
    notice(cause, '页面保存失败')
  } finally {
    pageLoading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageContainer title="权限资源" description="页面 / 菜单 / 按钮 / API / 字段资源定义。这里的编码就是权限判定使用的标识。">
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">关键字</span>
        <input v-model="keyword" class="field__control" placeholder="编码或名称" />
      </label>
      <label class="field">
        <span class="field__label">类型</span>
        <select v-model="kindFilter" class="field__control">
          <option value="">全部</option>
          <option v-for="kind in KINDS" :key="kind" :value="kind">{{ kind }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">状态</span>
        <select v-model="statusFilter" class="field__control">
          <option value="">全部</option>
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>
    </SearchForm>

    <div class="toolbar">
      <button class="btn" :class="{ 'btn--primary': mode === 'list' }" type="button" @click="switchMode('list')">
        列表
      </button>
      <button class="btn" :class="{ 'btn--primary': mode === 'tree' }" type="button" @click="switchMode('tree')">
        树形
      </button>
      <PermissionButton
        v-for="kind in KINDS"
        :key="kind"
        code="permission:resource-create"
        @click="startCreate(kind)"
      >
        新增 {{ kind }}
      </PermissionButton>
    </div>

    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <div v-else-if="loading" class="state"><span class="spinner" aria-hidden="true" /><span>加载中…</span></div>

    <template v-else-if="mode === 'list'">
      <DataTable
        :columns="columns"
        :rows="rows"
        :row-key="(row: PermissionResource) => row.id"
        empty-text="没有符合条件的资源"
      >
        <template #cell-status="{ row }">
          <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
            {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
          </span>
        </template>
        <template #cell-route_path="{ row }">
          <div>{{ row.route_path ?? row.api_path ?? '—' }}</div>
          <div v-if="row.component_path" class="muted">{{ row.component_path }}</div>
          <div v-if="row.api_method" class="muted">{{ row.api_method }}</div>
          <div v-if="row.field_key" class="muted">{{ row.field_key }}</div>
          <div class="row-actions">
            <PermissionButton code="permission:resource-edit" type="text" @click="startEdit(row)">
              编辑
            </PermissionButton>
            <PermissionButton
              v-if="row.resource_type === 'MENU'"
              code="permission:resource-edit"
              type="text"
              @click="openMenuPages(row)"
            >
              挂载页面
            </PermissionButton>
            <PermissionButton code="permission:resource-delete" type="text" @click="pendingDelete = row">
              删除
            </PermissionButton>
          </div>
        </template>
      </DataTable>

      <Pagination
        :total="total"
        :page-num="pageNum"
        :page-size="pageSize"
        :disabled="loading"
        @change="onPageChange"
      />
    </template>

    <div v-else class="tree">
      <div
        v-for="entry in flatTree"
        :key="entry.node.resource.id"
        class="tree__row"
        :style="{ paddingLeft: `${entry.depth * 20 + 12}px` }"
      >
        <span class="tree__name">{{ entry.node.resource.resource_name }}</span>
        <code class="tree__code">{{ entry.node.resource.resource_code }}</code>
        <span class="tag">{{ entry.node.resource.resource_type }}</span>
        <span class="tag" :class="entry.node.resource.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ entry.node.resource.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
        <span class="tree__actions">
          <PermissionButton code="permission:resource-edit" type="text" @click="startEdit(entry.node.resource)">
            编辑
          </PermissionButton>
          <PermissionButton
            v-if="entry.node.resource.resource_type === 'MENU'"
            code="permission:resource-edit"
            type="text"
            @click="openMenuPages(entry.node.resource)"
          >
            挂载页面
          </PermissionButton>
          <PermissionButton
            code="permission:resource-delete"
            type="text"
            @click="pendingDelete = entry.node.resource"
          >
            删除
          </PermissionButton>
        </span>
      </div>
      <p v-if="flatTree.length === 0" class="state__item">没有符合条件的资源</p>
    </div>

    <div v-if="draft !== null" class="editor">
      <h3 class="editor__title">
        {{ draft.id === null ? `新增 ${draft.resource_type}` : '编辑资源' }}
        <span class="tag">{{ draft.resource_type }}</span>
      </h3>

      <label class="field">
        <span class="field__label">资源编码（权限判定使用的标识）</span>
        <input v-model="draft.resource_code" class="field__control" :disabled="draft.id !== null" />
      </label>
      <label class="field">
        <span class="field__label">资源名称</span>
        <input v-model="draft.resource_name" class="field__control" />
      </label>

      <template v-if="draft.resource_type === 'PAGE' || draft.resource_type === 'MENU'">
        <label class="field">
          <span class="field__label">路由路径</span>
          <input v-model="draft.route_path" class="field__control" placeholder="/system/user" />
        </label>
        <label class="field">
          <span class="field__label">组件路径</span>
          <input v-model="draft.component_path" class="field__control" placeholder="/system/user/index" />
        </label>
      </template>

      <template v-if="draft.resource_type === 'API'">
        <label class="field">
          <span class="field__label">请求方法</span>
          <input v-model="draft.api_method" class="field__control" placeholder="GET" />
        </label>
        <label class="field">
          <span class="field__label">接口路径</span>
          <input v-model="draft.api_path" class="field__control" placeholder="/admin/users" />
        </label>
      </template>

      <template v-if="draft.resource_type === 'FIELD'">
        <label class="field">
          <span class="field__label">字段键（field_key）</span>
          <input v-model="draft.field_key" class="field__control" placeholder="field:user.phone" />
        </label>
      </template>

      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="saving" @click="submit">
          <span v-if="saving" class="spinner spinner--sm" aria-hidden="true" />
          保存
        </button>
        <button class="btn" type="button" :disabled="saving" @click="draft = null">取消</button>
      </div>
    </div>

    <div v-if="menuPages !== null" class="sub-panel">
      <h3 class="sub-panel__title">
        挂载页面 — {{ menuPages.pages.length === 0 ? '' : '' }}菜单 {{ menuPages.menu_id }}
      </h3>
      <p class="muted">
        勾选该菜单下出现的页面。未勾选的页面不会出现在菜单的路由目标里（菜单本身仍可显示）。
      </p>
      <ul class="sub-list">
        <li v-for="page in menuPages.pages" :key="page.id">
          <label class="check">
            <input
              type="checkbox"
              :checked="menuPageSelection.includes(page.id)"
              @change="toggleMenuPage(page.id)"
            />
            <span>{{ page.resource_name }}</span>
            <code class="muted">{{ page.resource_code }}</code>
          </label>
        </li>
      </ul>
      <PermissionButton code="permission:resource-edit" :loading="pageLoading" @click="saveMenuPages">
        保存
      </PermissionButton>
      <button class="btn" type="button" @click="menuPages = null">关闭</button>
    </div>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除资源"
      danger
      :confirm-text="deleting ? '删除中…' : '确认删除'"
      :loading="deleting"
      :description="`删除编码 ${pendingDelete?.resource_code ?? ''} 会同时移除所有角色对该资源的授权。已有用户会立即失去对应的页面 / 按钮权限。`"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    />
  </PageContainer>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.tree,
.sub-panel {
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.tree {
  padding: 6px 0;
}

.tree__row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--vctn-border);
}

.tree__row:last-child {
  border-bottom: none;
}

.tree__name {
  font-weight: 500;
}

.tree__code {
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.tree__actions,
.row-actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.editor,
.sub-panel {
  margin-top: 12px;
  padding: 14px;
}

.editor {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.editor__title {
  width: 100%;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.editor__actions {
  display: flex;
  gap: 8px;
}

.sub-panel__title {
  font-size: 15px;
  margin-bottom: 4px;
}

.sub-list {
  list-style: none;
  margin: 8px 0 12px;
  padding: 0;
  max-height: 240px;
  overflow: auto;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  cursor: pointer;
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
