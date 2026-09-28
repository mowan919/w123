import { defineStore } from 'pinia'
import type { StatisticsOverview } from '@/types'
import { getStatisticsOverview } from '@/api/endpoints/statistics'

/**
 * statisticsStore —— 报表页面的数据。
 *
 * ## 为什么必须进"登出清理"清单
 *
 * 这份数据**是被权限过滤过的**：操作者没有的域会以 `accessible: false` 返回。
 * 若缓存跨账号存活，换一个权限更低的账号登录时，页面会先渲染出**上一个人**
 * 看到过的数字（在下一次请求回来之前）—— 一次实打实的聚合数据越权展示，
 * 而且不会有任何报错。因此它和部门树一样，属于 `resetAllSessionState`
 * 必须清掉的那一类，理由见 `frontend/src/router/index.ts`。
 *
 * ## 为什么保留上一次的结果
 *
 * 重新进入报表页时先渲染**旧数字 + 转圈**，而不是清空成骨架屏：
 * 骨架屏会让整页高度塌陷再撑开，肉眼看到的是"页面闪了一下"，
 * 比"数字稍后才更新"更让人怀疑数据是否可信。
 */

export const useStatisticsStore = defineStore('statistics', {
  state: () => ({
    /** 最近一次成功加载的结果；null = 还没成功过。 */
    overview: null as StatisticsOverview | null,
    loading: false,
    error: null as string | null,
    /** 是否至少成功加载过一次（用于区分"首次加载"与"刷新失败"）。 */
    loaded: false,
  }),

  getters: {
    /** 生成时刻的本地化显示；未加载时为 null。 */
    generatedAtText(state): string | null {
      if (state.overview === null) return null
      const at = new Date(state.overview.generated_at)
      if (Number.isNaN(at.getTime())) return null
      return at.toLocaleString('zh-CN', { hour12: false })
    },
  },

  actions: {
    /**
     * 加载统计概览。
     *
     * `force=false` 且已成功加载过时直接返回 —— 页面之间的来回切换
     * 不该每次都打一次聚合查询（后端那条要跑 8 条 COUNT）。
     * 需要最新数字时传 `force=true`（刷新按钮 / 手动重试）。
     */
    async load(force = false): Promise<void> {
      if (this.loaded && !force && this.overview !== null) return
      this.loading = true
      this.error = null
      try {
        this.overview = await getStatisticsOverview()
        this.loaded = true
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '统计数据加载失败'
        // 刻意**不清空** `overview`：刷新失败时保留上一次的数字，
        // 并同时显示错误 —— 比空屏更有用（空屏无法区分"没权限"与"请求挂了"）。
      } finally {
        this.loading = false
      }
    },

    /** 强制重新拉取（登出清理之外的唯一入口）。 */
    async refresh(): Promise<void> {
      await this.load(true)
    },

    reset(): void {
      this.overview = null
      this.loading = false
      this.error = null
      this.loaded = false
    },
  },
})
