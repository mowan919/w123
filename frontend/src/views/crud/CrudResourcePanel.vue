<script setup lang="ts">
/**
 * CrudResourcePanel（VCTN §33）—— V3.1 四新增域**结构层**实体的通用 CRUD 面板。
 *
 * 为什么是一个通用面板而不是 44 个页面
 * -----------------------------------
 * 这 44 个实体的结构层端点形状完全一致（见 `api/endpoints/v31-crud.ts`），
 * 页面要做的事也完全一致：列一张表、按可过滤列筛选、分页、增 / 改 / 删。
 * 逐表写 44 个 `.vue` 只会得到 44 份 95% 相同的代码 —— 每一份都是一个
 * 可以写错的地方，而且改一处交互要改 44 遍。
 *
 * 资源差异（有哪些列、哪些列可过滤 / 可编辑、哪一列是枚举）全部来自
 * 后端契约的镜像 `V31_META`（由 `scripts/gen_v31_crud.py` 从 ORM 模型生成），
 * 因此"后端加了列、前端不会忘"这件事是**结构性**成立的，不靠自觉。
 *
 * ⚠️ 本面板**不含任何业务规则**。等级计算、积分记账、工具执行、博客发布流
 * 属 `docs/spec/09-D` 的未冻结项，本轮一律不实现、不发明取值域：
 * 表单里出现的字段就是"表里有这一列"，语义由后端冻结后另行交付。
 *
 * 表单绑定为什么不用 `v-model`
 * ---------------------------
 * 草稿与筛选值都是**动态键**（`Record<string, …>`），而工程开了
 * `noUncheckedIndexedAccess` —— 索引访问的类型是 `string | undefined`，
 * 直接 `v-model="draft[key]"` 会被 `vue-tsc` 判成"可能写入 undefined"。
 * 这里统一走 `:value` + `@input` 与显式的 `onXxx(key, event)` 取值，
 * 好处是事件目标的类型收窄只写一次，且不依赖模板里的类型断言。
 *
 * 权限
 * ----
 * 三个写按钮用 `PermissionButton` 按 `v31:<kebab>:create|update|delete`
 * 判定（后端已按每个实体播种这三个 BUTTON 资源）。这只是**展示层**控制：
 * 真正拦住越权的是后端路由上的 `require_api_permission`（域级 `*_MANAGE`），
 * 前端藏按钮不能替代那一次 403。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { AddOutline, CreateOutline, RefreshOutline, TrashOutline } from '@vicons/ionicons5'
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
import { usePageQuery } from '@/composables/usePageQuery'
import { formatDateTime, localInputToUtcIso } from '@/utils/format'
import {
  createRecord,
  deleteRecord,
  listRecords,
  updateRecord,
  type CrudListQuery,
  type CrudRecord,
} from '@/api/endpoints/v31-crud'
import type { V31ColumnMeta, V31ResourceMeta } from '@/api/endpoints/v31-meta'
import type { DataTableColumn } from '@/components/data/types'
import type { ID } from '@/types/common'

const props = defineProps<{ meta: V31ResourceMeta }>()

const appStore = useAppStore()

/** 路由段（`biz-user` / `blog-article` / …）—— 接口路径与按钮编码都要用它。 */
const kebab = computed(() => props.meta.kebab)

// ---------------------------------------------------------------- 表格列

/**
 * 列定义直接来自元数据。
 *
 * `key` 的类型是 `keyof CrudRecord & string`，而 `CrudRecord` 带开放索引，
 * 所以任意列名都能通过类型检查 —— 这是**有意**的：列集合由后端契约决定，
 * 前端不可能为 44 张表预先声明字段名。`DataTable` 用 key 取值，
 * 因此字段名与响应不一致时表现为空单元格（而不是悄悄展示了别的字段）。
 */
const dataColumns = computed<Array<DataTableColumn<CrudRecord>>>(() =>
  props.meta.columns.map((column) => ({
    key: column.key,
    title: column.label,
    width: columnWidth(column),
  })),
)

function columnWidth(column: V31ColumnMeta): string | undefined {
  if (column.type === 'boolean') return '90px'
  if (column.type === 'datetime') return '170px'
  if (column.type === 'date') return '120px'
  return undefined
}

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<CrudRecord>(`v31.${props.meta.resourceType}`, dataColumns.value)

// ---------------------------------------------------------------- 筛选

const filterColumns = computed(() => props.meta.columns.filter((column) => column.filterable))
const formColumns = computed(() => props.meta.columns.filter((column) => column.formable))

/** 筛选输入（值一律是字符串；空串表示"不筛这一列"）。 */
const filters = ref<Record<string, string>>({})

function filterValue(key: string): string {
  return filters.value[key] ?? ''
}

function onFilterInput(key: string, event: Event): void {
  const target = event.target as HTMLInputElement | null
  filters.value = { ...filters.value, [key]: target?.value ?? '' }
}

/**
 * 把筛选输入转成后端 `filters()` 认识的对象。
 *
 * 空串一律**丢弃**而不是发一个 `?status=` —— 通道上多一个空参数会让
 * "没有筛选"与"筛选等于空字符串"混在一起，后者在枚举列上必然查不到任何行。
 */
