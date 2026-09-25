<script setup lang="ts" generic="T">
/**
 * DataTable（FE-09 §2）。
 *
 * 统一承载 loading / empty / error / disabled 四态，业务页面不重复判断。
 * 列定义用 `key` 取值而非插槽，是因为分页数据来自后端 DTO，
 * 字段名是冻结契约 —— 走 key 取值能让类型错误在编译期暴露。
 */
import { computed } from 'vue'
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
  }>(),
  { loading: false, error: null, emptyText: '暂无数据', selectable: false, selected: () => [] },
)

const emit = defineEmits<{
  (e: 'row-click', row: T): void
  (e: 'selection-change', keys: string[]): void
}>()

const hasRows = computed(() => props.rows.length > 0)

function cellText(row: T, key: keyof T & string): string {
  const value = row[key]
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div class="data-table">
    <NSpin v-if="props.loading" size="medium" class="data-table__state" description="加载中…">
      <template #default>
        <div class="data-table__state-box" />
      </template>
    </NSpin>

    <NAlert v-else-if="props.error" type="error" :bordered="false" class="data-table__state-alert">
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
            :class="['col-head', column.align === 'right' ? 'is-right' : '', column.align === 'center' ? 'is-center' : '']"
          >
            {{ column.title }}
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
            :class="[column.align === 'right' ? 'is-right' : '', column.align === 'center' ? 'is-center' : '']"
          >
            <slot :name="`cell-${column.key}`" :row="row">
              {{ cellText(row, column.key) }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
