import { afterEach, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 测试环境公共前置（FE-12 §2 / FE-12 §3）。
 *
 * 三件事必须每个 spec 之前都做对，否则会出现"上一个测试的状态渗进下一个"：
 *
 * 1. **Pinia 全新实例** —— store 是模块级单例，跨测试残留会让
 *    `isAuthenticated` / `loaded` 这类断言随机翻车（表现为"单独跑绿、
 *    跑全套就红"，最难查的一类）。
 * 2. **localStorage 清空** —— `authStore` 把令牌写进 localStorage，
 *    不清就会带着上一个测试的令牌进入下一个用例。
 * 3. **`vi.unstubAllGlobals()`** —— 各 spec 会 `stubGlobal('fetch', ...)` 敲
 *    一个假后端；不还原会让下一个文件继续用上假的 fetch。
 */

beforeEach(() => {
  setActivePinia(createPinia())
  window.localStorage.clear()
})

afterEach(() => {
  window.localStorage.clear()
  vi.unstubAllGlobals()

  // 清理被传送到 body 上的组件容器（naive 的 Modal / Message / Drawer）。
  // teleport 出来的节点**不会**随 wrapper.unmount() 消失，留着就会在下一个
  // 用例里继续响应 "[role=dialog]" 这类文档级查询 —— 表现为"单独跑绿、
  // 全套跑就偶尔多出一个弹窗"，是最难复现的一类污染。
  for (const selector of [
    '.n-modal-container',
    '.n-message-container',
    '.n-notification-container',
    '.n-drawer-container',
  ]) {
    document.body.querySelectorAll(selector).forEach((node) => node.remove())
  }
})