function activeFilters(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(filters.value)) {
    if (value !== '') out[key] = value
  }
  return out
}

// ---------------------------------------------------------------- 分页

const { rows, total, pageNum, pageSize, loading, error, reload, onPageChange } = usePageQuery<
  CrudRecord
>((query) => listRecords<CrudRecord>(kebab.value, query as CrudListQuery))

/**
 * 重新拉取当前页。
 *
 * 筛选条件变化时**必须回到第 1 页**：停在原页码上，结果集缩小后用户会看到
 * 一个空列表，而数据其实还在（与分页组件"每页条数变化后归 1"同一理由）。
 */
function refresh(): void {
  if (pageNum.value !== 1) {
    onPageChange({ pageNum: 1, pageSize: pageSize.value })
    return
  }
  void reload(activeFilters())
}

function resetFilters(): void {
  filters.value = {}
  void reload({})
  if (pageNum.value !== 1) onPageChange({ pageNum: 1, pageSize: pageSize.value })
}

onMounted(() => {
  void reload(activeFilters())
})

// ---------------------------------------------------------------- 新增 / 编辑

/** 表单草稿：`column.key` → 原始输入值（boolean 用 boolean，其余用 string）。 */
type DraftValue = string | boolean
const draft = ref<Record<string, DraftValue>>({})
const draftOpen = ref(false)
const editingId = ref<ID | null>(null)
const saving = ref(false)
const pendingDelete = ref<CrudRecord | null>(null)
const deleting = ref(false)

const isEditing = computed(() => editingId.value !== null)

function emptyDraft(): Record<string, DraftValue> {
  const out: Record<string, DraftValue> = {}
  for (const column of formColumns.value) {
    out[column.key] = column.type === 'boolean' ? false : ''
  }
  return out
}

function startCreate(): void {
  editingId.value = null
  draft.value = emptyDraft()
  draftOpen.value = true
}

function startEdit(row: CrudRecord): void {
  editingId.value = row.id
  const out: Record<string, DraftValue> = {}
  for (const column of formColumns.value) {
    const raw = row[column.key]
    if (column.type === 'boolean') out[column.key] = raw === true
    else out[column.key] = raw === null || raw === undefined ? '' : String(raw)
  }
  draft.value = out
  draftOpen.value = true
}

function draftText(key: string): string {
  const value = draft.value[key]
  return typeof value === 'string' ? value : ''
}

function draftChecked(key: string): boolean {
  return draft.value[key] === true
}

function onDraftInput(key: string, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement | null
  draft.value = { ...draft.value, [key]: target?.value ?? '' }
}

function onDraftCheck(key: string, event: Event): void {
  const target = event.target as HTMLInputElement | null
  draft.value = { ...draft.value, [key]: target?.checked ?? false }
}

/** 表单校验：只做"必填有没有填"这一级，业务规则不在前端发明。 */
const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  for (const column of formColumns.value) {
    if (!column.required || column.type === 'boolean') continue
    if (draftText(column.key).trim() === '') return `请填写 ${column.label}`
  }
  return null
})

/**
 * 草稿 → 请求体。
 *
 * 三条规则：
 * 1. 只提交**可编辑**的列（服务端托管字段与主键从不出现，见 `app.crud.base`）；
 * 2. 空串转 `null` 而不是 `''` —— 空串会撞 `NOT NULL` 或写入脏值；
 * 3. `datetime` 走 `localInputToUtcIso`（后端时间统一 UTC，见 `utils/format`）。
 */
function buildPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const column of formColumns.value) {
    if (column.type === 'boolean') {
      payload[column.key] = draftChecked(column.key)
      continue
    }
    const text = draftText(column.key).trim()
    if (text === '') {
      payload[column.key] = null
    } else if (column.type === 'datetime') {
      payload[column.key] = localInputToUtcIso(text)
    } else if (column.type === 'number') {
      const numeric = Number(text)
      payload[column.key] = Number.isNaN(numeric) ? null : numeric
    } else {
      payload[column.key] = text
    }
  }
  return payload
}

async function save(): Promise<void> {
  if (draftError.value !== null) return
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingId.value === null) {
      await createRecord(kebab.value, payload)
      appStore.showNotice('success', '已创建')
    } else {
      await updateRecord(kebab.value, editingId.value, payload)
      appStore.showNotice('success', '已更新')
    }
    draftOpen.value = false
    void reload(activeFilters())
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deleting.value = true
  try {
    await deleteRecord(kebab.value, target.id)
    pendingDelete.value = null
    appStore.showNotice('success', '已删除')
    void reload(activeFilters())
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '删除失败')
  } finally {
    deleting.value = false
  }
}

// 资源切换：外层已按 kebab 做了 `:key`（组件会重建），这里保持状态不变量显式。
watch(kebab, () => {
  filters.value = {}
  draftOpen.value = false
  pendingDelete.value = null
  void reload({})
})

// ---------------------------------------------------------------- 展示

