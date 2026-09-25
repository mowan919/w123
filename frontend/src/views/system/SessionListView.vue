<script setup lang="ts">
/**
 * 会话管理（FE-06 / `08 §5`）。
 *
 * 会话是**安全视角**下的实体：看到"谁在什么时候从哪个 IP 登录了"比看到用户
 * 列表更能发现异常。因此这里展示 `device` / `ip` / `user_agent` 全量字段，
 * 不做脱敏（FE-11 的脱敏只针对日志与令牌，不包括给管理员看的会话信息）。
 *
 * 撤销会话会立刻生效（后端实时计算权限，不依赖缓存）。
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
  listSessions,
  revokeAllUserSessions,
  revokeSession,
} from '@/api/endpoints/organization'
import type { DataTableColumn } from '@/components/data/types'
import type { Session } from '@/types'

const appStore = useAppStore()

const columns: Array<DataTableColumn<Session>> = [
  { key: 'username', title: '用户' },
  { key: 'login_at', title: '登录时间', width: '170px' },
  { key: 'ip', title: 'IP', width: '140px' },
  { key: 'device', title: '设备' },
  { key: 'last_active_at', title: '最后活跃', width: '170px' },
  { key: 'online', title: '状态', width: '90px', align: 'center' },
  { key: 'revoked_at', title: '撤销时间', width: '170px' },
]

const rows = ref<Session[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)
const onlineOnly = ref(false)
const selected = ref<string[]>([])

const pendingRevoke = ref<Session | null>(null)
const revoking = ref(false)
const pendingRevokeAll = ref<Session | null>(null)
const revokingAll = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listSessions({ pageNum: pageNum.value, pageSize: pageSize.value, online: onlineOnly.value })
    rows.value = result.list
    total.value = result.total
    pageNum.value = result.pageNum
    pageSize.value = result.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '会话加载失败'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search(): void {
  pageNum.value = 1
  selected.value = []
  void load()
}

function resetFilters(): void {
  onlineOnly.value = false
  pageNum.value = 1
  selected.value = []
  void load()
}

function onPageChange(next: { pageNum: number; pageSize: number }): void {
  pageNum.value = next.pageNum
  pageSize.value = next.pageSize
  void load()
}

async function confirmRevoke(): Promise<void> {
  const target = pendingRevoke.value
  if (target === null) return
  revoking.value = true
  try {
    await revokeSession(target.id)
    pendingRevoke.value = null
    await load()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '撤销失败')
  } finally {
    revoking.value = false
  }
}

async function confirmRevokeAll(): Promise<void> {
  const target = pendingRevokeAll.value
  if (target === null) return
  revokingAll.value = true
  try {
    await revokeAllUserSessions(target.user_id)
    pendingRevokeAll.value = null
    await load()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '批量撤销失败')
  } finally {
    revokingAll.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageContainer title="会话管理" description="撤销是即时生效的：后端不缓存权限，撤销后下一次请求即被拒绝。">
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">在线状态</span>
        <select v-model="onlineOnly" class="field__control">
          <option value="">全部</option>
          <option value="true">仅在线</option>
        </select>
      </label>
    </SearchForm>

    <div class="toolbar">
      <PermissionButton
        v-if="selected.length > 0"
        code="session:revoke-all"
        danger
        @click="pendingRevokeAll = rows.find((row) => row.id === selected[0]) ?? null"
      >
        批量撤销（{{ selected.length }}）
      </PermissionButton>
      <span class="muted">批量撤销按用户维度生效，而不是按选中的会话逐条撤销</span>
    </div>

    <DataTable
      :columns="columns"
      :rows="rows"
      :loading="loading"
      :error="error"
      :row-key="(row: Session) => row.id"
      selectable
      :selected="selected"
      empty-text="没有会话"
      @selection-change="(keys: string[]) => (selected = keys)"
    >
      <template #cell-online="{ row }">
        <span class="tag" :class="row.online ? 'tag--active' : 'tag--disabled'">
          {{ row.online ? '在线' : '离线' }}
        </span>
      </template>
      <template #cell-device="{ row }">
        <span>{{ row.device ?? '—' }}</span>
        <div class="muted">{{ row.user_agent ?? '' }}</div>
      </template>
      <template #cell-revoked_at="{ row }">
        <span v-if="row.revoked_at !== null" class="tag tag--disabled">
          {{ row.revoked_at }}
          <span v-if="row.revoke_reason !== null">（{{ row.revoke_reason }}）</span>
        </span>
        <span v-else class="muted">—</span>
      </template>
      <template #cell-username="{ row }">
        <div>{{ row.display_name || row.username }}</div>
        <div class="muted">{{ row.username }}</div>
      </template>
    </DataTable>

    <Pagination
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      :disabled="loading"
      @change="onPageChange"
    />

    <ConfirmDialog
      :open="pendingRevoke !== null"
      title="撤销会话"
      danger
      :confirm-text="revoking ? '撤销中…' : '确认撤销'"
      :loading="revoking"
      :description="`该会话的 Refresh Token 将立即失效。若后续复用旧 Refresh Token，后端会按 TOKEN_REUSE_DETECTED 处理（强制登出）。`"
      @cancel="pendingRevoke = null"
      @confirm="confirmRevoke"
    />

    <ConfirmDialog
      :open="pendingRevokeAll !== null"
      title="撤销该用户的全部会话"
      danger
      :confirm-text="revokingAll ? '撤销中…' : '确认撤销全部'"
      :loading="revokingAll"
      :description="`将撤销 ${pendingRevokeAll?.username ?? ''} 名下的所有会话，用户需要重新登录。此操作不可撤销。`"
      @cancel="pendingRevokeAll = null"
      @confirm="confirmRevokeAll"
    />
  </PageContainer>
</template>

