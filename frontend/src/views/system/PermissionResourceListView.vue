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
 * 树形的两种范围，别搞混：
 * - **类型 = 全部** → 不传 `resourceType`，后端返回五类**合成**的完整树。
 *   必须这样：父子规则是跨类型的（`BUTTON` / `API` 的父是 `PAGE`），
 *   按单类型取会让这些子节点因为"父不在同一批数据里"被提升为根。
 *   （曾有一次"类型没选就 400"的契约，已在后端作废；这里记一笔免得又被"修"回去。）
 * - **类型 = 某个值** → 后端只返回该类型，**跨类型的子资源必然缺席**。
 *   这是该模式的固有语义，不是缺陷，所以界面上会明说一句。
 *
 * 关键字与状态筛选在两种范围下都会生效，且保留命中节点的祖先
 * （否则"搜一个按钮"会得到一排没有归属的按钮）。
 *
 * 树形不做递归组件：模板不能自引用，用一个自定义递归组件反而更难测。
 * 这里先把树压平成带层级的行列表再渲染，与部门页同一套做法。
 *
 * **折叠**（2026-09-28 补）：压平必须带上"哪些节点处于展开态"，否则只是把树
 * 摊成一张不能收的长表 —— 真实数据 16 根 / 65 节点，一屏根本铺不下，而
 * 授权树与部门树都能收，只有这一页不能，是明显的遗漏。口径统一为
 * 「`expanded: Set<ID>` + 默认全展开 + 展开全部/收起全部」，见 `expanded` 的注释。
 */
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import {
  AddOutline,
  AlbumsOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CreateOutline,
  GitBranchOutline,
  RefreshOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
import { useAppStore } from '@/stores/app'
import { formatDateTime } from '@/utils/format'
import { useColumnSettings } from '@/composables/useColumnSettings'
import { useResourcesStore } from '@/stores/resources'
import {
  getMenuPages,
  getResourceTree,
  setMenuPages,
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
const resourcesStore = useResourcesStore()

const dataColumns: Array<DataTableColumn<PermissionResource>> = [
  { key: 'resource_name', title: '名称' },
  { key: 'resource_code', title: '编码' },
  { key: 'resource_type', title: '类型', width: '90px' },
  // 「路由 / 路径」把 route_path / component_path / api_method / api_path /
  // field_key 压在一格里（它们互斥，一个资源只会命中其中一两个）。
  // 但**父子关系**与**排序值**此前完全没露出来 —— 而"这个按钮挂在哪个页面下"
  // 正是权限排查时最常问的一句。
  { key: 'parent_id', title: '所属资源', width: '200px' },
  { key: 'owner_resource_id', title: '字段归属', width: '200px' },
  { key: 'route_path', title: '路由 / 路径' },
  { key: 'icon', title: '图标', width: '120px' },
  { key: 'sort_order', title: '排序', width: '80px', align: 'right' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
  { key: 'created_at', title: '创建时间', width: '170px' },
  { key: 'updated_at', title: '更新时间', width: '170px' },
  { key: 'id', title: '资源 ID', width: '200px' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<PermissionResource>('permission-resources', dataColumns)

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
  hasChildren: boolean
}

function emptyDraft(kind: ResourceType): ResourceDraft {
  return {
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

/** 筛选输入留在页面里（受控于 SearchForm），筛选结果归 store。 */
const keyword = ref('')
const kindFilter = ref<'' | ResourceType>('')
const statusFilter = ref<'' | 'ACTIVE' | 'DISABLED'>('')

const mode = ref<'list' | 'tree'>('list')
const treeNodes = ref<PermissionResourceTreeNode[]>([])

/**
 * 处于**展开**态的节点 ID 集合（默认全展开，语义与部门页一致）。
 *
 * 为什么是「展开集合」而不是「折叠集合」：全类型树在真实数据下是 16 个根、
 * 65 个节点、深度 2 —— 一屏铺不下，用户第一眼要看的恰恰是层级本身。
 * 用展开集合时只需一个 `expandAll()` 就能表达"补全到全展开"，
 * 而"收某个分支"是一次删元素，两种操作都不会出现"集合里留着已消失节点的键"
 * 这种说不清的状态。
 */
const expanded = ref<Set<ID>>(new Set())

const draft = ref<ResourceDraft>(emptyDraft('PAGE'))
const draftOpen = ref(false)
const saving = ref(false)
const pendingDelete = ref<PermissionResource | null>(null)
const deleting = ref(false)

const isEditing = computed(() => draft.value.id !== null)

const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  if (draft.value.resource_code.trim() === '') return '请填写资源编码'
  if (draft.value.resource_name.trim() === '') return '请填写资源名称'
  if (draft.value.resource_type === 'PAGE' || draft.value.resource_type === 'MENU') {
    if (draft.value.route_path.trim() === '') return 'PAGE / MENU 必须填写路由路径'
    if (draft.value.component_path.trim() === '') return 'PAGE / MENU 必须填写组件路径'
  }
  if (draft.value.resource_type === 'API' && draft.value.api_path.trim() === '') return 'API 必须填写接口路径'
  if (draft.value.resource_type === 'FIELD' && draft.value.field_key.trim() === '') return 'FIELD 必须填写字段键'
  return null
})

/** 菜单 → 页面 的子表。只有 MENU 类型才有意义。 */
const menuPages = ref<{ menu_id: ID; pages: PermissionResource[] } | null>(null)
const menuPageSelection = ref<ID[]>([])
const pageLoading = ref(false)

/** 菜单弹窗的标题要显示**菜单名**，不是雪花 ID。 */
const menuPageMenu = computed<PermissionResource | null>(() => {
  const id = menuPages.value?.menu_id
  if (id === undefined) return null
  return (
    resourcesStore.rows.find((row) => row.id === id) ??
    treeNodes.value.map((entry) => entry.resource).find((resource) => resource.id === id) ??
    null
  )
})

/**
 * 压平成带层级的行列表。
 *
 * ⚠️ 从前这里是**无条件递归**：不管有多少层都全铺出来，只靠缩进表达层级 ——
 * 于是"树"其实是一张不能收的长表（真实数据 65 行）。现在子节点只在
 * 父节点处于展开态时才进入结果，与部门页同一口径。
 *
 * `hasChildren` 由扁平化时一并算出，模板只消费不判断。它与
 * `entry.node.children.length > 0` 等价，但把它放在这里有两个好处：
 * 「什么算可折叠」只有一处定义（将来若改成"根节点也能收"，只需改这里），
 * 以及模板不必为每一行重复计算同一个表达式。
 */
const flatTree = computed<FlatTreeNode[]>(() => {
  const out: FlatTreeNode[] = []
  const walk = (nodes: PermissionResourceTreeNode[], depth: number): void => {
    for (const node of nodes) {
      out.push({ node, depth, hasChildren: node.children.length > 0 })
      if (node.children.length > 0 && expanded.value.has(node.resource.id)) {
        walk(node.children, depth + 1)
      }
    }
  }
  walk(treeNodes.value, 0)
  return out
})

/** 树里全部节点的 ID（`expandAll` 用；`flatTree` 是**裁剪后**的，不能拿来补全）。 */
function allNodeIds(nodes: PermissionResourceTreeNode[]): ID[] {
  return nodes.flatMap((node) => [node.resource.id, ...allNodeIds(node.children)])
}

function expandAll(): void {
  expanded.value = new Set(allNodeIds(treeNodes.value))
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

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

/** 分页列表由 store 持有；树是这一页独有的视图形态，留在页面里。 */
function load(): Promise<void> {
  return resourcesStore.load()
}

/** 树的加载态与错误信息归 store：它和分页列表共用那两个字段，避免两份。 */
async function loadTree(): Promise<void> {
  resourcesStore.loading = true
  resourcesStore.error = null
  try {
    treeNodes.value = await getResourceTree({
      resourceType: kindFilter.value === '' ? null : kindFilter.value,
      status: statusFilter.value === '' ? null : (statusFilter.value as PermissionStatus),
      keyword: keyword.value,
    })
    // 树换了就重新展开（与部门页同一理由，但这里更硬）：筛选会**换掉整棵树**，
    // 若沿用上一次的展开集合，新树的分支没有一个是"展开"的 —— 用户搜到一个按钮，
    // 界面上却只见一排收起的根，命中节点藏在里面看不见，看起来就像"搜索坏了"。
    expandAll()
  } catch (cause) {
    resourcesStore.error = cause instanceof Error ? cause.message : '资源树加载失败'
    treeNodes.value = []
  } finally {
    resourcesStore.loading = false
  }
}

async function search(): Promise<void> {
  await resourcesStore.setFilters({
    keyword: keyword.value,
    kind: kindFilter.value === '' ? null : kindFilter.value,
    status: statusFilter.value === '' ? null : (statusFilter.value as PermissionStatus),
  })
  if (mode.value === 'tree') await loadTree()
}

async function resetFilters(): Promise<void> {
  keyword.value = ''
  kindFilter.value = ''
  statusFilter.value = ''
  await search()
}

/** 用命名函数而不是模板内联箭头：内联里同时读写 ref 容易踩类型推断。 */
function onPageChange(next: { pageNum: number; pageSize: number }): void {
  void resourcesStore.goToPage(next.pageNum, next.pageSize)
}

async function switchMode(next: 'list' | 'tree'): Promise<void> {
  mode.value = next
  if (next === 'list') await load()
  else await loadTree()
}

function startCreate(kind: ResourceType): void {
  draft.value = emptyDraft(kind)
  draftOpen.value = true
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
  draftOpen.value = true
}

async function submit(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  saving.value = true
  try {
    if (current.id === null) {
      await resourcesStore.create({
        resource_type: current.resource_type,
        resource_code: current.resource_code.trim(),
        resource_name: current.resource_name.trim(),
        route_path: current.route_path.trim() || null,
        component_path: current.component_path.trim() || null,
        api_method: current.api_method.trim() || null,
        api_path: current.api_path.trim() || null,
        field_key: current.field_key.trim() || null,
      })
    } else {
      await resourcesStore.update(current.id, {
        resource_name: current.resource_name.trim(),
        route_path: current.route_path.trim() || null,
        component_path: current.component_path.trim() || null,
        api_method: current.api_method.trim() || null,
        api_path: current.api_path.trim() || null,
        field_key: current.field_key.trim() || null,
      })
    }
    draftOpen.value = false
    // 列表 / 树由 store 负责失效后重拉，这里只还原编辑区。
    if (mode.value === 'tree') await loadTree()
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deleting.value = true
  try {
    await resourcesStore.remove(target.id)
    pendingDelete.value = null
    if (mode.value === 'tree') await loadTree()
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
    // 菜单挂的页面变了，列表里的 MENU 行要跟着变。
    await load()
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
  <PageContainer
    title="权限资源"
    description="定义可被授权的对象：页面、菜单、按钮、接口与字段。这里的编码就是授权时使用的标识。"
    :icon="AlbumsOutline"
  >
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
      <NButton size="small" :type="mode === 'list' ? 'primary' : 'default'" @click="switchMode('list')">
        列表
      </NButton>
      <NButton size="small" :type="mode === 'tree' ? 'primary' : 'default'" @click="switchMode('tree')">
        树形
      </NButton>
      <!-- 展开 / 收起只在树形下有意义，切到列表还留着会让人以为点了没反应。 -->
      <template v-if="mode === 'tree'">
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
      </template>
      <PermissionButton
        v-for="kind in KINDS"
        :key="kind"
        code="permission:resource-create"
        @click="startCreate(kind)"
      >
        <NIcon :component="AddOutline" />
        新增 {{ kind }}
      </PermissionButton>
      <span class="toolbar__end">
        <NButton size="small" :loading="resourcesStore.loading" @click="mode === 'tree' ? loadTree() : load()">
          <template #icon>
            <NIcon :component="RefreshOutline" />
          </template>
          刷新
        </NButton>
        <ColumnSettings
          v-if="mode === 'list'"
          :items="columnItems"
          :disabled="resourcesStore.loading"
          @toggle="toggleColumn"
          @move="moveColumn"
          @reset="resetColumns"
        />
      </span>
    </div>

    <div v-if="resourcesStore.error" class="alert alert--error">{{ resourcesStore.error }}</div>

    <div v-else-if="resourcesStore.loading" class="state"><span class="spinner" aria-hidden="true" /><span>加载中…</span></div>

    <template v-else-if="mode === 'list'">
      <DataTable
        :columns="visibleColumns"
        :rows="resourcesStore.rows"
        :row-key="(row: PermissionResource) => row.id"
        empty-text="没有符合条件的资源"
        actions-title="操作"
        actions-width="230px"
      >
        <template #cell-status="{ row }">
          <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
            {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
          </span>
        </template>
        <template #cell-resource_code="{ row }">
          <code>{{ row.resource_code }}</code>
        </template>
        <template #cell-route_path="{ row }">
          <div>{{ row.route_path ?? row.api_path ?? '—' }}</div>
          <div v-if="row.component_path" class="muted">{{ row.component_path }}</div>
          <div v-if="row.api_method" class="muted">{{ row.api_method }}</div>
          <div v-if="row.field_key" class="muted">{{ row.field_key }}</div>
        </template>
        <template #cell-parent_id="{ row }">
          <code v-if="row.parent_id !== null" class="muted">{{ row.parent_id }}</code>
          <span v-else class="muted">—</span>
        </template>
        <template #cell-owner_resource_id="{ row }">
          <code v-if="row.owner_resource_id !== null" class="muted">{{ row.owner_resource_id }}</code>
          <span v-else class="muted">—</span>
        </template>
        <template #cell-icon="{ row }">
          <code v-if="row.icon !== null && row.icon !== ''">{{ row.icon }}</code>
          <span v-else class="muted">—</span>
        </template>
        <template #cell-created_at="{ row }">
          <span class="muted">{{ formatDateTime(row.created_at) }}</span>
        </template>
        <template #cell-updated_at="{ row }">
          <span class="muted">{{ formatDateTime(row.updated_at) }}</span>
        </template>
        <template #cell-id="{ row }">
          <code class="muted">{{ row.id }}</code>
        </template>

        <template #actions="{ row }">
          <span class="table-actions">
            <PermissionButton code="permission:resource-update" type="text-primary" @click="startEdit(row)">
              <NIcon :component="CreateOutline" />
              编辑
            </PermissionButton>
            <PermissionButton
              v-if="row.resource_type === 'MENU'"
              code="permission:resource-update"
              type="text-primary"
              @click="openMenuPages(row)"
            >
              <NIcon :component="GitBranchOutline" />
              挂载页面
            </PermissionButton>
            <PermissionButton code="permission:resource-delete" type="text-danger" @click="pendingDelete = row">
              <NIcon :component="TrashOutline" />
              删除
            </PermissionButton>
          </span>
        </template>
      </DataTable>

      <Pagination
        :total="resourcesStore.total"
        :page-num="resourcesStore.pageNum"
        :page-size="resourcesStore.pageSize"
        :disabled="resourcesStore.loading"
        @change="onPageChange"
      />
    </template>

    <div v-else class="tree">
      <p v-if="kindFilter !== ''" class="hint">
        已按类型筛选：树里只有 {{ kindFilter }} 资源。挂在其他类型下的子资源
        （按钮 / 接口挂在页面下）不会出现 —— 把「类型」清成「全部」才能看到完整层级。
      </p>
      <div
        v-for="entry in flatTree"
        :key="entry.node.resource.id"
        class="tree__row"
        :style="{ paddingLeft: `${entry.depth * 20 + 12}px` }"
      >
        <!-- 叶子用等宽占位而不是不渲染：否则同一层里"有子节点"和"没子节点"的
             名称会错开 20px，缩进就不再表示层级了。 -->
        <button
          v-if="entry.hasChildren"
          class="tree__twisty"
          type="button"
          :aria-expanded="expanded.has(entry.node.resource.id)"
          :aria-label="`${expanded.has(entry.node.resource.id) ? '收起' : '展开'} ${entry.node.resource.resource_name}`"
          @click="toggleExpand(entry.node.resource.id)"
        >
          {{ expanded.has(entry.node.resource.id) ? '−' : '+' }}
        </button>
        <span v-else class="tree__twisty tree__twisty--leaf" aria-hidden="true" />

        <span class="tree__name">{{ entry.node.resource.resource_name }}</span>
        <code class="tree__code">{{ entry.node.resource.resource_code }}</code>
        <span class="tag">{{ entry.node.resource.resource_type }}</span>
        <span class="tag" :class="entry.node.resource.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ entry.node.resource.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
        <span class="tree__actions">
          <PermissionButton code="permission:resource-update" type="text-primary" @click="startEdit(entry.node.resource)">
            编辑
          </PermissionButton>
          <PermissionButton
            v-if="entry.node.resource.resource_type === 'MENU'"
            code="permission:resource-update"
            type="text-primary"
            @click="openMenuPages(entry.node.resource)"
          >
            挂载页面
          </PermissionButton>
          <PermissionButton
            code="permission:resource-delete"
            type="text-danger"
            @click="pendingDelete = entry.node.resource"
          >
            删除
          </PermissionButton>
        </span>
      </div>
      <!-- 判"有没有资源"要看 treeNodes，不能看 flatTree：
           后者是**裁剪后**的可见行，将来若允许收起根节点，它会先变空，
           于是"树里有数据但被你自己收起来了"会被误报成"没有符合条件的资源"。 -->
      <p v-if="treeNodes.length === 0" class="state__item">没有符合条件的资源</p>
    </div>

    <!-- 新增 / 编辑资源 -->
    <FormDialog
      :open="draftOpen"
      :title="isEditing ? '编辑资源' : `新增 ${draft.resource_type}`"
      :loading="saving"
      :error="draftError"
      :width="640"
      @cancel="draftOpen = false"
      @submit="submit"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">资源编码</span>
          <input
            v-model.trim="draft.resource_code"
            class="field__control"
            :disabled="isEditing"
            placeholder="如 system:user:page"
          />
        </label>
        <label class="field">
          <span class="field__label">资源名称</span>
          <input v-model.trim="draft.resource_name" class="field__control" placeholder="如 用户管理" />
        </label>

        <template v-if="draft.resource_type === 'PAGE' || draft.resource_type === 'MENU'">
          <label class="field">
            <span class="field__label">路由路径</span>
            <input v-model.trim="draft.route_path" class="field__control" placeholder="/system/users" />
          </label>
          <label class="field">
            <span class="field__label">组件路径</span>
            <input v-model.trim="draft.component_path" class="field__control" placeholder="system/user" />
          </label>
        </template>

        <template v-if="draft.resource_type === 'API'">
          <label class="field">
            <span class="field__label">请求方法</span>
            <input v-model.trim="draft.api_method" class="field__control" placeholder="GET" />
          </label>
          <label class="field">
            <span class="field__label">接口路径</span>
            <input v-model.trim="draft.api_path" class="field__control" placeholder="/users" />
          </label>
        </template>

        <template v-if="draft.resource_type === 'FIELD'">
          <label class="field field--full">
            <span class="field__label">字段键</span>
            <input v-model.trim="draft.field_key" class="field__control" placeholder="field:user.phone" />
          </label>
        </template>
      </div>

      <p class="hint">
        <template v-if="isEditing">资源编码是授权时使用的标识，创建后不可修改。</template>
        <template v-else-if="draft.resource_type === 'PAGE' || draft.resource_type === 'MENU'">
          组件路径要能对应到前端已有的页面组件，写错会导致该页面点进去打不开。
        </template>
        <template v-else-if="draft.resource_type === 'API'">
          接口路径按实际路由填写，不含 /api/v1 前缀（例如 /users）。
        </template>
        <template v-else>新建后可在「权限配置」页把它授权给角色。</template>
      </p>
    </FormDialog>

    <!-- 菜单挂载页面 -->
    <FormDialog
      :open="menuPages !== null"
      :title="`挂载页面 — ${menuPageMenu?.resource_name ?? ''}`"
      :loading="pageLoading"
      confirm-text="保存挂载"
      @cancel="menuPages = null"
      @submit="saveMenuPages"
    >
      <p class="muted">勾选该菜单下出现的页面。未勾选的页面不会出现在菜单的路由目标里。</p>
      <ul class="sub-list">
        <li v-for="page in menuPages?.pages ?? []" :key="page.id">
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
      <p v-if="(menuPages?.pages ?? []).length === 0" class="muted">没有可挂载的页面</p>
    </FormDialog>

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

<!-- 本页所有样式已上升为 base.css 的共享类（tree / editor / sub-panel /
     check / alert）。这里不再保留 scoped 定义：scoped 的属性选择器优先级
     更高，留着会盖掉统一版本，等于没统一。 -->
