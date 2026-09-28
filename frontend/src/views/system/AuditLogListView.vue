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
import { formatDateTime, localInputToUtcIso, nowAsLocalInput } from '@/utils/format'
import { onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { DocumentTextOutline, EyeOutline, RefreshOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import { useAppStore } from '@/stores/app'
import { useColumnSettings } from '@/composables/useColumnSettings'
import { getAuditLog, listAuditLogs } from '@/api/endpoints/logs'
import type { DataTableColumn } from '@/components/data/types'
import type { AuditLog } from '@/types'

const appStore = useAppStore()

const dataColumns: Array<DataTableColumn<AuditLog>> = [
  { key: 'created_at', title: '时间', width: '170px' },
  { key: 'action', title: '动作' },
  { key: 'result', title: '结果', width: '90px', align: 'center' },
  { key: 'operator_username', title: '操作者' },
  // 用户名会被改名、也可能重名；`operator_id` 才是稳定标识，追查时以它为准。
  { key: 'operator_id', title: '操作者 ID', width: '200px' },
  { key: 'resource_type', title: '资源类型', width: '120px' },
  { key: 'resource_id', title: '资源 ID', width: '200px' },
  { key: 'error_code', title: '错误码', width: '100px', align: 'right' },
  { key: 'ip', title: '来源 IP', width: '130px' },
  // 排查"是不是某个客户端在重试"时，只有 UA 能回答；它也是识别脚本化
  // 请求的唯一线索（`curl/8.4` 与真实浏览器一眼可分）。
  { key: 'user_agent', title: '客户端', width: '260px' },
  // 一个 `trace_id` 把这条审计和它那次请求的访问 / 操作 / 应用日志串起来，
  // 明细里虽有，但"有几条日志属于同一次操作"要一眼看出来才有用。
  { key: 'trace_id', title: '追踪 ID', width: '220px' },
  { key: 'request_id', title: '请求 ID', width: '220px' },
  { key: 'id', title: '日志 ID', width: '200px' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<AuditLog>('audit-logs', dataColumns)

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
      // 与用户管理页同一口径：`datetime-local` 的值是**不带时区的本地时间**，
      // 原样发出时后端把它当 naive datetime 绑到 timestamptz 上比较，
      // 解释权归服务端时区（实测本机为 Asia/Shanghai）。服务器一旦不是 +08:00，
      // 这里会整块偏 8 小时且不报错。转成带 `Z` 的 UTC 串后不再有时区依赖。
      created_from: localInputToUtcIso(createdFrom.value),
      created_to: localInputToUtcIso(createdTo.value),
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

/** 把结束时间设为此刻（与用户管理页同一行为，见那里的注释）。 */
function setCreatedToNow(): void {
  createdTo.value = nowAsLocalInput()
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
  <PageContainer
    title="审计日志"
    description="记录谁在什么时候做了什么、结果如何。被拒绝的操作同样会留痕，排查异常时优先看「结果 = 失败」。"
    :icon="DocumentTextOutline"
  >
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
      <div class="field">
        <span class="field__label">时间范围</span>
        <div class="field__row">
          <input
            v-model="createdFrom"
            class="field__control"
            type="datetime-local"
            aria-label="起始时间"
          />
          <span class="muted">~</span>
          <input
            v-model="createdTo"
            class="field__control"
            type="datetime-local"
            aria-label="结束时间"
          />
          <!-- 与用户管理页同一个「此刻」：两端对齐同一套时间筛选交互，
               免得同一个人在两页之间来回时记两套操作习惯。 -->
          <button
            type="button"
            class="btn btn--text btn--text-primary"
            title="把结束时间设为当前时间"
            @click="setCreatedToNow"
          >
            此刻
          </button>
        </div>
      </div>
    </SearchForm>

    <div class="toolbar">
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
      :row-key="(row: AuditLog) => row.id"
      empty-text="没有符合条件的审计记录"
      actions-title="操作"
      actions-width="120px"
    >
      <template #cell-result="{ row }">
        <span class="tag" :class="RESULT_STYLE[row.result] ?? ''">{{ row.result }}</span>
      </template>
      <template #cell-resource_id="{ row }">
        <span>{{ row.resource_id ?? '—' }}</span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ formatDateTime(row.created_at) }}</span>
      </template>
      <template #cell-action="{ row }">
        <span>{{ row.action }}</span>
      </template>
      <template #cell-error_code="{ row }">
        <!-- 成功记录没有错误码，占位就行；失败才需要显眼的数字 -->
        <span v-if="row.error_code === null" class="muted">—</span>
        <span v-else class="tag tag--locked">{{ row.error_code }}</span>
      </template>
      <template #cell-user_agent="{ row }">
        <span v-if="row.user_agent === null" class="muted">—</span>
        <!-- UA 最长 149 字符（实测）：截断显示，完整值放 title。 -->
        <span v-else class="muted clip" :title="row.user_agent">{{ row.user_agent }}</span>
      </template>
      <template #cell-trace_id="{ row }">
        <code>{{ row.trace_id ?? '—' }}</code>
      </template>
      <template #cell-request_id="{ row }">
        <code>{{ row.request_id ?? '—' }}</code>
      </template>
      <template #cell-operator_id="{ row }">
        <code class="muted">{{ row.operator_id ?? '—' }}</code>
      </template>
      <template #cell-id="{ row }">
        <code class="muted">{{ row.id }}</code>
      </template>

      <template #actions="{ row }">
        <PermissionButton code="audit:read" type="text-primary" @click="openDetail(row)">
          <NIcon :component="EyeOutline" />
          明细
        </PermissionButton>
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
          <NButton size="small" quaternary :loading="detailLoading" @click="detail = null">关闭</NButton>
        </h3>
        <dl class="kv">
          <dt>日志 ID</dt>
          <dd><code>{{ detail.id }}</code></dd>
          <dt>动作</dt>
          <dd>{{ detail.action }}</dd>
          <dt>结果</dt>
          <dd><span class="tag" :class="RESULT_STYLE[detail.result] ?? ''">{{ detail.result }}</span></dd>
          <dt>错误码</dt>
          <dd>{{ detail.error_code ?? '—' }}</dd>
          <dt>操作者</dt>
          <dd>{{ detail.operator_username ?? '—' }}（{{ detail.operator_id ?? '—' }}）</dd>
          <!-- 用展示层格式化：这里原先直接怼 ISO 串，和列表列的口径不一致 -->
          <dt>时间</dt>
          <dd>{{ formatDateTime(detail.created_at) }}</dd>
          <dt>追踪 ID</dt>
          <dd><code>{{ detail.trace_id ?? '—' }}</code></dd>
          <dt>请求 ID</dt>
          <dd><code>{{ detail.request_id ?? '—' }}</code></dd>
          <dt>资源</dt>
          <dd>{{ detail.resource_type }}{{ detail.resource_id === null ? '' : ` / ${detail.resource_id}` }}</dd>
          <dt>来源 IP</dt>
          <dd>{{ detail.ip ?? '—' }}</dd>
          <!-- 客户端字符串可能很长（真实 UA 上百字符）；`.kv dd` 已带
               `word-break: break-all`，不需要额外的换行样式。 -->
          <dt>客户端</dt>
          <dd>{{ detail.user_agent ?? '—' }}</dd>
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

