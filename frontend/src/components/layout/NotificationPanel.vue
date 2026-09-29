<script setup lang="ts">
/**
 * 消息面板列表（顶栏下拉里的内容，`DESIGN-DECISIONS §32`）。
 *
 * 只做**展示 + 上抛选择**：数据来源、已读的写操作都在顶栏组件与 store 里。
 * 面板是纯展示组件，因此可以被单测直接喂一批数据断言渲染结果，
 * 不需要构造 Pinia、不需要 mock 请求。
 *
 * 三种「未读」的视觉信号是**叠加**而不是三选一：
 * 左侧小圆点（有没有未读）、标题加粗、底色淡染。只用一种时
 * 在浅色屏幕上容易漏看（尤其是小圆点，16px 以下几乎看不见）。
 */
import { NIcon } from 'naive-ui'
import { MegaphoneOutline, ShieldCheckmarkOutline } from '@vicons/ionicons5'
import { useDictionaryStore } from '@/stores/dictionaries'
import {
  NOTIFICATION_CATEGORY_FALLBACK,
  notificationLevelStyle,
  relativeTime,
} from '@/utils/notification'
import type { NotificationItem } from '@/types'

defineProps<{ items: NotificationItem[] }>()
const emit = defineEmits<{
  (e: 'select', notificationId: string): void
}>()

const dictionaryStore = useDictionaryStore()

/**
 * 分类 → 图标。公告是人发的、系统消息是系统产生的事件，
 * 用两个图标让"这条要不要当回事"在没有读标题前就有个判断。
 * 用 `Record` 而非 fallback，理由同 `utils/notification.ts`。
 */
const iconOf = (item: NotificationItem) =>
  item.category === 'ANNOUNCEMENT' ? MegaphoneOutline : ShieldCheckmarkOutline

/** 文案一律"字典优先、回落兜底"（字典是运营可改的数据，可能取不到）。 */
function levelLabel(item: NotificationItem): string {
  return dictionaryStore.labelOf(
    'notification_level',
    item.level,
    notificationLevelStyle(item.level).label,
  )
}

function categoryLabel(item: NotificationItem): string {
  return dictionaryStore.labelOf(
    'notification_category',
    item.category,
    NOTIFICATION_CATEGORY_FALLBACK[item.category],
  )
}

function onSelect(item: NotificationItem): void {
  emit('select', item.id)
}
</script>

<template>
  <ul class="list">
    <li v-for="item in items" :key="item.id">
      <button
        type="button"
        class="row"
        :class="{ 'row--unread': item.read_at === null }"
        @click="onSelect(item)"
      >
        <span class="row__icon" :style="{ color: notificationLevelStyle(item.level).color }">
          <NIcon :component="iconOf(item)" :size="18" />
        </span>
        <span class="row__main">
          <span class="row__title">{{ item.title }}</span>
          <span class="row__meta">
            <span
              class="row__tag"
              :style="{
                color: notificationLevelStyle(item.level).color,
                background: notificationLevelStyle(item.level).background,
              }"
            >
              {{ levelLabel(item) }}
            </span>
            <span class="row__category">{{ categoryLabel(item) }}</span>
            <span class="row__time">{{ relativeTime(item.created_at) }}</span>
          </span>
        </span>
        <!-- 未读圆点放在最右：左对齐的三个信号（图标、加粗、底色）在
             快速滚动时容易混成一个"看起来都差不多"的列表，
             右端一个孤立的点是最容易被扫到的那一个。 -->
        <span v-if="item.read_at === null" class="row__dot" aria-label="未读" />
      </button>
    </li>
  </ul>
</template>

<style scoped>
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 320px;
  overflow-y: auto;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px 8px;
  border: none;
  border-radius: var(--vctn-radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.row:hover {
  background: var(--vctn-fill-subtle);
}

.row--unread {
  background: var(--vctn-primary-weak);
}

.row--unread .row__title {
  font-weight: 600;
}

.row__icon {
  flex: 0 0 auto;
  display: inline-flex;
  padding-top: 2px;
}

.row__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.row__title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.45;
  word-break: break-word;
}

.row__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--vctn-text-weak);
}

.row__tag {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
}

.row__dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--vctn-danger);
}
</style>
