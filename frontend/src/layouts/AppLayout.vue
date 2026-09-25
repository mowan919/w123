<script setup lang="ts">
/**
 * AppLayout（FE-09 §1）：侧边栏 + 顶栏 + 面包屑 + 页面容器。
 *
 * 布局只做**外壳**。权限判断不在这里 —— 菜单来自后端权限结果
 * （FE-03 §7），越权访问由路由守卫拦到 /403。
 */
import { useAppStore } from '@/stores/app'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import AppBreadcrumb from './AppBreadcrumb.vue'
import NotificationHost from '@/components/feedback/NotificationHost.vue'

const appStore = useAppStore()
</script>

<template>
  <div class="app-layout" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
    <AppSidebar />
    <div class="app-layout__main">
      <AppHeader />
      <AppBreadcrumb />
      <main class="app-layout__content">
        <slot />
      </main>
    </div>
    <NotificationHost />
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: var(--vctn-bg);
}
.app-layout__main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.app-layout__content {
  flex: 1;
  padding: 16px 24px 32px;
  min-width: 0;
}
</style>
