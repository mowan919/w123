<script setup lang="ts">
/**
 * PageContainer（FE-09 §1）：统一页头 + 内容区。
 *
 * 标题由**路由 meta** 提供（后端资源名），不在页面里各自写死 ——
 * 这样后端改资源名时，菜单、面包屑、页头三处同时更新。
 *
 * `description` 只写**用户视角**的一句话（"这一页能做什么"）。
 * 后端如何实现（数据范围怎么下推、缓存在哪、审计写几张表）不写在页面上：
 * 对使用者它是噪音，也不会因为写着"不参与判权"就少一次 403。
 */
import type { Component } from 'vue'
import { NIcon } from 'naive-ui'

defineProps<{
  title?: string
  description?: string
  /** 页头图标（@vicons 组件）。 */
  icon?: Component
}>()
</script>

<template>
  <section class="page-container">
    <header v-if="title" class="page-container__head">
      <span v-if="icon" class="page-container__icon" aria-hidden="true">
        <NIcon :component="icon" :size="20" />
      </span>
      <div class="page-container__titles">
        <h2 class="page-container__title">{{ title }}</h2>
        <p v-if="description" class="page-container__desc">{{ description }}</p>
      </div>
    </header>
    <div class="page-container__body">
      <slot />
    </div>
  </section>
</template>
