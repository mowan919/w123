<script setup lang="ts">
/**
 * 顶栏：面包屑之外的一切 —— 当前身份、强制改密提示、登出入口、侧栏折叠开关。
 *
 * 折叠开关为什么在这里而不是侧栏里：侧栏被折叠时能点的地方只剩 64px，
 * 展开按钮放进去很容易做成一个几乎点不中的图标。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAvatar,
  NButton,
  NDropdown,
  NTag,
  type DropdownOption,
} from 'naive-ui'
import { MenuOutline } from '@vicons/ionicons5'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { resetAllSessionState } from '@/router'
import { logout } from '@/api/endpoints/auth'

const authStore = useAuthStore()
const appStore = useAppStore()
const router = useRouter()

const displayName = computed<string>(() => authStore.user?.display_name || authStore.user?.username || '')

/** 头像取展示名首字符；中文取第一个字，英文取首字母大写。 */
const initial = computed<string>(() => (displayName.value.trim()[0] ?? '?').toUpperCase())

const userMenu = computed<DropdownOption[]>(() => [
  { key: 'who', label: displayName.value, disabled: true },
  { type: 'divider', key: 'd1' },
  { key: 'logout', label: '退出登录' },
])

async function onLogout(): Promise<void> {
  await logout().catch(() => undefined)
  resetAllSessionState()
  await router.replace({ name: 'login' })
}

function onSelect(key: string): void {
  if (key === 'logout') void onLogout()
}
</script>

<template>
  <header class="app-header">
    <div class="app-header__left">
      <NButton quaternary circle :aria-label="appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" @click="appStore.toggleSidebar()">
        <template #icon>
          <MenuOutline />
        </template>
      </NButton>
      <span class="app-header__name">{{ displayName }}</span>
      <NTag v-if="authStore.mustChangePassword" type="warning" size="small" round>
        需先修改密码
      </NTag>
    </div>

    <div class="app-header__right">
      <NDropdown :options="userMenu" trigger="click" @select="onSelect">
        <button type="button" class="app-header__user">
          <NAvatar round size="small" :style="{ background: 'var(--vctn-primary)' }">
            {{ initial }}
          </NAvatar>
          <span class="app-header__user-name">{{ displayName || '未登录' }}</span>
        </button>
      </NDropdown>
    </div>
  </header>
</template>

<style scoped>
.app-header__left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.app-header__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition:
    background var(--vctn-motion),
    border-color var(--vctn-motion);
}

.app-header__user:hover {
  background: var(--vctn-fill-subtle);
  border-color: var(--vctn-border);
}

.app-header__user:focus-visible {
  outline: 2px solid var(--vctn-primary);
  outline-offset: 1px;
}

.app-header__user-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 窄屏只留头像，名字挤没了反而更糟。 */
@media (max-width: 720px) {
  .app-header__user-name {
    display: none;
  }
}
</style>
