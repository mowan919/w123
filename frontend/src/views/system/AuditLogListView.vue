<script setup lang="ts">
/**
 * 审计日志查询（`08 §8`，Phase 10 后端补交付的读端点）。
 *
 * 这一页存在的意义不只是"能看日志"：审计是**安全复盘**的唯一依据，
 * 越权尝试会写 FAILURE 记录。能查询、能按资源类型过滤，这些记录才不会
 * 变成只能靠 grep 的死数据（FINDING-10-01 的教训）。
 *
 * 注意只展示**结果**：`before_data` / `after_data` 里可能含敏感字段，
 * 后端已经在写入侧做了脱敏范围控制，这里不做二次加工、也不额外放大。
 */
import { onMounted, ref } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import { useAppStore } from '@/stores/app'
import { getAuditLog, listAuditLogs } from '@/api/endpoints/logs'
import type { DataTableColumn } from '@/components/data/types'
import type { AuditLog } from '@/types'

const appStore = useAppStore()

const columns: Array<DataTableColumn<AuditLog>> = [
  { key: 'created_at', title: '时间', width: '170px' },
  { key: 'action', title: '动作' },
  { key: 'operator_username', title: '操作者' },
  { key: 'resource_type', title: '资源类型', width: '120px' },
  { key: 'resource_id', title: '资源 ID', width: '120px' },
  { key: 'result', title: '结果', width: '90px', align: 'center' },
  { key: 'ip', title: '来源 IP', width: '130px' },
]

const RESULT_STYLE: Record<string, string> = {
  SUCCESS: 'tag--active',
  FAILURE: 'tag--disabled',
}

