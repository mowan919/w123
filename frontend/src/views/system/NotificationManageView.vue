<script setup lang="ts">
/**
 * 通知管理 —— 发布 / 撤回管理员公告（`DESIGN-DECISIONS §32`）。
 *
 * 与顶栏铃铛指向的消息中心（`/notifications`）是**两页两个方向**
 * ------------------------------------------------------------
 * | 页面 | 看的是 | 权限 |
 * |---|---|---|
 * | `/notifications`（消息中心） | 我**收到**了什么 | 无（静态路由，人人可达） |
 * | 本页（`/system/notifications`） | 我**发给**了谁 | `notification:manage:page` |
 *
 * 把它们合成一页会立刻撞上一个矛盾：普通用户能进这一页（他的收件箱在这），
 * 但发布表单不该给他 —— 于是要么整页给权限位（普通用户打不开自己的消息），
 * 要么整页不给（任何登录用户都能发全员公告）。拆开才两边都对。
 *
 * 公告与系统消息的区别
 * -------------------
 * `SYSTEM` 分类的消息由服务端事件产生（被顶下线、口令被重置……），
 * 本页**刻意不提供**"手动补发一条系统消息"的入口：那些事件的文案与跳转
 * 都绑在事件码上（`app/services/notification.py` 的 `SYSTEM_EVENTS`），
 * 放开手写等于把"通知里说的话"与"系统真正做了什么"解耦。
 *
 * 发布后立刻刷新列表而不是前端插一行：公告的 `recipient_count` 由后端
 * 在扇出时统计（受数据范围与账号状态影响），前端猜不出这个数字。
 */
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon, NTag } from 'naive-ui'
import {
  ArrowUndoOutline,
  MegaphoneOutline,
  RefreshOutline,
  SendOutline,
} from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
import { useAppStore } from '@/stores/app'
import { useRolesStore } from '@/stores/roles'
import { useDictionaryStore } from '@/stores/dictionaries'
import { useColumnSettings } from '@/composables/useColumnSettings'
import { listAnnouncements, publishAnnouncement, revokeAnnouncement } from '@/api/endpoints/notifications'
import { formatDateTime } from '@/utils/format'
import {
  ANNOUNCEMENT_AUDIENCE_FALLBACK,
  NOTIFICATION_LEVEL_STYLE,
  notificationLevelStyle,
} from '@/utils/notification'
import type { DataTableColumn } from '@/components/data/types'
import type { Announcement, AnnouncementAudience, NotificationLevel } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const rolesStore = useRolesStore()
const dictionaryStore = useDictionaryStore()

/** 与服务端 `app/models/notification.py` 的常量逐字一致，改了这里也要改那里。 */
const TITLE_MAX = 200
const BODY_MAX = 4000

