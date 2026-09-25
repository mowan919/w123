<script setup lang="ts">
/** 顶栏：当前身份、强制改密提示、登出入口。 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { resetAllSessionState } from '@/router'
import { logout } from '@/api/endpoints/auth'

const authStore = useAuthStore()
const router = useRouter()

const displayName = computed<string>(() => authStore.user?.display_name || authStore.user?.username || '')

async function onLogout(): Promise<void> {
  await logout().catch(() => undefined)
  resetAllSessionState()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <header class="app-header">
    <div class="app-header__who">
      <span class="app-header__name">{{ displayName }}</span>
    </div>
    <div class="app-header__right">
      <span v-if="authStore.mustChangePassword" class="app-header__badge app-header__badge--warn">
        需先修改密码
      </span>
      <button class="btn btn--text" type="button" @click="onLogout">退出登录</button>
    </div>
  </header>
</template>
