import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/**
 * ESLint flat config。
 *
 * 规则取向：只开"能自动修复 / 有明确对错"的条目，不开风格偏好 ——
 * 本项目把 gates 压在 typecheck 上，lint 的职责是拦住
 * `no-any`、`no-explicit-any`（FE-01 §5 明令业务核心数据禁用 any）
 * 与 `vue/no-v-html`（FE-11 §3：禁止不可信 HTML 直接注入）。
 */
export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'playwright-report/**', 'test-results/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
  },
  {
    files: ['**/*.{ts,mts,tsx,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      // 控制台输出会进日志链路（FE-11 §2：口令 / 令牌 / MFA Secret 不得落日志），
      // 因此连 `console.log` 一并禁掉，只允许 warn / error。
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['**/*.vue'],
    rules: {
      'vue/no-v-html': 'error',
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    files: ['tests/**/*.ts', 'e2e/**/*.ts'],
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
)
