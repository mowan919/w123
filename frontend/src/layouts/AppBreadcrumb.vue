<script setup lang="ts">
/** 面包屑：只显示当前路由 title，不做权限推导（权限来源唯一）。 */
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
const title = computed<string>(() => (route.meta?.title as string | undefined) ?? '')
</script>

<template>
  <nav class="breadcrumb" aria-label="面包屑">
    <RouterLink to="/dashboard">首页</RouterLink>
    <span class="breadcrumb__sep">/</span>
    <span class="breadcrumb__current">{{ title || '当前页面' }}</span>
  </nav>
</template>
