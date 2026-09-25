/**
 * 全站主题 token 的**唯一来源**。
 *
 * 为什么色值放 TS 而不是 CSS
 * --------------------------
 * 页面的视觉由两套东西共同决定：本项目的手写 CSS（用 CSS 变量）与
 * naive-ui 组件（用 `themeOverrides`，只认 JS 值）。若两边各写一份主色，
 * 改色时必然只改一处 —— 这正是本项目踩过的漂移事故（见
 * `docs/DESIGN-DECISIONS.md §19.2`：两个种子脚本各写一份清单）。
 *
 * 因此这里定义**一次**，再分两路导出：
 *
 * 1. `applyCssTokens()` —— 把同一批值写成 `:root` 上的 CSS 变量，供 `base.css`
 *    与视图里的 `var(--vctn-*)` 使用；
 * 2. `naiveThemeOverrides` —— 交给 `NConfigProvider`，让 naive 组件的 Primary
 *    / 圆角 / 阴影 / 字号与手写部分对齐。
 *
 * 新增 token 时只加这里；`base.css` 不再自己维护 `:root` 色值块。
 */

/** 品牌与语义色。命名与 CSS 变量名一一对应（去掉 `--vctn-` 前缀）。 */
export const TOKENS = {
  /** 页面底色（内容区背景）。 */
  bg: '#f4f6fa',
  /** 卡片 / 表格 / 弹窗表面色。 */
  surface: '#ffffff',
  /** 次级表面（表格头、只读控件底色）。 */
  fillMuted: '#f7f9fc',
  /** 三级表面（hover 行、代码块）。 */
  fillSubtle: '#eff3f9',
  /** 常规分隔线。 */
  border: '#e5e9f0',
  /** hover 态边框。 */
  borderHover: '#c9d6ea',
  /** 主文本。 */
  text: '#1c2434',
  /** 次级文本（标签、说明）。 */
  textWeak: '#6b7688',
  /** 禁用 / 占位文本。 */
  textDisabled: '#a3acbb',

  /** 品牌主色。 */
  primary: '#3b6ef6',
  primaryHover: '#5590ff',
  primaryPressed: '#2b56d6',
  /** 主色浅底（选中行、提示块）。 */
  primaryWeak: '#e8effe',

  danger: '#e5484d',
  dangerWeak: '#fdecec',
  warn: '#d97706',
  warnWeak: '#fdf4e3',
  success: '#12a150',
  successWeak: '#e7f6ee',
  info: '#3b6ef6',
  infoWeak: '#e8effe',

  /** 侧边栏（深色）专属配色，与浅色主区分离。 */
  sidebarBg: '#141a29',
  sidebarBgSub: '#1b2334',
  sidebarText: '#aeb8cc',
  sidebarTextActive: '#ffffff',
  sidebarBorder: 'rgba(255, 255, 255, 0.08)',

  radius: '8px',
  radiusSm: '6px',
  radiusLg: '12px',

  shadowSm: '0 1px 2px rgba(16, 24, 40, 0.05)',
  shadowMd: '0 4px 14px rgba(16, 24, 40, 0.08)',
  shadowLg: '0 18px 40px rgba(16, 24, 40, 0.14)',

  /** 统一动效时长，用于让 hover/过渡在全站同步。 */
  motion: '0.16s cubic-bezier(0.4, 0, 0.2, 1)',

  fontFamily:
    "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
} as const

export type TokenName = keyof typeof TOKENS

/** CSS 变量名映射：`radius` → `--vctn-radius`。 */
function cssVarName(name: TokenName): string {
  return `--vctn-${name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`
}

/**
 * 以**小写连字符**形式导出 CSS 变量名，供组件内联样式使用。
 * 这里的转换必须与 `cssVarName` 一致，否则 `var()` 拿不到值。
 */
export const CSS_VARS = Object.fromEntries(
  (Object.keys(TOKENS) as TokenName[]).map((k) => [k, `var(${cssVarName(k)})`]),
) as Record<TokenName, string>

/**
 * 把 token 写成 `:root` 的内联 CSS 变量。
 *
 * 用 **inline style 属性**而不是改写一个 CSS 文件：CSS 文件里的 `:root`
 * 会与这里的写入竞争优先级，而 inline 属性是最终胜利者，能让"TS 是唯一
 * 来源"这条不变量在运行时也成立。
 */
export function applyCssTokens(target: HTMLElement = document.documentElement): void {
  for (const key of Object.keys(TOKENS) as TokenName[]) {
    target.style.setProperty(cssVarName(key), TOKENS[key])
  }
}

/**
 * naive-ui 的主题重写：让组件库与手写 CSS 共用同一套 token。
 *
 * 只覆盖"会影响全局观感"的 common 段；组件级样式（表格头、菜单高亮）
 * 仍由 `base.css` 统一兜底，避免把样式拆成两套维护心智。
 */
export const naiveThemeOverrides = {
  common: {
    primaryColor: TOKENS.primary,
    primaryColorHover: TOKENS.primaryHover,
    primaryColorPressed: TOKENS.primaryPressed,
    primaryColorSuppl: TOKENS.primaryHover,
    errorColor: TOKENS.danger,
    errorColorHover: TOKENS.danger,
    warningColor: TOKENS.warn,
    successColor: TOKENS.success,
    infoColor: TOKENS.info,
    bodyColor: TOKENS.bg,
    cardColor: TOKENS.surface,
    tableHeaderColor: TOKENS.fillMuted,
    borderColor: TOKENS.border,
    textColorBase: TOKENS.text,
    textColor2: TOKENS.textWeak,
    textColor3: TOKENS.textDisabled,
    borderRadius: TOKENS.radius,
    borderRadiusSmall: TOKENS.radiusSm,
    fontFamily: TOKENS.fontFamily,
    fontSize: '14px',
    fontSizeSmall: '13px',
    heightMedium: '34px',
    boxShadow1: TOKENS.shadowSm,
    boxShadow2: TOKENS.shadowMd,
    boxShadow3: TOKENS.shadowLg,
  },
} as const