function displayCell(row: CrudRecord, column: V31ColumnMeta): string {
  const raw = row[column.key]
  if (raw === null || raw === undefined || raw === '') return '—'
  if (column.type === 'boolean') return raw === true ? '是' : '否'
  if (column.type === 'datetime') return formatDateTime(String(raw))
  if (column.type === 'json') return JSON.stringify(raw)
  return String(raw)
}

function isBlank(row: CrudRecord, column: V31ColumnMeta): boolean {
  const raw = row[column.key]
  return raw === null || raw === undefined || raw === ''
}

function placeholderFor(column: V31ColumnMeta): string {
  if (column.type === 'enum') return `枚举值（${column.enumType ?? '枚举'}）`
  if (column.type === 'fk') return '关联 ID（雪花 ID 字符串）'
  if (column.type === 'json') return 'JSON 文本'
  return ''
}
</script>

<template>
  <PageContainer
    :title="props.meta.title"
    description="结构层数据维护。业务规则（等级 / 积分 / 工具执行 / 发布流程）尚未冻结，本页只做增删改查。"
  >
    <SearchForm @search="refresh" @reset="resetFilters">
      <label v-for="column in filterColumns" :key="column.key" class="field">
        <span class="field__label">{{ column.label }}</span>
        <input
          :value="filterValue(column.key)"
          class="field__control"
          :placeholder="column.type === 'enum' ? '枚举值（如 ACTIVE）' : '精确匹配'"
          @input="onFilterInput(column.key, $event)"
        />
      </label>
    </SearchForm>

    <div class="toolbar">
      <PermissionButton :code="`v31:${kebab}:create`" type="primary" @click="startCreate">
        <NIcon :component="AddOutline" />
        新增
      </PermissionButton>
      <NButton size="small" :loading="loading" @click="refresh">
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
      :row-key="(row: CrudRecord) => row.id"
      empty-text="没有符合条件的数据"
      actions-title="操作"
      actions-width="160px"
    >
      <template
        v-for="column in props.meta.columns"
        :key="column.key"
        #[`cell-${column.key}`]="{ row }"
      >
        <span class="clip" :class="isBlank(row, column) ? 'muted' : ''">
          {{ displayCell(row, column) }}
        </span>
      </template>

      <template #actions="{ row }">
        <span class="table-actions">
          <PermissionButton
            :code="`v31:${kebab}:update`"
            type="text-primary"
            @click="startEdit(row)"
          >
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton
            :code="`v31:${kebab}:delete`"
            type="text-danger"
            @click="pendingDelete = row"
          >
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

    <FormDialog
      :open="draftOpen"
      :title="isEditing ? `编辑 ${props.meta.title}` : `新增 ${props.meta.title}`"
      :loading="saving"
      :error="draftError"
      :width="680"
      @cancel="draftOpen = false"
      @submit="save"
    >
      <div class="form-grid">
        <label v-for="column in formColumns" :key="column.key" class="field">
          <span class="field__label">
            {{ column.label }}
            <em v-if="column.required" class="field__required">*</em>
          </span>
          <input
            v-if="column.type === 'boolean'"
            class="field__check"
            type="checkbox"
            :checked="draftChecked(column.key)"
            @change="onDraftCheck(column.key, $event)"
          />
          <textarea
            v-else-if="column.type === 'json'"
            class="field__control field__control--area"
            :value="draftText(column.key)"
            rows="3"
            :placeholder="placeholderFor(column)"
            @input="onDraftInput(column.key, $event)"
          />
          <input
            v-else-if="column.type === 'datetime'"
            class="field__control"
            type="datetime-local"
            :value="draftText(column.key)"
            @input="onDraftInput(column.key, $event)"
          />
          <input
            v-else-if="column.type === 'date'"
            class="field__control"
            type="date"
            :value="draftText(column.key)"
            @input="onDraftInput(column.key, $event)"
          />
          <input
            v-else-if="column.type === 'number'"
            class="field__control"
            type="number"
            :value="draftText(column.key)"
            @input="onDraftInput(column.key, $event)"
          />
          <input
            v-else
            class="field__control"
            :value="draftText(column.key)"
            :maxlength="column.maxLength"
            :placeholder="placeholderFor(column)"
            @input="onDraftInput(column.key, $event)"
          />
        </label>
      </div>

      <p class="hint">
        服务端托管字段（创建人 / 更新人等）不在表单里 —— 它们由后端按当前操作者回填。
        业务规则尚未冻结：本页不做等级计算、积分记账或发布流程判定。
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除数据"
      danger
      :confirm-text="deleting ? '删除中…' : '确认删除'"
      :loading="deleting"
      :description="`删除后该行不再出现在列表中（逻辑删除）。资源：${props.meta.resourceType}，ID：${pendingDelete?.id ?? ''}。`"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    />
  </PageContainer>
</template>

<style scoped>
.field__check {
  width: 18px;
  height: 18px;
  margin-top: 4px;
}

.field__control--area {
  min-height: 72px;
  resize: vertical;
}

.field__required {
  margin-left: 2px;
  color: var(--vctn-danger);
  font-style: normal;
}
</style>
