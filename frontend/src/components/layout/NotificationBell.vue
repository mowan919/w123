<script setup lang="ts">
/**
 * 顶栏消息铃铛 + 角标 + 下拉面板（`DESIGN-DECISIONS §32`）。
 *
 * 位置：个人中心**左侧**。用户原话是"在右上角个人中心那个位置" ——
 * 铃铛与头像同处一个视觉组，但不与头像下拉合并：头像菜单是"我是谁 /
 * 退出"，消息是"有什么事"，两者的点击结果完全不同，合并进一个下拉
 * 会让"想看消息"变成"先点开自己的名字"。
 *
 * 为什么是 NPopover 而不是 NDrawer / 独立页面
 * -----------------------------------------
 * 判据是"看一条消息的成本"：通知大多数时候只是扫一眼标题。
 * 抽屉与整页都要离开当前页面（还带一次路由跳转和一次列表重查），
 * 而面板就在原地 —— 需要完整列表时再点「查看全部」进消息中心。
 *
 * 角标的两个语义细节
 * ----------------
 * 1. **0 条时不显示角标**（不是显示 0）：`NBadge` 的 `show` 用
 *    `hasUnread` 控制。"0"这个角标既占位又提示"你没事"，纯噪音。
 * 2. 上限显示 `99+`：角标宽度固定，四位数会把铃铛挤变形。
 *
 * 面板打开时**重新拉一次**（`@update:show`）：轮询是 60 秒一次，
 * 点开时大概率已经过期；不刷新的话用户会盯着一个旧列表点已读。
 */

import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { NBadge, NIcon, NPopover, NSpin } from 'naive-ui'
import { NotificationsOutline } from '@vicons/ionicons5'

import { useNotificationsStore } from '@/stores/notifications'
import NotificationPanel from '@/components/layout/NotificationPanel.vue'

const store = useNotificationsStore()
const router = useRouter()

const label = computed<string>(() =>
  store.hasUnread ? `消息（${store.unread} 条未读）` : '消息',
)

function onPanelToggle(show: boolean): void {
  if (show) void store.loadPanel()
}

async function onOpenCenter(): Promise<void> {
  await router.push({ name: 'notifications' })
}

/**
 * 窗口重新可见时补一次未读数。
 *
 * 这是轮询之外的必要补充而不是优化：浏览器会**冻结后台标签页的
 * 定时器**（节流到分钟级甚至完全暂停）。于是"最小化一小时后回来"
 * 恰好是角标最旧、也最需要准的那一刻 —— 而那一刻定时器刚被解冻，
 * 下一次轮询还要等一整个间隔。
 */
function onVisibilityChange(): void {
  if (document.visibilityState === 'visible') void store.loadUnreadCount()
}

onMounted(() => {
  store.startPolling()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  store.stopPolling()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <NPopover
    trigger="click"
    placement="bottom-end"
    :width="360"
    :show-arrow="false"
    @update:show="onPanelToggle"
  >
    <template #trigger>
      <button type="button" class="bell" :aria-label="label" :title="label">
        <NBadge
          :value="store.unread"
          :max="99"
          :show="store.hasUnread"
          :offset="[2, 4]"
          type="error"
        >
          <NIcon :component="NotificationsOutline" :size="20" />
        </NBadge>
      </button>
    </template>

    <div class="panel" data-testid="notification-panel">
      <div class="panel__head">
        <span class="panel__title">消息</span>
        <span class="panel__count">{{ store.hasUnread ? `${store.unread} 条未读` : '全部已读' }}</span>
      </div>

      <div v-if="store.loading" class="panel__state">
        <NSpin size="small" />
      </div>
      <div v-else-if="store.error" class="panel__state panel__state--error">{{ store.error }}</div>
      <div v-else-if="store.recent.length === 0" class="panel__state">暂时没有消息</div>

      <NotificationPanel v-else :items="store.recent" @select="store.markRead" />

      <div class="panel__foot">
        <button type="button" class="panel__link" @click="onOpenCenter">查看全部</button>
        <button
          type="button"
          class="panel__link"
          :disabled="!store.hasUnread"
          @click="store.markAllRead()"
        >
          全部已读
        </button>
      </div>
    </div>
  </NPopover>
</template>

<style scoped>
.bell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition:
    background var(--vctn-motion),
    border-color var(--vctn-motion);
}

.bell:hover {
  background: var(--vctn-fill-subtle);
  border-color: var(--vctn-border);
}

.bell:focus-visible {
  outline: 2px solid var(--vctn-primary);
  outline-offset: 1px;
}

.panel__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 4px 4px 10px;
  border-bottom: 1px solid var(--vctn-border);
}

.panel__title {
  font-weight: 600;
}

.panel__count {
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.panel__state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 92px;
  color: var(--vctn-text-weak);
  font-size: 13px;
}

.panel__state--error {
  color: var(--vctn-danger);
}

.panel__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid var(--vctn-border);
}

.panel__link {
  border: none;
  background: none;
  padding: 4px 2px;
  color: var(--vctn-primary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.panel__link:disabled {
  color: var(--vctn-text-weak);
  cursor: not-allowed;
}
</style>
