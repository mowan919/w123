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
import { NAlert, NButton, NInput } from 'naive-ui'
import { LockClosedOutline, PersonOutline, ShieldCheckmarkOutline } from '@vicons/ionicons5'

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
    <!-- 左侧品牌区：纯装饰，窄屏直接隐藏（登录表单才是唯一任务）。 -->
    <aside class="login__aside" aria-hidden="true">
      <div class="login__brand">
        <span class="login__logo">V</span>
        <span class="login__brand-name">VCTN</span>
      </div>
      <h2 class="login__headline">统一身份与权限<br />管理平台</h2>
      <ul class="login__points">
        <li>角色继承与数据范围下推</li>
        <li>字段级读写权限控制</li>
        <li>全链路审计留痕</li>
      </ul>
      <div class="login__glass" />
    </aside>

    <main class="login__main">
      <form class="login__card" @submit.prevent="onSubmit">
        <header class="login__head">
          <h1 class="login__title">{{ mfaRequired ? '二次验证' : '登录' }}</h1>
          <p class="login__subtitle">
            {{ mfaRequired ? '请输入验证器中的动态码' : '使用管理员账号继续' }}
          </p>
        </header>

        <template v-if="!mfaRequired">
          <label class="login__field">
            <span class="login__label">用户名</span>
            <NInput
              v-model:value="username"
              size="large"
              placeholder="请输入用户名"
              autocomplete="username"
              :input-props="{ required: true }"
            >
              <template #prefix>
                <PersonOutline />
              </template>
            </NInput>
          </label>

          <label class="login__field">
            <span class="login__label">密码</span>
            <NInput
              v-model:value="password"
              type="password"
              size="large"
              placeholder="请输入密码"
              show-password-on="click"
              autocomplete="current-password"
              :input-props="{ required: true }"
              @keyup.enter="onSubmit"
            >
              <template #prefix>
                <LockClosedOutline />
              </template>
            </NInput>
          </label>

          <NAlert v-if="authStore.error" type="error" :bordered="false" class="login__alert">
            {{ authStore.error }}
          </NAlert>

          <NButton
            type="primary"
            size="large"
            block
            attr-type="submit"
            :loading="authStore.loading"
            class="login__submit"
          >
            登录
          </NButton>
        </template>

        <template v-else>
          <NAlert type="info" :bordered="false" class="login__alert">
            该账号已开启二次验证（{{ authStore.pendingMfa?.provider }}），验证令牌仅本次登录有效。
          </NAlert>

          <label class="login__field">
            <span class="login__label">动态验证码</span>
            <NInput
              v-model:value="code"
              size="large"
              placeholder="6 位数字"
              inputmode="numeric"
              autocomplete="one-time-code"
              maxlength="8"
              @keyup.enter="onVerifyMfa"
            >
              <template #prefix>
                <ShieldCheckmarkOutline />
              </template>
            </NInput>
          </label>

          <NAlert v-if="mfaError" type="error" :bordered="false" class="login__alert">
            {{ mfaError }}
          </NAlert>

          <NButton
            type="primary"
            size="large"
            block
            :loading="authStore.loading"
            class="login__submit"
            @click="onVerifyMfa"
          >
            验证并登录
          </NButton>
        </template>
      </form>
    </main>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  min-height: 100vh;
  background: var(--vctn-bg);
}

/* ------------------------------------------------------- 左侧品牌区 */

.login__aside {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 28px;
  padding: 56px;
  color: #fff;
  background: linear-gradient(145deg, #17233d 0%, #1d3a8a 55%, var(--vctn-primary) 100%);
}

/* 一层错位的柔光，避免大面积纯渐变显得廉价。 */
.login__glass {
  position: absolute;
  width: 460px;
  height: 460px;
  right: -140px;
  top: -120px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.22) 0%, transparent 62%);
  pointer-events: none;
}

.login__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.login__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.28);
  font-size: 20px;
  font-weight: 700;
}

.login__brand-name {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 2px;
}

.login__headline {
  margin: 0;
  font-size: 34px;
  line-height: 1.35;
  font-weight: 650;
}

.login__points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 14px;
  opacity: 0.88;
}

.login__points li::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 10px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.7);
  vertical-align: middle;
}

/* ------------------------------------------------------- 右侧表单 */

.login__main {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}

.login__card {
  width: min(400px, 100%);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 36px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius-lg);
  box-shadow: var(--vctn-shadow-lg);
}

.login__head {
  margin-bottom: 4px;
}

.login__title {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0.5px;
}

.login__subtitle {
  margin: 6px 0 0;
  color: var(--vctn-text-weak);
  font-size: 13px;
}

.login__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.login__label {
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.login__alert {
  /* naive 的 alert 有默认外边距，放在紧凑表单里会把间距撑松。 */
  margin: 0;
}

.login__submit {
  margin-top: 4px;
  font-weight: 500;
  letter-spacing: 2px;
}

/* 窄屏：品牌区是装饰，砍掉不影响登录这件事本身。 */
@media (max-width: 900px) {
  .login {
    grid-template-columns: 1fr;
  }

  .login__aside {
    display: none;
  }
}
</style>
