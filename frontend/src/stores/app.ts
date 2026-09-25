import { defineStore } from 'pinia'

/** appStore：主题、布局、侧边栏折叠等**纯 UI** 状态。 */

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarCollapsed: false,
    /** 全局提示（错误 / 成功），由组件层的 notification 渲染。 */
    notice: null as { type: 'success' | 'error' | 'info'; message: string } | null,
    /** 全局遮罩，用于跨请求的重操作。 */
    busy: false,
  }),

  actions: {
    toggleSidebar(): void {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },

    showNotice(type: 'success' | 'error' | 'info', message: string): void {
      this.notice = { type, message }
    },

    clearNotice(): void {
      this.notice = null
    },

    setBusy(value: boolean): void {
      this.busy = value
    },
  },
})
