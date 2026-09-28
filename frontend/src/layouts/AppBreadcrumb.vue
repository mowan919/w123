<script setup lang="ts">
/**
 * 面包屑：只显示当前路由 title，不做权限推导（权限来源唯一）。
 *
 * "首页"指向 `HOME_PATH`（报表页）而不是写死路径：默认落地页将来若再改，
 * 这里漏改就会出现"面包屑回首页把你带到另一个地方"。
 */
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { HOME_PATH } from '@/router/guard'

const route = useRoute()
const title = computed<string>(() => (route.meta?.title as string | undefined) ?? '')
</script>

<template>
  <nav class="breadcrumb" aria-label="面包屑">
    <RouterLink :to="HOME_PATH">首页</RouterLink>
    <span class="breadcrumb__sep">/</span>
    <span class="breadcrumb__current">{{ title || '当前页面' }}</span>
  </nav>
</template>
