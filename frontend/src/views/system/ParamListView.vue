<script setup lang="ts">
/**
 * 系统参数（FE-07 / `08 §9`）。
 *
 * 与字典是两套东西：字典是枚举展示源，参数是运行期配置（决定系统行为）。
 *
 * 安全约定：**审计不记录参数值**。参数可能承载密钥类配置，而审计
 * append-only 保留 2 年 —— 一旦页面上能"看历史值"，就是不可撤回的泄漏通道。
 * 因此这里没有"查看变更历史"的入口，只展示当前生效值。
 *
 * `clear_value` 与 `param_value` 互斥：点"清空"只提交 `clear_value: true`，
 * 不夹带值（后端会拒绝两者同时出现）。
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
  createSystemParam,
  deleteSystemParam,
  listSystemParams,
  updateSystemParam,
} from '@/api/endpoints/params'
import type { DataTableColumn } from '@/components/data/types'
import type { SystemParam } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()

const columns: Array<DataTableColumn<SystemParam>> = [
  { key: 'param_key', title: '参数键' },
  { key: 'param_name', title: '参数名' },
  { key: 'param_type', title: '类型', width: '90px' },
  { key: 'effective_value', title: '当前生效值' },
  { key: 'default_value', title: '默认值' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
]

const PARAM_TYPES = ['STRING', 'INT', 'BOOL']

interface ParamDraft {
  id: ID | null
  param_key: string
  param_name: string
  param_type: 'STRING' | 'INT' | 'BOOL'
  default_value: string
  param_value: string
  description: string
  status: 'ACTIVE' | 'DISABLED'
}

const rows = ref<SystemParam[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

const keyword = ref('')
const statusFilter = ref<'ACTIVE' | 'DISABLED' | null>(null)

const draft = ref<ParamDraft | null>(null)
const saving = ref(false)
/** 单独的"清空值"动作：与编辑分开，避免两者互相覆盖语义。 */
const clearing = ref(false)
const pendingDelete = ref<SystemParam | null>(null)
const deleting = ref(false)

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listSystemParams({ pageNum: pageNum.value, pageSize: pageSize.value, keyword: keyword.value, status: statusFilter.value })
    rows.value = result.list
    total.value = result.total
    pageNum.value = result.pageNum
    pageSize.value = result.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '参数加载失败'
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

function startCreate(): void {
  draft.value = {
    id: null,
    param_key: '',
    param_name: '',
    param_type: 'STRING',
    default_value: '',
    param_value: '',
    description: '',
    status: 'ACTIVE',
  }
}

function startEdit(param: SystemParam): void {
  draft.value = {
    id: param.id,
    param_key: param.param_key,
    param_name: param.param_name,
    param_type: param.param_type,
    default_value: param.default_value,
    param_value: param.param_value ?? '',
    description: param.description ?? '',
    status: param.status,
  }
}

async function save(): Promise<void> {
  const current = draft.value
  if (current === null) return
  saving.value = true
  try {
    if (current.id === null) {
      await createSystemParam({
        param_key: current.param_key,
        param_name: current.param_name,
        param_type: current.param_type,
        default_value: current.default_value,
        param_value: current.param_value || null,
        description: current.description || null,
        status: current.status,
      })
    } else {
      await updateSystemParam(current.id, {
        param_name: current.param_name,
        description: current.description || null,
        status: current.status,
        param_value: current.param_value || null,
        clear_value: false,
      })
    }
    draft.value = null
    await load()
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    saving.value = false
  }
}

/** 独立动作：清空当前值 → 回落到默认值。 */
async function clearValue(): Promise<void> {
  const current = draft.value
  if (current === null || current.id === null) return
  clearing.value = true
  try {
    await updateSystemParam(current.id, {
      clear_value: true,
      param_name: current.param_name,
      status: current.status,
      description: current.description || null,
    })
    draft.value = null
    await load()
  } catch (cause) {
    notice(cause, '清空失败')
  } finally {
    clearing.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deleting.value = true
  try {
    await deleteSystemParam(target.id)
    pendingDelete.value = null
    await load()
  } catch (cause) {
    notice(cause, '删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageContainer title="系统参数" description="参数是运行期配置。生效值为当前值，缺失时回退默认值；审计不记录参数值，因此这里没有历史视图。">
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">关键字</span>
        <input v-model="keyword" class="field__control" placeholder="键或名称" />
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
      <PermissionButton code="param:create" type="primary" @click="startCreate">新增参数</PermissionButton>
      <span class="muted">参数键变更等价于换一个开关，历史审计仍会记录"改了哪个键"</span>
    </div>

    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <DataTable
      v-else
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :row-key="(row: SystemParam) => row.id"
      empty-text="没有符合条件的参数"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-effective_value="{ row }">
        <div class="cell">
          <code>{{ row.effective_value }}</code>
          <div v-if="row.param_value === null" class="muted">取自默认值</div>
        </div>
      </template>
      <template #cell-param_key="{ row }">
        <div class="cell">
          <PermissionButton code="param:edit" type="text" @click="startEdit(row)">编辑</PermissionButton>
          <PermissionButton code="param:delete" type="text" @click="pendingDelete = row">删除</PermissionButton>
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

    <div v-if="draft !== null" class="editor">
      <h3 class="editor__title">{{ draft.id === null ? '新增参数' : `编辑：${draft.param_key}` }}</h3>

      <label class="field">
        <span class="field__label">参数键</span>
        <input v-model="draft.param_key" class="field__control" :disabled="draft.id !== null" />
      </label>
      <label class="field">
        <span class="field__label">参数名</span>
        <input v-model="draft.param_name" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">类型</span>
        <select v-model="draft.param_type" class="field__control" :disabled="draft.id !== null">
          <option v-for="type in PARAM_TYPES" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">默认值</span>
        <input v-model="draft.default_value" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">当前值（留空表示用默认值）</span>
        <input v-model="draft.param_value" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">描述</span>
        <input v-model="draft.description" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">状态</span>
        <select v-model="draft.status" class="field__control">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>

      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="saving" @click="save">保存</button>
        <PermissionButton
          v-if="draft.id !== null"
          code="param:edit"
          :loading="clearing"
          @click="clearValue"
        >
          清空当前值
        </PermissionButton>
        <button class="btn" type="button" :disabled="saving" @click="draft = null">取消</button>
      </div>
      <p v-if="clearing" class="hint">
        "清空当前值"会让参数回落到默认值；它与"保存"是两次独立提交，`clear_value` 与 `param_value` 不能同时给出。
      </p>
    </div>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除参数"
      danger
      :confirm-text="deleting ? '删除中…' : '确认删除'"
      :loading="deleting"
      :description="`删除后该参数回落到未配置状态，相关行为按后端默认处理。参数键：${pendingDelete?.param_key ?? ''}。`"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    />
  </PageContainer>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.cell {
  display: flex;
  flex-direction: column;
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

.hint {
  width: 100%;
  margin: 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
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
