<script setup lang="ts">
/**
 * SearchForm（FE-09 §2）。
 *
 * 只负责"布局 + 查询/重置"这两个动作，字段本身由调用方用插槽给
 * （没有 UI 组件库，硬做一套 field 抽象只会把简单问题复杂化）。
 *
 * 折叠只由**独立的**第三个按钮控制。早先版本把折叠挂在"重置"上，
 * 结果点一次重置会同时触发"筛选被清空"和"面板收起"两件事 ——
 * 用户以为筛选没清掉，其实是面板藏起来了。
 */
import { ref } from 'vue'

const props = withDefaults(defineProps<{ collapsible?: boolean }>(), { collapsible: true })

const emit = defineEmits<{
  (e: 'search'): void
  (e: 'reset'): void
}>()

const collapsed = ref(false)

function toggle(): void {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <section class="search-form">
    <div class="search-form__body" :class="{ 'is-collapsed': collapsed }">
      <slot />
    </div>
    <div class="search-form__actions">
      <button class="btn btn--primary" type="button" @click="emit('search')">查询</button>
      <button class="btn" type="button" @click="emit('reset')">重置</button>
      <button v-if="props.collapsible" class="btn btn--text" type="button" @click="toggle">
        {{ collapsed ? '展开' : '收起' }}
      </button>
    </div>
  </section>
</template>
