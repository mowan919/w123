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
import { useParamsStore } from '@/stores/params'
import type { DataTableColumn } from '@/components/data/types'
import type { SystemParam } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const paramsStore = useParamsStore()

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

/** 筛选输入留在页面里；分页与结果归 store。 */
const keyword = ref('')
const statusFilter = ref<'' | 'ACTIVE' | 'DISABLED'>('')

const draft = ref<ParamDraft | null>(null)
const saving = ref(false)
/** 单独的"清空值"动作：与编辑分开，避免两者互相覆盖语义。 */
const clearing = ref(false)
const pendingDelete = ref<SystemParam | null>(null)
const deleting = ref(false)

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

function search(): void {
  void paramsStore.setFilters({ keyword: keyword.value })
}

async function resetFilters(): Promise<void> {
  keyword.value = ''
  statusFilter.value = ''
  await paramsStore.setFilters({ keyword: '', status: '' })
}

/** 用命名函数而不是模板内联箭头：内联里同时读写 ref 容易踩类型推断。 */
function onPageChange(next: { pageNum: number; pageSize: number }): void {
  void paramsStore.goToPage(next.pageNum, next.pageSize)
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
      await paramsStore.create({
        param_key: current.param_key,
        param_name: current.param_name,
        param_type: current.param_type,
        default_value: current.default_value,
        param_value: current.param_value || null,
        description: current.description || null,
        status: current.status,
      })
    } else {
      await paramsStore.update(current.id, {
        param_name: current.param_name,
        description: current.description || null,
        status: current.status,
        param_value: current.param_value || null,
        clear_value: false,
      })
    }
    draft.value = null
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
    await paramsStore.clearValue(current.id, {
      param_name: current.param_name,
      description: current.description || null,
      status: current.status,
    })
    draft.value = null
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
    await paramsStore.remove(target.id)
    pendingDelete.value = null
  } catch (cause) {
    notice(cause, '删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void paramsStore.goToPage(1, paramsStore.pageSize)
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

    <div v-if="paramsStore.error" class="alert alert--error">{{ paramsStore.error }}</div>

    <DataTable
      v-else
      :columns="columns"
      :rows="paramsStore.rows"
      :loading="paramsStore.loading"
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
      :total="paramsStore.total"
      :page-num="paramsStore.pageNum"
      :page-size="paramsStore.pageSize"
      :disabled="paramsStore.loading"
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
.cell {
  display: flex;
  flex-direction: column;
}
</style>
