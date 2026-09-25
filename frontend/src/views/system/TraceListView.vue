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
import PageContainer from '@/components/layout/PageContainer.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import { useAppStore } from '@/stores/app'
import { getTrace, listTraces } from '@/api/endpoints/logs'
import type { DataTableColumn } from '@/components/data/types'
import type { TraceEntry, TraceSummary } from '@/api/endpoints/logs'

const appStore = useAppStore()

const columns: Array<DataTableColumn<TraceSummary>> = [
  { key: 'trace_id', title: 'Trace ID' },
  { key: 'first_seen_at', title: '首条时间', width: '170px' },
  { key: 'last_seen_at', title: '末条时间', width: '170px' },
  { key: 'counts', title: '日志类型分布' },
  { key: 'total_entries', title: '总条数', width: '90px', align: 'right' },
]

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
  <PageContainer title="链路查询" description="按 Trace ID 串联一个请求产生的全部日志，用于定位某个请求为什么慢或为什么失败。">
    <div v-if="error" class="alert alert--error">{{ error }}</div>

    <DataTable
      v-else
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :row-key="(row: TraceSummary) => row.trace_id"
      empty-text="没有链路记录"
    >
      <template #cell-trace_id="{ row }">
        <PermissionButton code="trace:read" type="text" @click="openDetail(row.trace_id)">
          <code>{{ row.trace_id }}</code>
        </PermissionButton>
      </template>
      <template #cell-counts="{ row }">
        <span class="muted">{{ describeCounts(row.counts) }}</span>
      </template>
      <template #cell-first_seen_at="{ row }">
        <div>{{ row.first_seen_at }}</div>
        <div v-if="row.total_entries > 0" class="muted">{{ row.total_entries }} 条</div>
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
          <button class="link" type="button" @click="detail = null">关闭</button>
        </h3>
        <p v-if="detailLoading" class="muted">加载中…</p>
        <template v-else>
          <table class="mini-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>类型</th>
                <th>名称</th>
                <th>结果</th>
                <th>明细</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in detail.entries" :key="entry.id">
                <td class="nowrap">{{ entry.created_at }}</td>
                <td><span class="tag">{{ entry.log_type }}</span></td>
                <td>{{ entry.name }}</td>
                <td>{{ entry.result ?? '—' }}</td>
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
   不要再重写整个 `.drawer__panel`（那会让 base.css 里的统一外观失效一半）。 */
.drawer--wide {
  --drawer-width: 760px;
}
</style>