const rows = ref<AuditLog[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

const action = ref('')
const operatorId = ref('')
const resourceType = ref('')
const resourceId = ref('')
const result = ref('')
const createdFrom = ref('')
const createdTo = ref('')

/** 明细抽屉。审计记录是 append-only，不提供编辑。 */
const detail = ref<AuditLog | null>(null)
const detailLoading = ref(false)

function stripInput(): string | null {
  const value = operatorId.value.trim()
  return value === '' ? null : value
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const page = await listAuditLogs({
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      action: action.value || null,
      operator_id: stripInput(),
      resource_type: resourceType.value || null,
      resource_id: resourceId.value || null,
      result: result.value || null,
      created_from: createdFrom.value || null,
      created_to: createdTo.value || null,
    })
    rows.value = page.list
    total.value = page.total
    pageNum.value = page.pageNum
    pageSize.value = page.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审计日志加载失败'
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
  action.value = ''
  operatorId.value = ''
  resourceType.value = ''
  resourceId.value = ''
  result.value = ''
  createdFrom.value = ''
  createdTo.value = ''
  pageNum.value = 1
  void load()
}

function onPageChange(next: { pageNum: number; pageSize: number }): void {
  pageNum.value = next.pageNum
  pageSize.value = next.pageSize
  void load()
}

async function openDetail(row: AuditLog): Promise<void> {
  detail.value = row
  detailLoading.value = true
  try {
    detail.value = await getAuditLog(row.id)
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '明细加载失败')
  } finally {
    detailLoading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageContainer title="审计日志" description="失败记录（越权尝试）是这一页最有价值的部分，可按动作、操作者、资源类型与时间窗组合过滤。">
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field"><span class="field__label">动作</span><input v-model="action" class="field__control" placeholder="如 USER_DISABLE" /></label>
      <label class="field"><span class="field__label">操作者 ID</span><input v-model="operatorId" class="field__control" /></label>
      <label class="field"><span class="field__label">资源类型</span><input v-model="resourceType" class="field__control" placeholder="如 USER" /></label>
      <label class="field"><span class="field__label">资源 ID</span><input v-model="resourceId" class="field__control" /></label>
      <label class="field"><span class="field__label">结果</span>
        <select v-model="result" class="field__control">
          <option value="">全部</option>
          <option value="SUCCESS">成功</option>
          <option value="FAILURE">失败</option>
        </select>
      </label>
      <label class="field"><span class="field__label">起始时间</span><input v-model="createdFrom" class="field__control" type="datetime-local" /></label>
      <label class="field"><span class="field__label">结束时间</span><input v-model="createdTo" class="field__control" type="datetime-local" /></label>
    </SearchForm>

    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <DataTable
      v-else
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :row-key="(row: AuditLog) => row.id"
      empty-text="没有符合条件的审计记录"
    >
      <template #cell-result="{ row }">
        <span class="tag" :class="RESULT_STYLE[row.result] ?? ''">{{ row.result }}</span>
      </template>
      <template #cell-resource_id="{ row }">
        <PermissionButton code="audit:read" type="text" @click="openDetail(row)">
          {{ row.resource_id ?? '—' }}
        </PermissionButton>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ row.created_at }}</span>
      </template>
      <template #cell-action="{ row }">
        <div>{{ row.action }}</div>
        <div v-if="row.error_code !== null" class="muted">错误码 {{ row.error_code }}</div>
      </template>
    </DataTable>

    <Pagination
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      :disabled="loading"
      @change="onPageChange"
    />

    <div v-if="detail !== null" class="drawer">
      <div class="drawer__panel">
        <h3 class="drawer__title">
          审计明细
          <button class="link" type="button" @click="detail = null">关闭</button>
        </h3>
        <dl class="kv">
          <dt>动作</dt>
          <dd>{{ detail.action }}</dd>
          <dt>结果</dt>
          <dd><span class="tag" :class="RESULT_STYLE[detail.result] ?? ''">{{ detail.result }}</span></dd>
          <dt>操作者</dt>
          <dd>{{ detail.operator_username ?? '—' }}（{{ detail.operator_id ?? '—' }}）</dd>
          <dt>时间</dt>
          <dd>{{ detail.created_at }}</dd>
          <dt>追踪 ID</dt>
          <dd><code>{{ detail.trace_id ?? '—' }}</code></dd>
          <dt>请求 ID</dt>
          <dd><code>{{ detail.request_id ?? '—' }}</code></dd>
          <dt>资源</dt>
          <dd>{{ detail.resource_type }}{{ detail.resource_id === null ? '' : ` / ${detail.resource_id}` }}</dd>
          <dt>来源</dt>
          <dd>{{ detail.ip ?? '—' }}</dd>
        </dl>

        <template v-if="detail.before_data !== null || detail.after_data !== null">
          <h4 class="drawer__sub">变更前</h4>
          <pre class="json">{{ detail.before_data === null ? '—' : JSON.stringify(detail.before_data, null, 2) }}</pre>
          <h4 class="drawer__sub">变更后</h4>
          <pre class="json">{{ detail.after_data === null ? '—' : JSON.stringify(detail.after_data, null, 2) }}</pre>
        </template>
        <p v-else class="muted">该记录没有携带变更前后数据（读类动作通常如此）。</p>
      </div>
    </div>
  </PageContainer>
</template>

<style scoped>
.alert {
  padding: 10px 14px;
  border-radius: var(--vctn-radius);
  margin-bottom: 12px;
  background: #fdeceb;
  color: var(--vctn-danger);
}

.drawer {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 120;
  display: flex;
  justify-content: flex-end;
}

.drawer__panel {
  width: min(560px, 100vw);
  background: var(--vctn-surface);
  padding: 18px;
  overflow: auto;
  height: 100%;
}

.drawer__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 16px;
  margin-bottom: 12px;
}

.drawer__sub {
  font-size: 13px;
  margin: 14px 0 4px;
  color: var(--vctn-text-weak);
}

.kv {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 4px 12px;
  margin: 0;
}

.kv dt {
  color: var(--vctn-text-weak);
}

.kv dd {
  margin: 0;
  word-break: break-all;
}

.json {
  background: #f7f8fa;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  padding: 10px;
  overflow: auto;
  font-size: 12px;
}

.link {
  border: none;
  background: none;
  color: var(--vctn-primary);
  cursor: pointer;
  font: inherit;
}
</style>
