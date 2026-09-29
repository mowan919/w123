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
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { DesktopOutline, LogOutOutline, RefreshOutline, TrashOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
import { useDictionaryStore } from '@/stores/dictionaries'
import { useColumnSettings } from '@/composables/useColumnSettings'
import {
  listSessions,
  revokeAllUserSessions,
  revokeSession,
} from '@/api/endpoints/organization'
import { formatDateTime } from '@/utils/format'
import type { DataTableColumn } from '@/components/data/types'
import type { Session } from '@/types'

const appStore = useAppStore()
const dictionaryStore = useDictionaryStore()

const dataColumns: Array<DataTableColumn<Session>> = [
  { key: 'username', title: '用户' },
  { key: 'login_at', title: '登录时间', width: '170px' },
  { key: 'ip', title: 'IP', width: '140px' },
  { key: 'device', title: '设备' },
  { key: 'last_active_at', title: '最后活跃', width: '170px' },
  { key: 'online', title: '状态', width: '90px', align: 'center' },
  { key: 'revoked_at', title: '撤销时间', width: '170px' },
  // 「撤销时间」只说明会话什么时候结束，「撤销原因」才说明**是谁**结束的。
  // 前者是运维信息，后者是安全信息：`TOKEN_REUSE_DETECTED` 意味着有人拿着
  // 已经轮换过的 Refresh Token 重放，这一条不该藏在明细里。
  { key: 'revoke_reason', title: '撤销原因', width: '150px' },
  // 两个过期时间回答的是不同问题：`access_expires_at` 是"这个会话还热着吗"
  // （过期后由 Refresh 续期），`refresh_expires_at` 是"socket 最长还能活多久"
  // （总寿命上界，到点必须重新登录）。只看前者会以为会话永不过期。
  { key: 'access_expires_at', title: 'Access 过期', width: '170px' },
  { key: 'refresh_expires_at', title: '会话上限', width: '170px' },
  { key: 'user_id', title: '用户 ID', width: '200px' },
  { key: 'id', title: '会话 ID', width: '200px' },
]

/**
 * 撤销原因 → 中文文案。取值域是后端 `SessionRevokeReason`。
 *
 * 这份清单现在是**回落**：真正显示的是字典 `session_revoke_reason`
 * （可在字典管理页改字），取不到时才用它。两个来源必须同时存在 ——
 * 只有字典的话，字典一停用这里就是空白；只有清单的话，字典功能等于没用。
 */
const REVOKE_REASON_LABEL: Record<string, string> = {
  LOGOUT: '本人登出',
  ADMIN_REVOKE: '管理员撤销',
  REVOKE_ALL: '强制下线',
  TOKEN_REUSE_DETECTED: '令牌复用',
  SUPERSEDED: '顶替下线',
}

function revokeReasonLabel(reason: string): string {
  return dictionaryStore.labelOf('session_revoke_reason', reason, REVOKE_REASON_LABEL[reason])
}

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<Session>('sessions', dataColumns)

const rows = ref<Session[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

/**
 * 筛选条件。
 *
 * `status` 显式用三个字符串，而不是布尔 —— 早先这里是
 * `const onlineOnly = ref(false)` 直接绑在 `<select>` 上，于是一个字段同时
 * 装着 `boolean`（`false`）与 `string`（空串 / `"true"`）两种值：
 * "全部"与"仅在线"之所以看起来能用，靠的是"空串刚好为假、`'true'` 刚好为真"
 * 这种巧合。只要有人加一个 `value="false"`（字符串，也是真）就会立刻错乱。
 * 这里把三态写成三态，再在发请求时映射成后端的 `null / true / false`。
 */
const statusFilter = ref<'' | 'online' | 'offline'>('')
const ipFilter = ref('')
const systemFilter = ref('')

/** 登录时间区间边界（`YYYY-MM-DD`，本地日期）。空串表示该端不限。 */
const loginFrom = ref('')
const loginTo = ref('')

const selected = ref<string[]>([])

const pendingRevoke = ref<Session | null>(null)
const revoking = ref(false)
const pendingRevokeAll = ref<Session | null>(null)
const revokingAll = ref(false)

const loginRangeInvalid = computed<boolean>(
  () => loginFrom.value !== '' && loginTo.value !== '' && loginFrom.value > loginTo.value,
)

/**
 * 本地日期 → 当天的起点 / 终点，再转成 UTC 的 ISO 8601。
 *
 * `<input type="date">` 给的是**本地**日期，而 `login_at` 是 UTC 时间戳。
 * 直接拼 `T00:00:00Z` 会把"本地的 9 月 1 日"当成"UTC 的 9 月 1 日"，
 * 在东八区就是漏掉 8 小时的数据（表现为"选了昨天却查不到昨天的登录"）。
 * 因此这里先构造本地零点 / 当日末刻，再由 `toISOString()` 做真正的换算。
 *
 * 终止端取 `23:59:59.999` 而不是下一天的零点：后端条件是 `login_at <= login_to`，
 * 用下一天零点会把次日 00:00:00.000 这条也放进来。
 */
function toIsoBoundary(date: string, edge: 'start' | 'end'): string | null {
  if (date === '') return null
  const [year, month, day] = date.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) return null
  if (Number.isNaN(year) || Number.isNaN(month) || Number.isNaN(day)) return null
  const local =
    edge === 'start'
      ? new Date(year, month - 1, day, 0, 0, 0, 0)
      : new Date(year, month - 1, day, 23, 59, 59, 999)
  return local.toISOString()
}

/** 选中的会话对应的用户：批量撤销是"按用户"生效的，先解出用户名再确认。 */
const selectedUser = computed<Session | null>(
  () => rows.value.find((row) => row.id === selected.value[0]) ?? null,
)

function blankToNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listSessions({
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      // 三态：空串 = 全部，必须映射成 null；`false` 在后端是"仅离线"。
      online: statusFilter.value === '' ? null : statusFilter.value === 'online',
      ip: blankToNull(ipFilter.value),
      device: blankToNull(systemFilter.value),
      login_from: toIsoBoundary(loginFrom.value, 'start'),
      login_to: toIsoBoundary(loginTo.value, 'end'),
    })
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
  // 区间反了就如实拒绝，不静默交换两端：静默交换会让用户以为筛的就是他填的区间。
  if (loginRangeInvalid.value) {
    appStore.showNotice('error', '登录时间的起始日期不能晚于结束日期')
    return
  }
  pageNum.value = 1
  selected.value = []
  void load()
}

