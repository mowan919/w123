<script setup lang="ts">
/**
 * 消息中心（`DESIGN-DECISIONS §32`）。
 *
 * 为什么是**静态路由**而不是权限契约里的 PAGE
 * -----------------------------------------
 * 这是"我自己的消息"，任何已认证用户都有自己的一份。做成契约页面
 * 会引入一个权限位，然后必须给每个角色都授它 —— 否则新角色 / 空角色
 * （DD-21）的用户连自己的消息都打不开，而报错是 403（看起来像越权，
 * 实际是配置漏了）。`/profile` 与 `/reports` 出于同一理由走静态路由。
 *
 * 页面自己持有分页 / 筛选状态（**不用**顶栏那个 store）：顶栏面板是
 * "最近 8 条"，这里是"整页可翻"。两者共用一个 `rows` 会让打开一次面板
 * 把这里的表格切成 8 行 —— 不报错，只表现为"翻页坏了"。
 * 但**写操作**（标已读 / 全部已读）走顶栏 store，这样角标会同步更新。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NIcon, NTag } from 'naive-ui'
import {
  CheckmarkDoneOutline,
  ChevronForwardOutline,
  MegaphoneOutline,
  NotificationsOutline,
  RefreshOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import Pagination from '@/components/data/Pagination.vue'
import { useAppStore } from '@/stores/app'
import { useDictionaryStore } from '@/stores/dictionaries'
import { useNotificationsStore } from '@/stores/notifications'
import { listMyNotifications } from '@/api/endpoints/notifications'
import { formatDateTime } from '@/utils/format'
import {
  NOTIFICATION_CATEGORY_FALLBACK,
  notificationLevelStyle,
  relativeTime,
} from '@/utils/notification'
import type { NotificationCategory, NotificationItem, NotificationLevel } from '@/types'

const appStore = useAppStore()
const dictionaryStore = useDictionaryStore()
const notificationsStore = useNotificationsStore()
const router = useRouter()

const rows = ref<NotificationItem[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const loading = ref(false)
/** 空串 = 全部（`<select>` 的空选项 value 只能是空串）。 */
const categoryFilter = ref<'' | NotificationCategory>('')
const unreadOnly = ref(false)

/** 分类下拉：字典优先、回落兜底（与其余列表页同一口径）。 */
const categoryOptions = computed(() =>
  dictionaryStore.optionsOr(
    'notification_category',
    (Object.keys(NOTIFICATION_CATEGORY_FALLBACK) as NotificationCategory[]).map((value) => ({
      value,
      label: NOTIFICATION_CATEGORY_FALLBACK[value],
    })),
  ),
)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listMyNotifications({
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      unreadOnly: unreadOnly.value,
      category: categoryFilter.value === '' ? null : categoryFilter.value,
    })
    rows.value = page.list
    total.value = page.total
    pageNum.value = page.pageNum
    pageSize.value = page.pageSize
    // 收件箱与角标同源：列表响应里就带着未读总数，顺手同步给顶栏 store，
    // 免得两个数字（列表页头 vs 顶栏角标）在屏幕上同时出现却不一致。
    notificationsStore.setUnread(page.unread)
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '消息加载失败')
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  categoryFilter.value = ''
  unreadOnly.value = false
  pageNum.value = 1
  void load()
}

/**
 * 筛选条件变化后**必须回到第 1 页**。
 *
 * 不回去的后果是"筛选后列表空了"：在第 3 页把分类改成"公告"，
 * 结果集只有 1 页，而请求还在问第 3 页 —— 用户以为没有公告，其实是有。
 */
function search(): void {
  pageNum.value = 1
  void load()
}

function onPage(event: { pageNum: number; pageSize: number }): void {
  pageNum.value = event.pageNum
  pageSize.value = event.pageSize
  void load()
}

async function onSelect(item: NotificationItem): Promise<void> {
  if (item.read_at === null) {
    try {
      await notificationsStore.markRead(item.id)
    } catch {
      // 标记失败不影响跳转：用户想看到的内容比"已读状态"重要。
      appStore.showNotice('info', '已读状态未能保存，稍后会自动刷新')
    }
  }
  if (item.link !== null && item.link !== '') {
    await router.push(item.link)
  } else {
    await load()
  }
}

async function onMarkAllRead(): Promise<void> {
  try {
    const updated = await notificationsStore.markAllRead()
    appStore.showNotice('success', updated > 0 ? `已标记 ${updated} 条为已读` : '没有未读消息')
    await load()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '操作失败')
  }
}