const dataColumns: Array<DataTableColumn<Announcement>> = [
  { key: 'title', title: '标题' },
  { key: 'level', title: '轻重', width: '90px', align: 'center' },
  { key: 'audience_type', title: '受众', width: '110px' },
  { key: 'recipient_count', title: '收件人数', width: '100px', align: 'center' },
  { key: 'created_by_username', title: '发布人', width: '140px' },
  { key: 'created_at', title: '发布时间', width: '170px' },
  { key: 'body', title: '正文' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<Announcement>('announcements', dataColumns)

/**
 * 本页的列表状态**放在页面里**，不进 `notificationsStore`。
 *
 * 那个 store 承载的是顶栏的"最近 8 条 + 未读数"，与这里的"所有公告分页"
 * 是两个查询。共用一份 `rows` 的表现是：打开一次顶栏面板，这一页的表格
 * 就会被切成 8 行且不报错 —— 用户只会觉得"翻页坏了"。
 */
const rows = ref<Announcement[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<string | null>(null)

interface AnnouncementDraft {
  title: string
  body: string
  level: NotificationLevel
  audience: AnnouncementAudience
  roleId: ID | null
}

function emptyDraft(): AnnouncementDraft {
  return { title: '', body: '', level: 'INFO', audience: 'ALL', roleId: null }
}

const draft = ref<AnnouncementDraft>(emptyDraft())
const draftOpen = ref(false)
const publishing = ref(false)
const pendingRevoke = ref<Announcement | null>(null)
const revoking = ref(false)

/** 轻重下拉：字典优先、回落兜底（与其余列表页同一口径）。 */
const levelOptions = computed(() =>
  dictionaryStore.optionsOr(
    'notification_level',
    (Object.keys(NOTIFICATION_LEVEL_STYLE) as NotificationLevel[]).map((value) => ({
      value,
      label: notificationLevelStyle(value).label,
    })),
  ),
)

const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  const title = draft.value.title.trim()
  if (title === '') return '请填写标题'
  if (title.length > TITLE_MAX) return `标题最多 ${TITLE_MAX} 个字`
  if (draft.value.body.length > BODY_MAX) return `正文最多 ${BODY_MAX} 个字`
  // 受众选了"指定角色"却没选角色 —— 后端会拒（`audience_role_consistent`），
  // 但让用户等一个 422 才看到原因没必要。
  if (draft.value.audience === 'ROLE' && draft.value.roleId === null) return '请选择要接收公告的角色'
  return null
})

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const page = await listAnnouncements({ pageNum: pageNum.value, pageSize: pageSize.value })
    rows.value = page.list
    total.value = page.total
    pageNum.value = page.pageNum
    pageSize.value = page.pageSize
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '公告加载失败'
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

function startPublish(): void {
  draft.value = emptyDraft()
  draftOpen.value = true
}

/** 切换受众时清掉另一支的残留，避免"选了全体却仍带着一个角色 id"。 */
function onAudienceChange(): void {
  if (draft.value.audience === 'ALL') draft.value.roleId = null
}

async function submitPublish(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  publishing.value = true
  try {
    const result = await publishAnnouncement({
      title: current.title.trim(),
      body: current.body.trim() === '' ? null : current.body.trim(),
      level: current.level,
      audience_type: current.audience,
      // `ALL` 时**必须**是 null：后端 CHECK 约束要求两者同时成立，
      // 带一个残留的角色 id 会被库层直接拒掉。
      audience_role_id: current.audience === 'ROLE' ? current.roleId : null,
    })
    draftOpen.value = false
    // 回到第 1 页：新公告一定在最新一页，停在旧页码会让发布者以为没发出去。
    pageNum.value = 1
    await load()
    appStore.showNotice('success', `公告已发布，共 ${result.recipient_count} 人收到`)
  } catch (cause) {
    notice(cause, '发布失败')
  } finally {
    publishing.value = false
  }
}

async function confirmRevoke(): Promise<void> {
  const target = pendingRevoke.value
  if (target === null) return
  revoking.value = true
  try {
    const result = await revokeAnnouncement(target.id)
    pendingRevoke.value = null
    await load()
    appStore.showNotice('success', `公告已撤回，同时收回 ${result.purged} 条已投递消息`)
  } catch (cause) {
    notice(cause, '撤回失败')
  } finally {
    revoking.value = false
  }
}

function levelLabel(level: NotificationLevel): string {
  return dictionaryStore.labelOf(
    'notification_level',
    level,
    notificationLevelStyle(level).label,
  )
}

onMounted(async () => {
  await Promise.all([
    dictionaryStore.ensureMany(['notification_level']),
    rolesStore.ensurePicker(),
  ])
  await load()
})
</script>

<template>
  <PageContainer
    title="通知管理"
    description="向全体或指定角色发布站内公告。发布后立即出现在对方的顶栏消息铃铛里。"
    :icon="MegaphoneOutline"
  >
    <div class="toolbar">
      <PermissionButton code="notification:publish" type="primary" @click="startPublish">
        <NIcon :component="SendOutline" />
        发布公告
      </PermissionButton>
      <NButton size="small" :loading="loading" @click="load">
        <template #icon><NIcon :component="RefreshOutline" /></template>
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

    <DataTable
      :columns="visibleColumns"
      :rows="rows"
      :loading="loading"
      :error="error"
      :row-key="(row: Announcement) => row.id"
      empty-text="还没有发布过公告"
      actions-title="操作"
      actions-width="120px"
    >
      <template #cell-level="{ row }">
        <NTag
          size="small"
          :bordered="false"
          :color="{
            color: notificationLevelStyle(row.level).background,
            textColor: notificationLevelStyle(row.level).color,
          }"
        >
          {{ levelLabel(row.level) }}
        </NTag>
      </template>
      <template #cell-audience_type="{ row }">
        <!--
          受众标签带上角色名。只显示"指定角色"而不说哪个角色，
          看列表的人无法回答"这条是给谁的"—— 而那正是这一列存在的意义。
        -->
        <span>
          {{ ANNOUNCEMENT_AUDIENCE_FALLBACK[row.audience_type] }}
          <span v-if="row.audience_type === 'ROLE'" class="muted">
            （{{ rolesStore.byId.get(row.audience_role_id ?? '')?.role_name ?? '已删除角色' }}）
          </span>
        </span>
      </template>
      <template #cell-recipient_count="{ row }">
        <span :class="row.recipient_count === 0 ? 'muted' : ''">{{ row.recipient_count }}</span>
      </template>
      <template #cell-created_by_username="{ row }">
        <span>{{ row.created_by_username }}</span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ formatDateTime(row.created_at) }}</span>
      </template>
      <template #cell-body="{ row }">
        <span
          class="clip"
          :class="row.body === null || row.body === '' ? 'muted' : ''"
          :title="row.body || undefined"
        >
          {{ row.body === null || row.body === '' ? '—' : row.body }}
        </span>
      </template>

      <template #actions="{ row }">
        <PermissionButton code="notification:revoke" type="text-danger" @click="pendingRevoke = row">
          <NIcon :component="ArrowUndoOutline" />
          撤回
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

    <FormDialog
      :open="draftOpen"
      title="发布公告"
      :loading="publishing"
      :error="draftError"
      :width="640"
      confirm-text="发布"
      @cancel="draftOpen = false"
      @submit="submitPublish"
    >
      <div class="form-grid">
        <label class="field field--full">
          <span class="field__label">标题</span>
          <input
            v-model="draft.title"
            class="field__control"
            :maxlength="TITLE_MAX"
            placeholder="一句话说清这条公告要做什么"
          />
        </label>
        <label class="field">
          <span class="field__label">轻重</span>
          <select v-model="draft.level" class="field__control">
            <option v-for="option in levelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="field">
          <span class="field__label">受众</span>
          <select v-model="draft.audience" class="field__control" @change="onAudienceChange">
            <option value="ALL">全体用户</option>
            <option value="ROLE">指定角色</option>
          </select>
        </label>
        <label v-if="draft.audience === 'ROLE'" class="field field--full">
          <span class="field__label">接收角色</span>
          <select v-model="draft.roleId" class="field__control">
            <option :value="null">请选择角色</option>
            <option v-for="role in rolesStore.picker" :key="role.id" :value="role.id">
              {{ role.role_name }}
            </option>
          </select>
        </label>
        <label class="field field--full">
          <span class="field__label">正文</span>
          <textarea
            v-model="draft.body"
            class="field__control"
            rows="5"
            :maxlength="BODY_MAX"
            placeholder="选填：展开说明。留空时对方只看到标题。"
          />
        </label>
      </div>

      <p class="hint">
        「指定角色」按用户的**角色直接分配**判定，不含角色继承 —— 也就是说，
        通过继承获得该角色的用户不会收到这条公告。
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingRevoke !== null"
      title="撤回公告"
      danger
      :confirm-text="revoking ? '撤回中…' : '确认撤回'"
      :loading="revoking"
      :description="`撤回后这条公告连同已经投递出去的消息一起消失——包括对方已经读过的。标题：${pendingRevoke?.title ?? ''}。`"
      @cancel="pendingRevoke = null"
      @confirm="confirmRevoke"
    />
  </PageContainer>
</template>