function resetFilters(): void {
  statusFilter.value = ''
  ipFilter.value = ''
  systemFilter.value = ''
  loginFrom.value = ''
  loginTo.value = ''
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
    selected.value = []
    await load()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '批量撤销失败')
  } finally {
    revokingAll.value = false
  }
}

onMounted(() => {
  void load()
  void dictionaryStore.ensureMany(['session_revoke_reason'])
})
</script>

<template>
  <PageContainer
    title="会话管理"
    description="查看用户的登录会话，撤销后该会话立即失效，用户需要重新登录。"
    :icon="DesktopOutline"
  >
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">在线状态</span>
        <select v-model="statusFilter" class="field__control">
          <option value="">全部</option>
          <option value="online">仅在线</option>
          <option value="offline">仅离线</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">IP</span>
        <input v-model.trim="ipFilter" class="field__control" placeholder="如 192.168" />
      </label>
      <label class="field">
        <span class="field__label">系统 / 浏览器</span>
        <input
          v-model.trim="systemFilter"
          class="field__control"
          placeholder="如 Windows / Chrome"
        />
      </label>
      <label class="field">
        <span class="field__label">登录时间从</span>
        <input v-model="loginFrom" type="date" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">登录时间到</span>
        <input v-model="loginTo" type="date" class="field__control" />
      </label>
    </SearchForm>
    <p v-if="loginRangeInvalid" class="hint">
      起始日期晚于结束日期，修改后再查询（查询会被拒绝，不会静默交换两端）。
    </p>

    <div class="toolbar">
      <NButton size="small" :loading="loading" @click="load">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
      <PermissionButton
        v-if="selected.length > 0"
        code="session:revoke-all"
        danger
        @click="pendingRevokeAll = selectedUser"
      >
        <NIcon :component="LogOutOutline" />
        强制该用户下线（{{ selected.length }}）
      </PermissionButton>
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

    <DataTable
      :columns="visibleColumns"
      :rows="rows"
      :loading="loading"
      :error="error"
      :row-key="(row: Session) => row.id"
      selectable
      :selected="selected"
      empty-text="没有会话"
      actions-title="操作"
      actions-width="130px"
      @selection-change="(keys: string[]) => (selected = keys)"
    >
      <template #cell-online="{ row }">
        <span class="tag" :class="row.online ? 'tag--active' : 'tag--disabled'">
          {{ row.online ? '在线' : '离线' }}
        </span>
      </template>
      <template #cell-login_at="{ row }">
        <span class="muted">{{ formatDateTime(row.login_at) }}</span>
      </template>
      <template #cell-last_active_at="{ row }">
        <span class="muted">{{ formatDateTime(row.last_active_at) }}</span>
      </template>
      <template #cell-device="{ row }">
        <span>{{ row.device ?? '—' }}</span>
        <!-- UA 最长可达 149 字符（实测），整表不折行后会把这列撑到约 700px，
             因此截断显示、完整值放 title。 -->
        <div v-if="row.user_agent !== null" class="muted clip" :title="row.user_agent">
          {{ row.user_agent }}
        </div>
      </template>
      <template #cell-revoked_at="{ row }">
        <span v-if="row.revoked_at !== null" class="tag tag--disabled">
          {{ formatDateTime(row.revoked_at) }}
        </span>
        <span v-else class="muted">—</span>
      </template>
      <template #cell-username="{ row }">
        <div>{{ row.display_name || row.username }}</div>
        <div class="muted">{{ row.username }}</div>
      </template>
      <template #cell-revoke_reason="{ row }">
        <span v-if="row.revoke_reason === null" class="muted">—</span>
        <span
          v-else
          class="tag"
          :class="row.revoke_reason === 'TOKEN_REUSE_DETECTED' ? 'tag--locked' : 'tag--disabled'"
        >
          {{ revokeReasonLabel(row.revoke_reason) || row.revoke_reason }}
        </span>
      </template>
      <template #cell-access_expires_at="{ row }">
        <span class="muted">{{ formatDateTime(row.access_expires_at) }}</span>
      </template>
      <template #cell-refresh_expires_at="{ row }">
        <span class="muted">{{ formatDateTime(row.refresh_expires_at) }}</span>
      </template>
      <template #cell-user_id="{ row }">
        <code class="muted">{{ row.user_id }}</code>
      </template>
      <template #cell-id="{ row }">
        <code class="muted">{{ row.id }}</code>
      </template>

      <template #actions="{ row }">
        <span class="table-actions">
          <PermissionButton
            v-if="row.revoked_at === null"
            code="session:revoke"
            type="text-danger"
            @click="pendingRevoke = row"
          >
            <NIcon :component="TrashOutline" />
            撤销会话
          </PermissionButton>
          <span v-else class="muted">已撤销</span>
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

    <ConfirmDialog
      :open="pendingRevoke !== null"
      title="撤销会话"
      danger
      :confirm-text="revoking ? '撤销中…' : '确认撤销'"
      :loading="revoking"
      :description="`该会话的登录凭证将立即失效，用户需要重新登录。${pendingRevoke === null ? '' : `用户：${pendingRevoke.username}（${pendingRevoke.device ?? '未知设备'}）`}`"
      @cancel="pendingRevoke = null"
      @confirm="confirmRevoke"
    />

    <ConfirmDialog
      :open="pendingRevokeAll !== null"
      title="强制该用户下线"
      danger
      :confirm-text="revokingAll ? '撤销中…' : '确认全部撤销'"
      :loading="revokingAll"
      :description="`将撤销 ${pendingRevokeAll?.username ?? ''} 名下全部会话（不只是当前勾选的这一条），该用户需要重新登录。此操作不可撤销。`"
      @cancel="pendingRevokeAll = null"
      @confirm="confirmRevokeAll"
    />
  </PageContainer>
</template>
