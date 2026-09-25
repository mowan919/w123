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
import { onMounted, ref } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
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

const columns: Array<DataTableColumn<DictType>> = [
  { key: 'dict_code', title: '字典编码' },
  { key: 'dict_name', title: '字典名称' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
  { key: 'created_at', title: '创建时间', width: '170px' },
]

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

const typeDraft = ref<TypeDraft | null>(null)
const savingType = ref(false)
const pendingDelete = ref<DictType | null>(null)
const deletingType = ref(false)
const deleteResult = ref<string | null>(null)

/** 展开的字典 → 其字典项。 */
const expandedDictId = ref<ID | null>(null)
const items = ref<DictItem[]>([])
const itemLoading = ref(false)
const itemDraft = ref<ItemDraft | null>(null)
const savingItem = ref(false)
const pendingDeleteItem = ref<DictItem | null>(null)
const deletingItem = ref(false)

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

async function saveType(): Promise<void> {
  const current = typeDraft.value
  if (current === null) return
  savingType.value = true
  try {
    if (current.id === null) {
      await createDictType({
        dict_code: current.dict_code,
        dict_name: current.dict_name,
        description: current.description || null,
        status: current.status,
      })
    } else {
      await updateDictType(current.id, {
        dict_name: current.dict_name,
        description: current.description || null,
        status: current.status,
      })
    }
    typeDraft.value = null
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
  itemDraft.value = {
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
}

async function saveItem(): Promise<void> {
  const dictTypeId = expandedDictId.value
  const current = itemDraft.value
  if (dictTypeId === null || current === null) return
  savingItem.value = true
  try {
    const payload: DictItemCreateRequest = {
      item_label: current.item_label,
      item_value: current.item_value,
      item_code: current.item_code,
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
    itemDraft.value = null
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
  <PageContainer title="数据字典" description="字典是枚举展示源。业务页面统一从这里取选项，不在页面里硬编码字面量。">
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
      <PermissionButton code="dict:create" type="primary" @click="typeDraft = { id: null, dict_code: '', dict_name: '', description: '', status: 'ACTIVE' }">
        新增字典
      </PermissionButton>
    </div>

    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <DataTable
      v-else
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :row-key="(row: DictType) => row.id"
      empty-text="没有符合条件的字典"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ row.created_at }}</span>
      </template>
      <template #cell-dict_code="{ row }">
        <div class="cell-actions">
          <button class="link" type="button" @click="toggleExpand(row)">
            {{ expandedDictId === row.id ? '收起字典项' : '展开字典项' }}
          </button>
          <PermissionButton code="dict:edit" type="text" @click="typeDraft = { id: row.id, dict_code: row.dict_code, dict_name: row.dict_name, description: row.description ?? '', status: row.status }">
            编辑
          </PermissionButton>
          <PermissionButton code="dict:delete" type="text" @click="pendingDelete = row">
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

    <div v-if="expandedDictId !== null" class="sub-panel">
      <h3 class="sub-panel__title">字典项</h3>
      <PermissionButton code="dict:item-create" type="primary" @click="startCreateItem">新增字典项</PermissionButton>

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
              <PermissionButton code="dict:item-edit" type="text" @click="startEditItem(item)">编辑</PermissionButton>
              <PermissionButton code="dict:item-delete" type="text" @click="pendingDeleteItem = item">删除</PermissionButton>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="items.length === 0" class="muted">该字典下还没有字典项</p>
    </div>

    <div v-if="itemDraft !== null" class="editor">
      <h3 class="editor__title">{{ itemDraft.id === null ? '新增字典项' : '编辑字典项' }}</h3>
      <label class="field"><span class="field__label">标签</span><input v-model="itemDraft.item_label" class="field__control" /></label>
      <label class="field"><span class="field__label">值</span><input v-model="itemDraft.item_value" class="field__control" /></label>
      <label class="field"><span class="field__label">项编码</span><input v-model="itemDraft.item_code" class="field__control" /></label>
      <label class="field"><span class="field__label">排序</span><input v-model.number="itemDraft.sort_order" class="field__control" type="number" /></label>
      <label class="field"><span class="field__label">描述</span><input v-model="itemDraft.description" class="field__control" /></label>
      <label class="check"><input v-model="itemDraft.is_default" type="checkbox" /><span>设为该字典的默认项</span></label>
      <label class="field"><span class="field__label">状态</span>
        <select v-model="itemDraft.status" class="field__control">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>
      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="savingItem" @click="saveItem">保存</button>
        <button class="btn" type="button" :disabled="savingItem" @click="itemDraft = null">取消</button>
      </div>
    </div>

    <div v-if="typeDraft !== null" class="editor">
      <h3 class="editor__title">{{ typeDraft.id === null ? '新增字典' : '编辑字典' }}</h3>
      <label class="field">
        <span class="field__label">字典编码</span>
        <input v-model="typeDraft.dict_code" class="field__control" :disabled="typeDraft.id !== null" />
      </label>
      <label class="field"><span class="field__label">字典名称</span><input v-model="typeDraft.dict_name" class="field__control" /></label>
      <label class="field"><span class="field__label">描述</span><input v-model="typeDraft.description" class="field__control" /></label>
      <label class="field"><span class="field__label">状态</span>
        <select v-model="typeDraft.status" class="field__control">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>
      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="savingType" @click="saveType">保存</button>
        <button class="btn" type="button" :disabled="savingType" @click="typeDraft = null">取消</button>
      </div>
    </div>

    <p v-if="deleteResult !== null" class="muted">{{ deleteResult }}</p>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除字典"
      danger
      :confirm-text="deletingType ? '删除中…' : '确认删除'"
      :loading="deletingType"
      :description="`删除字典会连带逻辑删除其下全部字典项。字典编码 ${pendingDelete?.dict_code ?? ''} 如有业务已按该编码读取，取值将回退为空。`"
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
.toolbar {
  margin-bottom: 12px;
}

.cell-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.link {
  border: none;
  background: none;
  padding: 0;
  color: var(--vctn-primary);
  cursor: pointer;
  font: inherit;
}

.sub-panel,
.editor {
  margin-top: 12px;
  padding: 14px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.sub-panel__title,
.editor__title {
  font-size: 15px;
  margin-bottom: 10px;
}

.editor {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}

.editor__title {
  width: 100%;
}

.editor__actions {
  display: flex;
  gap: 8px;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
}

.mini-table th,
.mini-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--vctn-border);
  text-align: left;
  font-weight: 500;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
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
