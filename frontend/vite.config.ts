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

    // 超时**必须**显式放宽，不能用默认的 10s / 5s。
    //
    // 这不是"慢就调大"式的敷衍：默认值会在满载机器上把
    // `tests/integration/session.spec.ts` 的 `beforeEach`
    // （装一个假后端 + 做一次真实 `router.replace`）判成超时，
    // 而**一条 hook 超时会让该文件的全部用例连带失败** —— 报出来的错是
    // "Invalid route component"、"Cannot read properties of undefined"，
    // 与真实原因（排队等 CPU）毫无关系。实测 38 个文件并行时，
    // 默认 10s 下该文件 22 条全红、把它们单独跑或放宽超时后 22 条全绿。
    //
    // 每个测试文件都要起一个独立 jsdom 环境并编译整棵依赖图，
    // 文件数增加会把单文件的等待时间推上去（实测 collect 阶段就要 180s+）。
    // 因此这里给的是"排队余量"，不是单条用例的合理耗时。
    hookTimeout: 60_000,
    testTimeout: 30_000,
  },
})
