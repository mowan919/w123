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
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { AddOutline, CreateOutline, OptionsOutline, RefreshOutline, ReturnUpBackOutline, TrashOutline } from '@vicons/ionicons5'
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
import { useParamsStore } from '@/stores/params'
import { formatDateTime } from '@/utils/format'
import type { DataTableColumn } from '@/components/data/types'
import type { SystemParam } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const paramsStore = useParamsStore()

const dataColumns: Array<DataTableColumn<SystemParam>> = [
  { key: 'param_key', title: '参数键' },
  { key: 'param_name', title: '参数名' },
  { key: 'param_type', title: '类型', width: '90px' },
  // 「显式值」与「当前生效值」是两个概念：前者是管理员**设过**的值（可能为
  // NULL = 没设过），后者是策略链算出来的结果。只看生效值无法回答
  // "这个值是配的还是继承来的" —— 那正是排查配置问题时第一个要问的。
  { key: 'param_value', title: '显式值', width: '160px' },
  { key: 'effective_value', title: '当前生效值' },
  { key: 'default_value', title: '默认值' },
  { key: 'status', title: '状态', width: '90px', align: 'center' },
  { key: 'description', title: '描述' },
  { key: 'created_at', title: '创建时间', width: '170px' },
  { key: 'updated_at', title: '更新时间', width: '170px' },
  { key: 'id', title: '参数 ID', width: '200px' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<SystemParam>('params', dataColumns)

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

function emptyDraft(): ParamDraft {
  return {
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

const draft = ref<ParamDraft>(emptyDraft())
const draftOpen = ref(false)
const saving = ref(false)
/** 单独的"清空值"动作：与编辑分开，避免两者互相覆盖语义。 */
const clearing = ref(false)
const pendingDelete = ref<SystemParam | null>(null)
const deleting = ref(false)

const isEditing = computed(() => draft.value.id !== null)

const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  if (draft.value.param_key.trim() === '') return '请填写参数键'
  if (draft.value.param_name.trim() === '') return '请填写参数名'
  if (draft.value.param_type === 'INT' && draft.value.param_value !== '' && !/^-?\d+$/.test(draft.value.param_value.trim())) {
    return '类型为 INT 时，当前值必须是整数'
  }
  if (
    draft.value.param_type === 'BOOL' &&
    draft.value.param_value !== '' &&
    !['true', 'false'].includes(draft.value.param_value.trim().toLowerCase())
  ) {
    return '类型为 BOOL 时，当前值只能是 true 或 false'
  }
  return null
})

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
  draft.value = emptyDraft()
  draftOpen.value = true
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
  draftOpen.value = true
}

async function save(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  saving.value = true
  try {
    if (current.id === null) {
      await paramsStore.create({
        param_key: current.param_key.trim(),
        param_name: current.param_name.trim(),
        param_type: current.param_type,
        default_value: current.default_value,
        param_value: current.param_value || null,
        description: current.description || null,
        status: current.status,
      })
    } else {
      await paramsStore.update(current.id, {
        param_name: current.param_name.trim(),
        description: current.description || null,
        status: current.status,
        param_value: current.param_value || null,
        clear_value: false,
      })
    }
    draftOpen.value = false
    appStore.showNotice('success', current.id === null ? '参数已创建' : '参数已更新')
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    saving.value = false
  }
}

/** 独立动作：清空当前值 → 回落到默认值。 */
async function clearValue(): Promise<void> {
  const current = draft.value
  if (current.id === null) return
  clearing.value = true
  try {
    await paramsStore.clearValue(current.id, {
      param_name: current.param_name.trim(),
      description: current.description || null,
      status: current.status,
    })
    draftOpen.value = false
    appStore.showNotice('success', '已清空当前值，参数回落到默认值')
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
  <PageContainer
    title="系统参数"
    description="集中管理运行期开关与阈值。没有单独设置当前值时，系统按默认值处理。"
    :icon="OptionsOutline"
  >
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
      <PermissionButton code="param:create" type="primary" @click="startCreate">
        <NIcon :component="AddOutline" />
        新增参数
      </PermissionButton>
      <NButton size="small" :loading="paramsStore.loading" @click="paramsStore.goToPage(paramsStore.pageNum, paramsStore.pageSize)">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
      <span class="toolbar__end">
        <ColumnSettings
          :items="columnItems"
          :disabled="paramsStore.loading"
          @toggle="toggleColumn"
          @move="moveColumn"
          @reset="resetColumns"
        />
      </span>
    </div>

    <div v-if="paramsStore.error" class="alert alert--error">{{ paramsStore.error }}</div>

    <DataTable
      v-else
      :columns="visibleColumns"
      :rows="paramsStore.rows"
      :loading="paramsStore.loading"
      :row-key="(row: SystemParam) => row.id"
      empty-text="没有符合条件的参数"
      actions-title="操作"
      actions-width="150px"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-effective_value="{ row }">
        <div class="cell">
          <code class="clip" :title="row.effective_value">{{ row.effective_value }}</code>
          <div v-if="row.param_value === null" class="muted">取自默认值</div>
        </div>
      </template>
      <template #cell-param_key="{ row }">
        <code>{{ row.param_key }}</code>
      </template>
      <template #cell-param_value="{ row }">
        <code v-if="row.param_value !== null" class="clip" :title="row.param_value">
          {{ row.param_value }}
        </code>
        <span v-else class="muted">未设置</span>
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
          <PermissionButton code="param:update" type="text-primary" @click="startEdit(row)">
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton code="param:delete" type="text-danger" @click="pendingDelete = row">
            <NIcon :component="TrashOutline" />
            删除
          </PermissionButton>
        </span>
      </template>
    </DataTable>

    <Pagination
      :total="paramsStore.total"
      :page-num="paramsStore.pageNum"
      :page-size="paramsStore.pageSize"
      :disabled="paramsStore.loading"
      @change="onPageChange"
    />

    <FormDialog
      :open="draftOpen"
      :title="isEditing ? `编辑参数：${draft.param_key}` : '新增参数'"
      :loading="saving"
      :error="draftError"
      :width="620"
      @cancel="draftOpen = false"
      @submit="save"
    >
      <template #extra>
        <NButton
          v-if="isEditing"
          quaternary
          type="warning"
          :loading="clearing"
          :disabled="saving"
          @click="clearValue"
        >
          <template #icon>
            <NIcon :component="ReturnUpBackOutline" />
          </template>
          清空当前值
        </NButton>
      </template>

      <div class="form-grid">
        <label class="field">
          <span class="field__label">参数键</span>
          <input v-model.trim="draft.param_key" class="field__control" :disabled="isEditing" placeholder="如 MFA_REQUIRED_DEFAULT" />
        </label>
        <label class="field">
          <span class="field__label">参数名</span>
          <input v-model.trim="draft.param_name" class="field__control" placeholder="中文名称" />
        </label>
        <label class="field">
          <span class="field__label">类型</span>
          <select v-model="draft.param_type" class="field__control" :disabled="isEditing">
            <option v-for="type in PARAM_TYPES" :key="type" :value="type">{{ type }}</option>
          </select>
        </label>
        <label class="field">
          <span class="field__label">默认值</span>
          <input v-model.trim="draft.default_value" class="field__control" />
        </label>
        <label class="field">
          <span class="field__label">当前值</span>
          <input v-model.trim="draft.param_value" class="field__control" placeholder="留空表示使用默认值" />
        </label>
        <label class="field">
          <span class="field__label">状态</span>
          <select v-model="draft.status" class="field__control">
            <option value="ACTIVE">启用</option>
            <option value="DISABLED">禁用</option>
          </select>
        </label>
        <label class="field field--full">
          <span class="field__label">描述</span>
          <input v-model.trim="draft.description" class="field__control" placeholder="选填：这个参数控制什么" />
        </label>
      </div>

      <p class="hint">
        <template v-if="isEditing">
          参数键与类型决定读取方式，创建后不可修改；「清空当前值」与「保存」是两次独立提交。
        </template>
        <template v-else>
          生效值优先取「当前值」，未设置时取「默认值」。参数值不会写入审计日志。
        </template>
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除参数"
      danger
      :confirm-text="deleting ? '删除中…' : '确认删除'"
      :loading="deleting"
      :description="`删除后该参数回落到未配置状态，相关行为按默认处理。参数键：${pendingDelete?.param_key ?? ''}。`"
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
