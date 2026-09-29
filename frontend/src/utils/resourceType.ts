import type { ResourceType } from '@/types'
import { CSS_VARS } from '@/styles/theme'

/**
 * 资源类型的视觉表达。
 *
 * 为什么要单独一个模块而不是在视图里写 `switch`
 * --------------------------------------------
 * 同一份配色要在**四个地方**渲染：资源列表的「类型」列、资源树的类型标签、
 * 授权树里的资源组名、以及与行数不清的将来新增视图。散在各处写 `switch`
 * 时，"少配一种类型"不会报错 —— 只是那一行渲染成默认灰。
 *
 * 这里用 `Record<ResourceType, ...>` 而不是带 fallback 的函数：
 * 新增第六种类型时**类型标注会直接编译失败**，逼着补色，
 * 而不是悄悄退化成灰色（这正是引入了
 * `docs/DESIGN-DECISIONS.md §19.2` 那种"清单各写一份"的漂移）。
 */

export interface ResourceTypeStyle {
  /** 文字色。 */
  color: string
  /** 底色（同色系浅底，保证深/浅底上都读得清）。 */
  background: string
  /** 中文标签：替代品还没到位时，至少让列表读起来是人话。 */
  label: string
}

export const RESOURCE_TYPE_STYLE: Record<ResourceType, ResourceTypeStyle> = {
  PAGE: { color: CSS_VARS.kindPage, background: CSS_VARS.kindPageWeak, label: '页面' },
  MENU: { color: CSS_VARS.kindMenu, background: CSS_VARS.kindMenuWeak, label: '菜单' },
  BUTTON: { color: CSS_VARS.kindButton, background: CSS_VARS.kindButtonWeak, label: '按钮' },
  API: { color: CSS_VARS.kindApi, background: CSS_VARS.kindApiWeak, label: '接口' },
  FIELD: { color: CSS_VARS.kindField, background: CSS_VARS.kindFieldWeak, label: '字段' },
}

/** 取某一类型的样式。类型来自后端，但值域是封闭的五种。 */
export function resourceTypeStyle(type: ResourceType): ResourceTypeStyle {
  return RESOURCE_TYPE_STYLE[type]
}