function levelLabel(level: NotificationLevel): string {
  return dictionaryStore.labelOf(
    'notification_level',
    level,
    notificationLevelStyle(level).label,
  )
}

function categoryLabel(category: NotificationCategory): string {
  return dictionaryStore.labelOf(
    'notification_category',
    category,
    NOTIFICATION_CATEGORY_FALLBACK[category],
  )
}

onMounted(async () => {
  await dictionaryStore.ensureMany(['notification_category', 'notification_level'])
  await load()
})
</script>

<template>
  <PageContainer
    title="消息中心"
    description="系统事件与管理员公告都会出现在这里。点一条即标记为已读并跳转到事发页面。"
    :icon="NotificationsOutline"
  >

    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">分类</span>
        <select v-model="categoryFilter" class="field__control">
          <option value="">全部</option>
          <option v-for="option in categoryOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
      <label class="field field--check">
        <span class="field__label">未读</span>
        <span class="field__check">
          <input v-model="unreadOnly" type="checkbox" />
          <span>只看未读</span>
        </span>
      </label>
    </SearchForm>

    <div class="toolbar">
      <NButton size="small" :loading="loading" @click="load">
        <template #icon><NIcon :component="RefreshOutline" /></template>
        刷新
      </NButton>
      <NButton
        size="small"
        type="primary"
        :disabled="notificationsStore.unread === 0"
        @click="onMarkAllRead"
      >
        <template #icon><NIcon :component="CheckmarkDoneOutline" /></template>
        全部已读
      </NButton>
      <span class="toolbar__end">
        {{
          notificationsStore.unread > 0 ? `${notificationsStore.unread} 条未读` : '全部已读'
        }}
      </span>
    </div>

    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="rows.length === 0" class="state">暂时没有消息</div>

    <ul v-else class="cards">
      <li v-for="item in rows" :key="item.id">
        <button
          type="button"
          class="card"
          :class="{ 'card--unread': item.read_at === null }"
          @click="onSelect(item)"
        >
          <span class="card__icon" :style="{ color: notificationLevelStyle(item.level).color }">
            <NIcon
              :component="item.category === 'ANNOUNCEMENT' ? MegaphoneOutline : ShieldCheckmarkOutline"
              :size="20"
            />
          </span>
          <span class="card__main">
            <span class="card__head">
              <span class="card__title">{{ item.title }}</span>
              <NTag
                size="small"
                :bordered="false"
                :color="{
                  color: notificationLevelStyle(item.level).background,
                  textColor: notificationLevelStyle(item.level).color,
                }"
              >
                {{ levelLabel(item.level) }}
              </NTag>
            </span>
            <span v-if="item.body" class="card__body">{{ item.body }}</span>
            <span class="card__meta">
              <span>{{ categoryLabel(item.category) }}</span>
              <span>{{ formatDateTime(item.created_at) }}</span>
              <span>{{ relativeTime(item.created_at) }}</span>
              <span v-if="item.read_at === null" class="card__unread">未读</span>
            </span>
          </span>
          <span v-if="item.link" class="card__go">
            <NIcon :component="ChevronForwardOutline" :size="16" />
          </span>
        </button>
      </li>
    </ul>

    <Pagination
      v-if="total > 0"
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      @change="onPage"
    />
  </PageContainer>
</template>

<style scoped>
/* 「只看未读」的对齐：`.field` 的其它控件高度约 32px，
   把复选框撑到同一行高度才不会让筛选区上下错位。 */
.field__check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 160px;
  height: 32px;
}

.state {
  padding: 48px 0;
  text-align: center;
  color: var(--vctn-text-weak);
}

.cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  background: var(--vctn-surface);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--vctn-motion);
}

.card:hover {
  border-color: var(--vctn-border-hover);
}

/* 未读的左侧色条：列表是纵向长条，左边一条竖线比整块淡底更容易扫。 */
.card--unread {
  border-left: 3px solid var(--vctn-primary);
}

.card--unread .card__title {
  font-weight: 600;
}

.card__icon {
  flex: 0 0 auto;
  padding-top: 2px;
}

.card__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card__title {
  font-size: 14px;
}

.card__body {
  color: var(--vctn-text-weak);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.card__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.card__unread {
  color: var(--vctn-danger);
}

.card__go {
  flex: 0 0 auto;
  align-self: center;
  color: var(--vctn-text-weak);
}
</style>
