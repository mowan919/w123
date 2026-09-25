<script setup lang="ts">
/**
 * PageContainer（FE-09 §1）：统一页头 + 内容区。
 *
 * 标题由**路由 meta** 提供（后端资源名），不在页面里各自写死 ——
 * 这样后端改资源名时，菜单、面包屑、页头三处同时更新。
 */
defineProps<{
  title?: string
  description?: string
}>()
</script>

<template>
  <section class="page-container">
    <header v-if="title" class="page-container__head">
      <h2 class="page-container__title">{{ title }}</h2>
      <p v-if="description" class="page-container__desc">{{ description }}</p>
    </header>
    <div class="page-container__body">
      <slot />
    </div>
  </section>
</template>
