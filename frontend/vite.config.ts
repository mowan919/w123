import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
// 用 vitest/config 的 defineConfig：它同时认识 Vite 与 Vitest 的配置段，
// 用 'vite' 的 defineConfig 写 `test` 段会在 typecheck 时报错。
import { defineConfig } from 'vitest/config'

/**
 * Vite / Vitest 配置。
 *
 * `build.sourcemap`：显式 `false`。FE-11 §6 要求"生产环境 Source Map 策略必须
 * 明确" —— 留默认值本身就是一个未被声明的选择。若日后为了生产排障要打开，
 * 需同时确认其中不含密钥、内部地址与源码中的敏感字符串。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env['VITE_PROXY_TARGET'] ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: false,
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.spec.ts'],
    setupFiles: ['tests/setup.ts'],
    restoreMocks: true,
  },
})
