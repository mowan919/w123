<script setup lang="ts">
/**
 * 统一状态组件（FE-09 §2 / §5）：loading / empty / error。
 * 三个合在一个文件里，理由是它们共享同样的"容器 + 文案"结构，
 * 分开写会产生三份几乎相同的模板。
 *
 * 视觉交给 naive 的 `NSpin` / `NEmpty` / `NResult`：它们自带无障碍语义
 * （role=status / 空态图标），比手写的一个 `.spinner` 信息量大得多。
 * props 与插槽契约保持不变，业务页面无需改动。
 */
import { NEmpty, NResult, NSpin } from 'naive-ui'

const props = withDefaults(
  defineProps<{
    loading?: boolean
    error?: string | null
    empty?: boolean
    emptyText?: string
  }>(),
  { loading: false, error: null, empty: false, emptyText: '暂无数据' },
)
</script>

<template>
  <div class="state">
    <NSpin v-if="props.loading" size="medium" class="state__spin" description="加载中…">
      <template #default>
        <!-- NSpin 需要一个默认插槽才有高度，这里给它一个占位。 -->
        <div class="state__spin-box" />
      </template>
    </NSpin>

    <NResult v-else-if="props.error" status="error" :title="props.error" size="small" class="state__result" />

    <NEmpty v-else-if="props.empty" :description="props.emptyText" size="medium" class="state__empty" />

    <slot v-else />
  </div>
</template>

<style scoped>
.state {
  padding: 32px 20px;
}

.state__spin,
.state__spin-box {
  display: block;
}

.state__spin-box {
  height: 96px;
}

/* NResult / NEmpty 自带较大的外边距，放进卡片里会把容器撑得比例失衡。 */
.state__result,
.state__empty {
  padding: 12px 0;
}
</style>
