<script setup lang="ts">
/**
 * 根组件：全局 Provider + 路由出口。
 *
 * 为什么 Provider 挂在这里而不是各页按需挂
 * --------------------------------------
 * `useMessage()` / `useDialog()` / `useNotification()` 只能在其 Provider 的
 * **子树内**取到实例。若让页面各自包一层，就会出现"这个页面的提示能用、
 * 那个页面调用即抛错"的偶发事故，而且只在特定页面才暴露。一个根 Provider
 * 让这条约束一次性成立。
 *
 * 这里不放任何权限 / 认证逻辑 —— 那属于路由守卫与 store。
 */
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  NNotificationProvider,
  dateZhCN,
  zhCN,
} from 'naive-ui'

import { naiveThemeOverrides } from '@/styles/theme'
</script>

<template>
  <NConfigProvider :theme-overrides="naiveThemeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <NDialogProvider>
      <NMessageProvider>
        <NNotificationProvider>
          <RouterView />
        </NNotificationProvider>
      </NMessageProvider>
    </NDialogProvider>
  </NConfigProvider>
</template>
