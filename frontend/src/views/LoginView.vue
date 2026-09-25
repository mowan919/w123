<script setup lang="ts">
/**
 * 登录页（FE-04 §1 / FE-05 MFA）。
 *
 * 流程：`POST /auth/login` → 若要求 MFA → `POST /auth/mfa/verify` → 建立会话。
 * 成功后**不在这里**跳转，而是由路由守卫的"已登录"分支把用户送到目标页
 * （含登录后回跳的原始地址）。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { installDynamicRoutes } from '@/router'
import { sanitizeRedirect } from '@/router/guard'
import { ApiError } from '@/api/errors'

const authStore = useAuthStore()
const permissionStore = usePermissionStore()
const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const code = ref('')
const mfaError = ref<string | null>(null)

const redirectTo = computed<string>(() =>
  sanitizeRedirect((route.query.redirect as string | undefined) ?? null),
)
const mfaRequired = computed(() => authStore.pendingMfa !== null)

async function onSubmit(): Promise<void> {
  mfaError.value = null
  try {
    const result = await authStore.login({ username: username.value, password: password.value })
    if (result === 'mfa_required') return
    await afterAuth()
  } catch (error) {
    authStore.error = error instanceof Error ? error.message : '登录失败'
  }
}

async function onVerifyMfa(): Promise<void> {
  mfaError.value = null
  try {
    await authStore.verifyMfa(code.value)
    await afterAuth()
  } catch (error) {
    mfaError.value = error instanceof ApiError ? error.message : '动态码校验失败'
  }
}

async function afterAuth(): Promise<void> {
  try {
    await permissionStore.load(true)
    installDynamicRoutes(permissionStore.toContract())
  } catch {
    // 权限加载失败也算登录成功：受保护页面会被守卫拦下，
    // 用户至少能看到登录态与错误提示，而不是卡在白屏。
  }
  await router.replace(redirectTo.value)
}
</script>

<template>
  <div class="login">
    <form class="login__card" @submit.prevent="onSubmit">
      <h1 class="login__title">VCTN 管理后台</h1>

      <template v-if="!mfaRequired">
        <label class="field">
          <span class="field__label">用户名</span>
          <input v-model.trim="username" class="field__control" autocomplete="username" required />
        </label>
        <label class="field">
          <span class="field__label">密码</span>
          <input
            v-model="password"
            class="field__control"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <p v-if="authStore.error" class="login__error">{{ authStore.error }}</p>
        <button class="btn btn--primary login__submit" type="submit" :disabled="authStore.loading">
          <span v-if="authStore.loading" class="spinner spinner--sm" aria-hidden="true" />
          登录
        </button>
      </template>

      <template v-else>
        <p class="login__hint">
          登录需要通过二次验证（{{ authStore.pendingMfa?.provider }}）。
          该验证令牌将过期，仅本次登录有效。
        </p>
        <label class="field">
          <span class="field__label">动态验证码</span>
          <input v-model.trim="code" class="field__control" inputmode="numeric" autocomplete="one-time-code" required />
        </label>
        <p v-if="mfaError" class="login__error">{{ mfaError }}</p>
        <button class="btn btn--primary login__submit" type="button" :disabled="authStore.loading" @click="onVerifyMfa">
          <span v-if="authStore.loading" class="spinner spinner--sm" aria-hidden="true" />
          验证并登录
        </button>
      </template>
    </form>
  </div>
</template>

<style scoped>
.login {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--vctn-bg);
}

.login__card {
  width: min(380px, calc(100vw - 32px));
  padding: 28px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.login__title {
  font-size: 20px;
}

.login__hint {
  margin: 0;
  color: var(--vctn-text-weak);
  font-size: 13px;
}

.login__error {
  margin: 0;
  color: var(--vctn-danger);
}

.login__submit {
  justify-content: center;
}
</style>
