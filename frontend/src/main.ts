import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router, installHttpClient } from './router'
import { bootstrapSession } from './stores/bootstrapSession'
import './styles/base.css'
import { applyCssTokens } from './styles/theme'

// token 必须在 mount 之前落到 DOM 上：它是**内联到 `:root` 的**，优先级高于
// 任何 CSS 选择器，因此"TS 是唯一色值来源"这条在运行时也成立。
applyCssTokens()

const app = createApp(App)
app.use(createPinia())

// HTTP Client 必须晚于 Pinia 安装：它的 AuthBridge 直接引用 store 单例。
installHttpClient()

// 恢复持久化令牌 → 回填身份 → 预加载权限。
//
// 顺序逻辑不写在入口文件里：`bootstrapSession` 有单元测覆盖（漏掉身份回填
// 会立刻变红），而写在 `main.ts` 里的代码任何测试都碰不到。
void bootstrapSession()

app.use(router)
app.mount('#app')
