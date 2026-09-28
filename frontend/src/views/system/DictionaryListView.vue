<script setup lang="ts">
/**
 * 字典与字典项（FE-07 / `08 §9`，INTERIM-7-01/02）。
 *
 * 字典与系统参数是两套东西：字典是**枚举展示源**（业务页面用它渲染下拉，
 * 不在各页面硬编码字面量），参数是**运行期配置**（决定系统行为）。
 * 两者不共用存储也不共用页面语义。
 *
 * 软删除感知的唯一性（同一字典下 item_code 至多一个启用项）由库层
 * partial unique index 保证，前端**不重复实现** —— 那属于后端不变量。
 * 前端只做友好提示：把后端 409 原样回显，不改写原因。
 */
import { formatDateTime } from '@/utils/format'
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import {
  AddOutline,
  BookOutline,
  CreateOutline,
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
import { useColumnSettings } from '@/composables/useColumnSettings'
import {
  createDictItem,
  createDictType,
  deleteDictItem,
  deleteDictType,
  listDictItems,
  listDictTypes,
  updateDictItem,
  updateDictType,
} from '@/api/endpoints/dictionaries'
import type { DataTableColumn } from '@/components/data/types'
import type { DictItem, DictItemCreateRequest, DictType, DictTypeDeleteResult } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()

const dataColumns: Array<DataTableColumn<DictType>> = [
  { key: 'dict_code', title: '字典编码' },
  { key: 'dict_name', title: '字典名称' },
  { key: 'description', title: '描述' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
  { key: 'created_at', title: '创建时间', width: '170px' },
  { key: 'updated_at', title: '更新时间', width: '170px' },
  { key: 'id', title: '字典 ID', width: '200px' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<DictType>('dictionaries', dataColumns)

interface TypeDraft {
  id: ID | null
  dict_code: string
  dict_name: string
  description: string
  status: 'ACTIVE' | 'DISABLED'
}

interface ItemDraft {
  id: ID | null
  item_label: string
  item_value: string
  item_code: string
  sort_order: number
  is_default: boolean
  description: string
  status: 'ACTIVE' | 'DISABLED'
}

const rows = ref<DictType[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)
const keyword = ref('')
const statusFilter = ref<'ACTIVE' | 'DISABLED' | null>(null)

function emptyTypeDraft(): TypeDraft {
  return { id: null, dict_code: '', dict_name: '', description: '', status: 'ACTIVE' }
}

function emptyItemDraft(): ItemDraft {
  return {
    id: null,
    item_label: '',
    item_value: '',
    item_code: '',
    sort_order: 0,
    is_default: false,
    description: '',
    status: 'ACTIVE',
  }
}

const typeDraft = ref<TypeDraft>(emptyTypeDraft())
const typeOpen = ref(false)
const savingType = ref(false)
const pendingDelete = ref<DictType | null>(null)
const deletingType = ref(false)
const deleteResult = ref<string | null>(null)

/** 展开的字典 → 其字典项。 */
const expandedDictId = ref<ID | null>(null)
const items = ref<DictItem[]>([])
const itemLoading = ref(false)
const itemDraft = ref<ItemDraft>(emptyItemDraft())
const itemOpen = ref(false)
const savingItem = ref(false)
const pendingDeleteItem = ref<DictItem | null>(null)
const deletingItem = ref(false)

const isEditingType = computed(() => typeDraft.value.id !== null)
const isEditingItem = computed(() => itemDraft.value.id !== null)

const typeError = computed<string | null>(() => {
  if (!typeOpen.value) return null
  if (typeDraft.value.dict_code.trim() === '') return '请填写字典编码'
  if (typeDraft.value.dict_name.trim() === '') return '请填写字典名称'
  return null
})

const itemError = computed<string | null>(() => {
  if (!itemOpen.value) return null
  if (itemDraft.value.item_code.trim() === '') return '请填写项编码'
  if (itemDraft.value.item_label.trim() === '') return '请填写标签'
  if (itemDraft.value.item_value.trim() === '') return '请填写值'
  return null
})

/** 当前展开的字典名，供字典项弹窗提示用。 */
const expandedDictName = computed<string>(
  () => rows.value.find((row) => row.id === expandedDictId.value)?.dict_name ?? '',
)

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listDictTypes({ pageNum: pageNum.value, pageSize: pageSize.value, keyword: keyword.value, status: statusFilter.value })
    rows.value = result.list
    total.value = result.total
    pageNum.value = result.pageNum
    pageSize.value = result.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '字典加载失败'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search(): void {
  pageNum.value = 1
  void load()
}

function resetFilters(): void {
  keyword.value = ''
  statusFilter.value = null
  pageNum.value = 1
  void load()
}

function onPageChange(next: { pageNum: number; pageSize: number }): void {
  pageNum.value = next.pageNum
  pageSize.value = next.pageSize
  void load()
}

// ---------------------------------------------------------------- 字典（类型）

function startCreateType(): void {
  typeDraft.value = emptyTypeDraft()
  typeOpen.value = true
}

function startEditType(row: DictType): void {
  typeDraft.value = {
    id: row.id,
    dict_code: row.dict_code,
    dict_name: row.dict_name,
    description: row.description ?? '',
    status: row.status,
  }
  typeOpen.value = true
}

async function saveType(): Promise<void> {
  if (typeError.value !== null) return
  const current = typeDraft.value
  savingType.value = true
  try {
    if (current.id === null) {
      await createDictType({
        dict_code: current.dict_code.trim(),
        dict_name: current.dict_name.trim(),
        description: current.description || null,
        status: current.status,
      })
    } else {
      await updateDictType(current.id, {
        dict_name: current.dict_name.trim(),
        description: current.description || null,
        status: current.status,
      })
    }
    typeOpen.value = false
    await load()
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    savingType.value = false
  }
}

async function confirmDeleteType(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deletingType.value = true
  try {
    const result: DictTypeDeleteResult = await deleteDictType(target.id)
    deleteResult.value = `已删除字典「${result.dict_code}」，连带逻辑删除 ${result.deleted_item_count} 个字典项`
    pendingDelete.value = null
    if (expandedDictId.value === target.id) expandedDictId.value = null
    await load()
  } catch (cause) {
    notice(cause, '删除失败')
  } finally {
    deletingType.value = false
  }
}

// ---------------------------------------------------------------- 字典项

async function toggleExpand(dict: DictType): Promise<void> {
  if (expandedDictId.value === dict.id) {
    expandedDictId.value = null
    items.value = []
    return
  }
  expandedDictId.value = dict.id
  await loadItems(dict.id)
}

async function loadItems(dictTypeId: ID): Promise<void> {
  itemLoading.value = true
  try {
    items.value = await listDictItems(dictTypeId)
  } catch (cause) {
    notice(cause, '字典项加载失败')
    items.value = []
  } finally {
    itemLoading.value = false
  }
}

function startCreateItem(): void {
  itemDraft.value = emptyItemDraft()
  // 新项排在最后：用当前最大排序值 +10，避免每次都要手填。
  const maxSort = items.value.reduce((max, item) => Math.max(max, item.sort_order), 0)
  itemDraft.value.sort_order = maxSort + 10
  itemOpen.value = true
}

function startEditItem(item: DictItem): void {
  itemDraft.value = {
    id: item.id,
    item_label: item.item_label,
    item_value: item.item_value,
    item_code: item.item_code,
    sort_order: item.sort_order,
    is_default: item.is_default,
    description: item.description ?? '',
    status: item.status,
  }
  itemOpen.value = true
}

async function saveItem(): Promise<void> {
  const dictTypeId = expandedDictId.value
  if (dictTypeId === null || itemError.value !== null) return
  const current = itemDraft.value
  savingItem.value = true
  try {
    const payload: DictItemCreateRequest = {
      item_label: current.item_label.trim(),
      item_value: current.item_value.trim(),
      item_code: current.item_code.trim(),
      sort_order: current.sort_order,
      is_default: current.is_default,
      description: current.description || null,
      status: current.status,
    }
    if (current.id === null) {
      await createDictItem(dictTypeId, payload)
    } else {
      await updateDictItem(dictTypeId, current.id, payload)
    }
    itemOpen.value = false
    await loadItems(dictTypeId)
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    savingItem.value = false
  }
}

async function confirmDeleteItem(): Promise<void> {
  const dictTypeId = expandedDictId.value
  const target = pendingDeleteItem.value
  if (dictTypeId === null || target === null) return
  deletingItem.value = true
  try {
    await deleteDictItem(dictTypeId, target.id)
    pendingDeleteItem.value = null
    await loadItems(dictTypeId)
  } catch (cause) {
    notice(cause, '删除失败')
  } finally {
    deletingItem.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageContainer
    title="数据字典"
    description="维护下拉选项这类枚举值。统一在这里维护，各业务页面的选项才不会有出入。"
    :icon="BookOutline"
  >
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">关键字</span>
        <input v-model="keyword" class="field__control" placeholder="编码或名称" />
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
      <PermissionButton code="dictionary:create" type="primary" @click="startCreateType">
        <NIcon :component="AddOutline" />
        新增字典
      </PermissionButton>
      <NButton size="small" :loading="loading" @click="load">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
      <span class="toolbar__end">
        <ColumnSettings
          :items="columnItems"
          :disabled="loading"
          @toggle="toggleColumn"
          @move="moveColumn"
          @reset="resetColumns"
        />
      </span>
    </div>

    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <DataTable
      v-else
      :columns="visibleColumns"
      :rows="rows"
      :loading="loading"
      :row-key="(row: DictType) => row.id"
      empty-text="没有符合条件的字典"
      actions-title="操作"
      actions-width="150px"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ formatDateTime(row.created_at) }}</span>
      </template>
      <template #cell-updated_at="{ row }">
        <span class="muted">{{ formatDateTime(row.updated_at) }}</span>
      </template>
      <template #cell-description="{ row }">
        <span
          class="clip"
          :class="row.description === null || row.description === '' ? 'muted' : ''"
          :title="row.description || undefined"
        >
          {{ row.description === null || row.description === '' ? '—' : row.description }}
        </span>
      </template>
      <template #cell-id="{ row }">
        <code class="muted">{{ row.id }}</code>
      </template>
      <template #cell-dict_code="{ row }">
        <div class="cell-actions">
          <code>{{ row.dict_code }}</code>
          <button class="link" type="button" @click="toggleExpand(row)">
            {{ expandedDictId === row.id ? '收起字典项' : '展开字典项' }}
          </button>
        </div>
      </template>

      <template #actions="{ row }">
        <span class="table-actions">
          <PermissionButton code="dictionary:update" type="text-primary" @click="startEditType(row)">
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton code="dictionary:delete" type="text-danger" @click="pendingDelete = row">
            <NIcon :component="TrashOutline" />
            删除
          </PermissionButton>
        </span>
      </template>
    </DataTable>

    <Pagination
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      :disabled="loading"
      @change="onPageChange"
    />

    <div v-if="expandedDictId !== null" class="sub-panel">
      <h3 class="sub-panel__title">
        <span>字典项 — {{ expandedDictName }}</span>
        <PermissionButton code="dictionary:item-create" type="primary" @click="startCreateItem">
          <NIcon :component="AddOutline" />
          新增字典项
        </PermissionButton>
      </h3>

      <div v-if="itemLoading" class="state"><span class="spinner" aria-hidden="true" /><span>加载中…</span></div>
      <table v-else class="mini-table">
        <thead>
          <tr>
            <th>标签</th>
            <th>值</th>
            <th>项编码</th>
            <th>排序</th>
            <th>默认</th>
            <th>状态</th>
            <!-- 描述与时间戳后端一直返回，此前没渲染：一个字典项"为什么是
                 这个值"往往就写在描述里。`dict_type_id` 刻意不列 —— 它就是
                 面板标题里那个字典的 ID，每行都一样，列出来只是噪音。 -->
            <th>描述</th>
            <th>创建时间</th>
            <th>更新时间</th>
            <th>项 ID</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>{{ item.item_label }}</td>
            <td><code>{{ item.item_value }}</code></td>
            <td>{{ item.item_code }}</td>
            <td>{{ item.sort_order }}</td>
            <td>
              <span class="tag" :class="item.is_default ? 'tag--active' : ''">{{ item.is_default ? '默认' : '' }}</span>
            </td>
            <td>
              <span class="tag" :class="item.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
                {{ item.status === 'ACTIVE' ? '启用' : '禁用' }}
              </span>
            </td>
            <td>
              <span :class="item.description === null || item.description === '' ? 'muted' : ''">
                {{ item.description === null || item.description === '' ? '—' : item.description }}
              </span>
            </td>
            <td class="nowrap"><span class="muted">{{ formatDateTime(item.created_at) }}</span></td>
            <td class="nowrap"><span class="muted">{{ formatDateTime(item.updated_at) }}</span></td>
            <td><code class="muted">{{ item.id }}</code></td>
            <td>
              <span class="table-actions">
                <PermissionButton code="dictionary:item-update" type="text-primary" @click="startEditItem(item)">编辑</PermissionButton>
                <PermissionButton code="dictionary:item-delete" type="text-danger" @click="pendingDeleteItem = item">删除</PermissionButton>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="items.length === 0" class="muted">该字典下还没有字典项</p>
    </div>

    <p v-if="deleteResult !== null" class="muted">{{ deleteResult }}</p>

    <FormDialog
      :open="typeOpen"
      :title="isEditingType ? '编辑字典' : '新增字典'"
      :loading="savingType"
      :error="typeError"
      @cancel="typeOpen = false"
      @submit="saveType"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">字典编码</span>
          <input v-model.trim="typeDraft.dict_code" class="field__control" :disabled="isEditingType" placeholder="如 user_status" />
        </label>
        <label class="field">
          <span class="field__label">字典名称</span>
          <input v-model.trim="typeDraft.dict_name" class="field__control" placeholder="如 用户状态" />
        </label>
        <label class="field">
          <span class="field__label">状态</span>
          <select v-model="typeDraft.status" class="field__control">
            <option value="ACTIVE">启用</option>
            <option value="DISABLED">禁用</option>
          </select>
        </label>
        <label class="field field--full">
          <span class="field__label">描述</span>
          <input v-model.trim="typeDraft.description" class="field__control" placeholder="选填" />
        </label>
      </div>
      <p class="hint">
        <template v-if="isEditingType">字典编码是业务读取用的标识，创建后不可修改。</template>
        <template v-else>创建后可在列表里「展开字典项」逐条维护选项。</template>
      </p>
    </FormDialog>

    <FormDialog
      :open="itemOpen"
      :title="isEditingItem ? '编辑字典项' : '新增字典项'"
      :loading="savingItem"
      :error="itemError"
      :width="620"
      @cancel="itemOpen = false"
      @submit="saveItem"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">标签</span>
          <input v-model.trim="itemDraft.item_label" class="field__control" placeholder="界面显示的文字" />
        </label>
        <label class="field">
          <span class="field__label">值</span>
          <input v-model.trim="itemDraft.item_value" class="field__control" placeholder="实际存储的值" />
        </label>
        <label class="field">
          <span class="field__label">项编码</span>
          <input v-model.trim="itemDraft.item_code" class="field__control" />
        </label>
        <label class="field">
          <span class="field__label">排序</span>
          <input v-model.number="itemDraft.sort_order" class="field__control" type="number" />
        </label>
        <label class="field">
          <span class="field__label">状态</span>
          <select v-model="itemDraft.status" class="field__control">
            <option value="ACTIVE">启用</option>
            <option value="DISABLED">禁用</option>
          </select>
        </label>
        <label class="field field--full">
          <span class="field__label">描述</span>
          <input v-model.trim="itemDraft.description" class="field__control" placeholder="选填" />
        </label>
      </div>

      <label class="check">
        <input v-model="itemDraft.is_default" type="checkbox" />
        <span>设为该字典的默认项</span>
      </label>
      <p class="hint">同一字典下只能有一个默认项；设为默认时，原默认项会被自动取消。</p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除字典"
      danger
      :confirm-text="deletingType ? '删除中…' : '确认删除'"
      :loading="deletingType"
      :description="`删除字典会连带删除其下全部字典项。字典编码 ${pendingDelete?.dict_code ?? ''} 如已被业务引用，对应取值会回退为空。`"
      @cancel="pendingDelete = null"
      @confirm="confirmDeleteType"
    />

    <ConfirmDialog
      :open="pendingDeleteItem !== null"
      title="删除字典项"
      danger
      :confirm-text="deletingItem ? '删除中…' : '确认删除'"
      :loading="deletingItem"
      :description="`删除后引用该值的下拉会回落为空值。字典项 ${pendingDeleteItem?.item_code ?? ''}。`"
      @cancel="pendingDeleteItem = null"
      @confirm="confirmDeleteItem"
    />
  </PageContainer>
</template>

<style scoped>
.cell-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
