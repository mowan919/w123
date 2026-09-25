/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 前缀，默认 `/api/v1`。 */
  readonly VITE_API_BASE_URL?: string
  /** 开发服务器代理目标，默认 `http://127.0.0.1:8000`。 */
  readonly VITE_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/**
 * `.vue` 单文件组件的模块声明。
 *
 * 这里写的是 fallback 声明：项目用 `vue-tsc` 直接解析 SFC，日常开发用不到它。
 * 保留它的价值是让纯 `tsc` / 编辑器未加载插件时不报"找不到模块"。
 * 泛型参数故意用宽类型（`unknown` / `Record<string, unknown>`）而不是 `{}` ——
 * `{}` 会放过 `0`、`""` 这类值，也让 props 检查形同虚设。
 */
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}
