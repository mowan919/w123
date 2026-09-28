<script setup lang="ts" generic="T">
/**
 * DataTable（FE-09 §2）。
 *
 * 统一承载 loading / empty / error / disabled 四态，业务页面不重复判断。
 * 列定义用 `key` 取值而非插槽，是因为分页数据来自后端 DTO，
 * 字段名是冻结契约 —— 走 key 取值能让类型错误在编译期暴露。
 *
 * "操作列"由 `actions-title` 声明，而不是让页面往 `columns` 里塞一个
 * `key: 'actions'` 的假列：那需要把 `key` 断言成 `keyof T`，
 * 等于在类型层面上承认"字段名可以随便写"，本文件开头那条约束就作废了。
 * 操作列也不参与"列设置"——它不是数据字段，隐藏它等于让整张表失去操作入口。
 */
import { computed, useSlots } from 'vue'
import { NAlert, NCheckbox, NEmpty, NSpin } from 'naive-ui'
import type { DataTableColumn } from './types'

const props = withDefaults(
  defineProps<{
    columns: Array<DataTableColumn<T>>
    rows: T[]
    rowKey: (row: T) => string
    loading?: boolean
    error?: string | null
    emptyText?: string
    selectable?: boolean
    selected?: string[]
    /** 传了才渲染操作列；值就是列标题（通常是"操作"）。 */
    actionsTitle?: string | null
    actionsWidth?: string
    /**
     * 操作列对齐，默认**居中**。
     *
     * 左对齐时"编辑 / 重置口令 / 禁用"与只有"编辑"的行各自贴左，
     * 每个动作的横向位置随该行按钮多少而变；居中后每个动作都落在列中轴附近，
     * 纵向扫读时位置稳定，也不会让操作列看起来比数据列更"靠边"。
     */
    actionsAlign?: 'left' | 'center' | 'right'
  }>(),
  {
    loading: false,
    error: null,
    emptyText: '暂无数据',
    selectable: false,
    selected: () => [],
    actionsTitle: null,
    actionsWidth: '220px',
    actionsAlign: 'center',
  },
)

const emit = defineEmits<{
  (e: 'row-click', row: T): void
  (e: 'selection-change', keys: string[]): void
}>()

const hasRows = computed(() => props.rows.length > 0)

const slots = useSlots() as unknown as Record<string, unknown>

/**
 * 该列是否由页面**自定义渲染**（提供了 `cell-<key>` 槽）。
 *
 * 两种渲染方式在"要不要给 `title`"上必须分开处理：
 *
 * - 默认渲染：单元格里就是字段原值，且外面套了 `.clip`（长文本截断），
 *   因此 `title` 直接给原值 —— 截断后悬停即可看到完整内容。
 * - 自定义渲染：画面内容由页面决定。沿用字段原值当提示会**与画面不符** ——
 *   例如 `status` 渲染成"正常"，提示却是 `ACTIVE`；`department_id` 渲染成
 *   部门名，提示却是一串雪花 ID。这种提示比没有提示更糟，所以这里返回
 *   `undefined`，由页面按需自己给。
 */
function hasCustomCell(key: keyof T & string): boolean {
  return Boolean(slots[`cell-${key}`])
}

function cellText(row: T, key: keyof T & string): string {
  const value = row[key]
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function alignClass(align: 'left' | 'center' | 'right' | undefined): string {
  if (align === 'right') return 'is-right'
  if (align === 'center') return 'is-center'
  return ''
}
</script>

<template>
  <div class="data-table">
    <NSpin v-if="props.loading" size="medium" class="data-table__state" description="加载中…">
      <template #default>
        <div class="data-table__state-box" />
      </template>
    </NSpin>

    <NAlert v-else-if="props.error" type="error" :bordered="false" show-icon class="data-table__state-alert">
      {{ props.error }}
    </NAlert>

    <NEmpty v-else-if="!hasRows" :description="props.emptyText" size="medium" class="data-table__state" />

    <table v-else class="data-table__table">
      <thead>
        <tr>
          <th v-if="props.selectable" class="col-select">
            <NCheckbox
              aria-label="全选"
              :checked="props.selected.length === props.rows.length && props.rows.length > 0"
              :disabled="props.rows.length === 0"
              @update:checked="
                (checked: boolean) =>
                  emit('selection-change', checked ? props.rows.map(props.rowKey) : [])
              "
            />
          </th>
          <th
            v-for="column in props.columns"
            :key="column.key"
            :style="{ width: column.width }"
            :class="['col-head', alignClass(column.align)]"
          >
            {{ column.title }}
          </th>
          <th
            v-if="props.actionsTitle"
            class="col-head col-actions"
            :class="alignClass(props.actionsAlign)"
            :style="{ width: props.actionsWidth }"
          >
            {{ props.actionsTitle }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in props.rows" :key="props.rowKey(row)" @click="emit('row-click', row)">
          <td v-if="props.selectable" class="col-select">
            <NCheckbox
              :aria-label="`选择 ${props.rowKey(row)}`"
              :checked="props.selected.includes(props.rowKey(row))"
              @click.stop
              @update:checked="
                (checked: boolean) =>
                  emit(
                    'selection-change',
                    checked
                      ? [...props.selected, props.rowKey(row)]
                      : props.selected.filter((k) => k !== props.rowKey(row)),
                  )
              "
            />
          </td>
          <td
            v-for="column in props.columns"
            :key="column.key"
            :class="alignClass(column.align)"
            :title="hasCustomCell(column.key) ? undefined : cellText(row, column.key)"
          >
            <slot :name="`cell-${column.key}`" :row="row">
              <span class="clip">{{ cellText(row, column.key) }}</span>
            </slot>
          </td>
          <td v-if="props.actionsTitle" class="col-actions" :class="alignClass(props.actionsAlign)">
            <slot name="actions" :row="row" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
