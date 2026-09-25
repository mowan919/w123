/**
 * 数据展示类组件的共享类型。
 *
 * 单独放在 `.ts` 里而不是写在 `<script setup>` 中：`script setup` 块
 * **不允许** ES module 导出（编译器会直接报错），类型声明必须落在普通模块里，
 * 业务页面才能 `import type { DataTableColumn }`。
 */

export interface DataTableAlign {
  align?: 'left' | 'center' | 'right'
}

export interface DataTableColumn<T> extends DataTableAlign {
  /** 字段名。用 key 取值而不是插槽，能让字段名的笔误在编译期暴露。 */
  key: keyof T & string
  title: string
  width?: string
  /** 该列受字段权限控制时填字段键；未授权时按 HIDDEN 处理。 */
  fieldCode?: string
}
