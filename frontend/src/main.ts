import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router, installHttpClient } from './router'
import { useAuthStore } from './stores/auth'
import { usePermissionStore } from './stores/permission'
import './styles/base.css'
import { applyCssTokens } from './styles/theme'

// token 必须在 mount 之前落到 DOM 上：它是**内联到 `:root` 的**，优先级高于
// 任何 CSS 选择器，因此"TS 是唯一色值来源"这条在运行时也成立。
applyCssTokens()

const app = createApp(App)
app.use(createPinia())

// HTTP Client 必须晚于 Pinia 安装：它的 AuthBridge 直接引用 store 单例。
installHttpClient()

// 恢复持久化令牌：只恢复令牌，**不**把 user 填回来 —— 用户身份必须由
// `GET /auth/me` 与 `GET /auth/permissions` 在服务端确认后才有意义。
useAuthStore().restorePersistedTokens()

// 权限集合不能在启动时就信 localStorage：它由后端每次计算。
// 这里只启动加载；真正"该不该进页面"由路由守卫判定。
void usePermissionStore().load().catch(() => undefined)

app.use(router)
app.mount('#app')
