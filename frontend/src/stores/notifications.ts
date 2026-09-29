import { defineStore } from 'pinia'
import type { ID, NotificationItem } from '@/types'
import {
  fetchUnreadCount,
  listMyNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '@/api/endpoints/notifications'

/**
 * notificationsStore —— 顶栏消息角标与消息面板（`DESIGN-DECISIONS §32`）。
 *
 * 边界：这个 store 只承载**顶栏**需要的两样东西 ——
 * 未读数与最近若干条消息。消息中心**整页**的分页状态由页面自己持有
 * （它有翻页 / 分类筛选，与顶栏"最近几条"是两个不同的查询）。
 *
 * 之所以不共用一份列表：顶栏面板打开时会用 8 条去查，
 * 如果和整页共用一个 `rows`，打开一次面板就会把消息中心的表格切成 8 行
 * —— 而这不报错，只表现为"翻页坏了"。
 *
 * ⚠️ 必须参与会话级清理（`resetAllSessionState`）：未读数与消息正文都是
 * **按人**的数据。换账号后残留会让下一个用户先看到上一个用户的消息标题
 * —— 与部门树、报表数字同类的一次静默越权展示。
 */

/** 顶栏面板一次展示的条数。 */
export const PANEL_PAGE_SIZE = 8

/** 角标轮询间隔。60 秒：通知不是即时通信，更密的轮询只是白烧请求。 */
export const POLL_INTERVAL_MS = 60_000

export const useNotificationsStore = defineStore('notifications', {
  state: () => ({
    /** 未读总数（角标）。 */
    unread: 0,
    /** 最近若干条（面板）。 */
    recent: [] as NotificationItem[],
    /** 收件箱总条数（面板底部「查看全部」用）。 */
    total: 0,
    loading: false,
    error: null as string | null,
    /** 轮询定时器句柄；不放进响应式之外的模块变量，便于测试断言已清理。 */
    timer: null as number | null,
  }),

  getters: {
    /** 角标文案：0 条时**不显示角标**（而不是显示一个 0）。 */
    badgeText: (state): string => (state.unread > 99 ? '99+' : String(state.unread)),
    hasUnread: (state): boolean => state.unread > 0,
  },

  actions: {
    /**
     * 只刷新未读数（轮询走的路径）。
     *
     * 失败**不写进 `error`**：轮询失败是常态（网络抖动、标签页挂起），
     * 把错误条挂到顶栏会让一次抖动看起来像系统坏了。
     * 失败时保留上一次的数字 —— 角标短暂偏旧，好过突然消失。
     */
    async loadUnreadCount(): Promise<void> {
      try {
        const result = await fetchUnreadCount()
        this.unread = result.unread
      } catch {
        // 刻意吞掉：见方法文档。
      }
    },

    /**
     * 直接写入未读数（消息中心整页查询回来后同步角标）。
     *
     * 为什么要有这个动作，而不是让页面写 `store.unread = page.unread`
     * ------------------------------------------------------------
     * 收件箱列表的响应里**自带** `unread`（后端刻意把两者放同一个响应，
     * 见 `types/notification.ts`）。页面把它写回角标，屏幕上就不会出现
     * "列表页头说 3 条未读、顶栏角标还是 0"这种同屏矛盾。
     *
     * 之所以不嫌麻烦走动作：`unread` 是**按人**的数据，写入点必须可枚举。
     * 直接赋值散落在各个页面里，将来加会话级清理时就会漏掉某一条写入路径。
     * 顺带在这里挡住负值 —— 负数会让 `badgeText` 显示成一个不存在的角标。
     */
    setUnread(value: number): void {
      this.unread = Math.max(0, value)
    },

    /** 拉取面板数据（最近若干条 + 最新未读数）。 */
    async loadPanel(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const page = await listMyNotifications({ pageNum: 1, pageSize: PANEL_PAGE_SIZE })
        this.recent = page.list
        this.total = page.total
        this.unread = page.unread
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '消息加载失败'
      } finally {
        this.loading = false
      }
    },

    /** 把一条标记为已读；随后刷新角标与面板（**乐观不更新**，见下）。 */
    async markRead(notificationId: ID): Promise<void> {
      await markNotificationRead(notificationId)
      // 不做本地乐观更新：后端只在**首次**标记时写 `read_at`，
      // 本地猜一个时间会与后端不一致（同一秒内两次点击就会分叉）。
      // 一次刷新请求换来"界面上的已读时间永远是后端那个值"。
      await Promise.all([this.loadUnreadCount(), this.loadPanel()])
    },

    /** 全部标记为已读。 */
    async markAllRead(): Promise<number> {
      const result = await markAllNotificationsRead()
      await Promise.all([this.loadUnreadCount(), this.loadPanel()])
      return result.updated
    },

    /**
     * 开始轮询未读数。
     *
     * 幂等：已在轮询时不重复起第二个定时器（顶栏在布局切换等场景下
     * 可能被重复挂载，两个定时器会让请求量翻倍且互不知情）。
     */
    startPolling(): void {
      if (this.timer !== null) return
      void this.loadUnreadCount()
      this.timer = window.setInterval(() => {
        void this.loadUnreadCount()
      }, POLL_INTERVAL_MS)
    },

    /** 停止轮询（登出 / 组件卸载）。 */
    stopPolling(): void {
      if (this.timer === null) return
      window.clearInterval(this.timer)
      this.timer = null
    },

    /** 会话级清理：数字与正文都必须清掉（见模块文档）。 */
    reset(): void {
      this.stopPolling()
      this.unread = 0
      this.recent = []
      this.total = 0
      this.loading = false
      this.error = null
    },
  },
})
