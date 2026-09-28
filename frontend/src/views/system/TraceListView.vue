<script setup lang="ts">
/**
 * 链路查询（`08 §8`）。
 *
 * 与审计日志的差别：审计是**结果**的世界（谁做了什么、成功还是失败），
 * 链路是**过程**的世界（一个请求穿过了多少日志、耗时分布、卡在哪一步）。
 *
 * 这里的 `counts` 是各日志类型的条数统计，用于在列表里一眼看出
 * "业务日志多还是审计多"；点开才看逐条明细。
 */
import { onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { EyeOutline, GitNetworkOutline, RefreshOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import { useAppStore } from '@/stores/app'
import { useColumnSettings } from '@/composables/useColumnSettings'
import { formatDateTime } from '@/utils/format'
import { getTrace, listTraces } from '@/api/endpoints/logs'
import type { DataTableColumn } from '@/components/data/types'
import type { TraceEntry, TraceSummary } from '@/api/endpoints/logs'

const appStore = useAppStore()

const dataColumns: Array<DataTableColumn<TraceSummary>> = [
  { key: 'trace_id', title: '链路 ID' },
  // 一个 `trace_id` 可能被 `X-Trace-ID` 复用在多个请求上，`request_id` 才是
  // "最近那一次 HTTP 请求"的标识 —— 排查时经常要靠它去访问日志里对时间。
  { key: 'request_id', title: '请求 ID', width: '220px' },
  { key: 'first_seen_at', title: '首条时间', width: '170px' },
  { key: 'last_seen_at', title: '末条时间', width: '170px' },
  { key: 'counts', title: '日志类型分布' },
  { key: 'total_entries', title: '总条数', width: '90px', align: 'right' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<TraceSummary>('traces', dataColumns)

const rows = ref<TraceSummary[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

const detail = ref<{ traceId: string; entries: TraceEntry[] } | null>(null)
const detailLoading = ref(false)

function describeCounts(counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${type}×${count}`)
  return parts.length === 0 ? '—' : parts.join('，')
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listTraces({ pageNum: pageNum.value, pageSize: pageSize.value })
    rows.value = result.list
    total.value = result.total
    pageNum.value = result.pageNum
    pageSize.value = result.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '链路加载失败'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onPageChange(next: { pageNum: number; pageSize: number }): void {
  pageNum.value = next.pageNum
  pageSize.value = next.pageSize
  void load()
}

async function openDetail(traceId: string): Promise<void> {
  detail.value = null
  detailLoading.value = true
  try {
    const result = await getTrace(traceId)
    detail.value = { traceId: result.trace_id, entries: result.entries }
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '链路明细加载失败')
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
    title="链路查询"
    description="按一次请求串联它产生的全部日志，用于判断一个操作慢在哪里、或者在哪一步失败。"
    :icon="GitNetworkOutline"
  >
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
      :row-key="(row: TraceSummary) => row.trace_id"
      empty-text="没有链路记录"
      actions-title="操作"
      actions-width="110px"
    >
      <template #cell-trace_id="{ row }">
        <code>{{ row.trace_id }}</code>
      </template>
      <template #cell-request_id="{ row }">
        <code>{{ row.request_id ?? '—' }}</code>
      </template>
      <template #cell-counts="{ row }">
        <span class="muted">{{ describeCounts(row.counts) }}</span>
      </template>
      <template #cell-first_seen_at="{ row }">
        <div class="muted">{{ formatDateTime(row.first_seen_at) }}</div>
        <div v-if="row.total_entries > 0" class="muted">{{ row.total_entries }} 条</div>
      </template>
      <template #cell-last_seen_at="{ row }">
        <span class="muted">{{ formatDateTime(row.last_seen_at) }}</span>
      </template>

      <template #actions="{ row }">
        <PermissionButton code="trace:read" type="text-primary" @click="openDetail(row.trace_id)">
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

    <div v-if="detail !== null" class="drawer drawer--wide">
      <div class="drawer__panel">
        <h3 class="drawer__title">
          链路明细
          <NButton size="small" quaternary @click="detail = null">关闭</NButton>
        </h3>
        <p v-if="detailLoading" class="muted">加载中…</p>
        <template v-else>
          <!-- `GET /traces/{id}` 的响应里 `trace_id` 与 `entries` 是一对；
              此前只用了后者，于是抽屉里看不出"这条明细属于哪条链路" ——
               复制给同事时无法自证。 -->
          <p class="trace-meta">
            链路 ID <code>{{ detail.traceId }}</code>
            <span class="muted">共 {{ detail.entries.length }} 条</span>
          </p>
          <table class="mini-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>类型</th>
                <th>名称</th>
                <th>结果</th>
                <th>操作者</th>
                <th>请求 ID</th>
                <th>明细</th>
              </tr>
            </thead>
            <tbody>
              <!-- key 带上 `log_type`：条目来自五张**不同**的表，只按 `id`
                   去重是"碰巧成立"（Snowflake 跨表不撞），而五张表之间
                   并没有任何约束保证这一点。 -->
              <tr v-for="entry in detail.entries" :key="`${entry.log_type}-${entry.id}`">
                <td class="nowrap">{{ formatDateTime(entry.created_at) }}</td>
                <td><span class="tag">{{ entry.log_type }}</span></td>
                <td>
                  <div>{{ entry.name }}</div>
                  <!-- 条目 ID：五张表各自的主键，报障时用来精确定位某一条 -->
                  <div class="muted">#{{ entry.id }}</div>
                </td>
                <td>{{ entry.result ?? '—' }}</td>
                <!--
                  操作者与请求 ID 后端一直在返回，但此前没渲染 —— 于是"这条
                  日志是谁产生的"只能靠点开 JSON 明细去翻，而 `application_logs`
                  这类条目**没有** operator 字段，看起来像数据缺失。
                -->
                <td>
                  <template v-if="entry.operator_username !== null || entry.operator_id !== null">
                    <div>{{ entry.operator_username ?? '—' }}</div>
                    <div class="muted">{{ entry.operator_id ?? '—' }}</div>
                  </template>
                  <span v-else class="muted">—</span>
                </td>
                <td class="nowrap">
                  <code v-if="entry.request_id !== null">{{ entry.request_id }}</code>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <pre v-if="Object.keys(entry.detail).length > 0" class="json">
{{ JSON.stringify(entry.detail, null, 2) }}</pre>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="detail.entries.length === 0" class="muted">该链路没有任何日志条目。</p>
        </template>
      </div>
    </div>
  </PageContainer>
</template>

<style scoped>
/* 链路详情列多、JSON 长，抽屉要比默认宽；宽度走 `--drawer-width` 局部变量，
   不要再重写整个 `.drawer__panel`（那会让 base.css 里的统一外观失效一半）。
   920px 是加了「操作者 / 请求 ID」两列之后的取值：仍留出明细列的横向空间。 */
.drawer--wide {
  --drawer-width: 920px;
}

.trace-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 10px;
  flex-wrap: wrap;
}
</style>
