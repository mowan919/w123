<script setup lang="ts">
/**
 * ColumnSettings（列设置）—— 列表页的"显示哪些字段 / 字段顺序"入口。
 *
 * 逻辑在 `useColumnSettings` 里，这里只管交互。之所以拆开：排序与持久化
 * 的边界（列集合变化后如何对账、至少保留一列）是**可单测**的纯逻辑，
 * 混在模板里就只能靠点界面来验证。
 *
 * 用上下按钮而不是拖拽：拖拽在无鼠标（键盘 / 触屏）场景下没有可用替代，
 * 而这个后台的列数最多也就七八个，点两下比拖一次更快也更准。
 */
import { NButton, NCheckbox, NPopover, NTooltip } from 'naive-ui'
import { ArrowDownOutline, ArrowUpOutline, RefreshOutline, SettingsOutline } from '@vicons/ionicons5'
import type { ColumnSettingItem } from '@/composables/useColumnSettings'

const props = withDefaults(
  defineProps<{
    items: ColumnSettingItem[]
    disabled?: boolean
  }>(),
  { disabled: false },
)

const emit = defineEmits<{
  (e: 'toggle', key: string): void
  (e: 'move', key: string, delta: -1 | 1): void
  (e: 'reset'): void
}>()

/** 只剩一列时不允许再取消勾选（`useColumnSettings` 侧也会拒绝，这里只是提前反馈）。 */
function canHide(item: ColumnSettingItem): boolean {
  const visible = props.items.filter((entry) => entry.visible).length
  return !item.visible || visible > 1
}
</script>

<template>
  <NPopover trigger="click" placement="bottom-end" :disabled="props.disabled" class="col-settings__popover">
    <template #trigger>
      <NButton size="small" :disabled="props.disabled" class="col-settings__btn">
        <template #icon>
          <SettingsOutline />
        </template>
        列设置
      </NButton>
    </template>

    <div class="col-settings">
      <div class="col-settings__head">
        <span class="col-settings__title">显示字段与顺序</span>
        <NButton size="tiny" quaternary @click="emit('reset')">
          <template #icon>
            <RefreshOutline />
          </template>
          重置
        </NButton>
      </div>

      <ul class="col-settings__list">
        <li v-for="(item, index) in props.items" :key="item.key" class="col-settings__row">
          <NCheckbox
            :checked="item.visible"
            :disabled="!canHide(item)"
            @update:checked="() => emit('toggle', item.key)"
          >
            {{ item.title }}
          </NCheckbox>

          <span class="col-settings__moves">
            <NTooltip>
              <template #trigger>
                <NButton
                  size="tiny"
                  quaternary
                  :disabled="index === 0"
                  :aria-label="`上移 ${item.title}`"
                  @click="emit('move', item.key, -1)"
                >
                  <template #icon>
                    <ArrowUpOutline />
                  </template>
                </NButton>
              </template>
              上移
            </NTooltip>
            <NTooltip>
              <template #trigger>
                <NButton
                  size="tiny"
                  quaternary
                  :disabled="index === props.items.length - 1"
                  :aria-label="`下移 ${item.title}`"
                  @click="emit('move', item.key, 1)"
                >
                  <template #icon>
                    <ArrowDownOutline />
                  </template>
                </NButton>
              </template>
              下移
            </NTooltip>
          </span>
        </li>
      </ul>

      <p class="col-settings__hint">设置保存在本机浏览器，不影响其他用户。</p>
    </div>
  </NPopover>
</template>

<style scoped>
.col-settings {
  width: 260px;
}

.col-settings__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--vctn-border);
}

.col-settings__title {
  font-weight: 600;
  font-size: 13px;
}

.col-settings__list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  max-height: 280px;
  overflow-y: auto;
}

.col-settings__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
}

.col-settings__moves {
  display: inline-flex;
  gap: 2px;
}

.col-settings__hint {
  margin: 8px 0 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}
</style>
