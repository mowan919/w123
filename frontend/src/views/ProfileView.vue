<script setup lang="ts">
/**
 * 个人中心。
 *
 * 只做"关于我自己"的三件事：账号信息、修改口令、两步验证（MFA）。
 * 这三者都不需要任何管理类权限 —— 每个登录用户都能访问自己的这一页，
 * 因此它是**静态路由**（`/profile`），不参与权限契约，也不出现在后端菜单树里。
 *
 * 未做但容易被期待的两项，以及为什么：
 * - "编辑我的手机号/邮箱"：本人改联系方式属于账号资料变更，后端没有
 *   面向本人的写端点（`PUT /admin/users/{id}` 是管理面接口），
 *   前端不能拿管理接口冒充"我的资料"——那会让一个无权管理用户的人
 *   给自己开后门。
 * - "查看我的角色/权限清单"：契约里只有角色 id，没有名称；把 id 列出来
 *   对用户没有意义，显示名称又要额外拉一份角色清单，收益不抵开销。
 */
import { computed, onMounted, ref } from 'vue'
import { NAlert, NButton, NIcon, NTag } from 'naive-ui'
import {
  IdCardOutline,
  InformationCircleOutline,
  KeyOutline,
  QrCodeOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'

import PageContainer from '@/components/layout/PageContainer.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useOrganizationStore } from '@/stores/organization'
import {
  changePassword,
  disableMfa,
  enableMfa,
  getMe,
  getMfaStatus,
  setupMfa,
} from '@/api/endpoints/auth'
import { formatDateTime } from '@/utils/format'
import { PASSWORD_HINT, validatePassword } from '@/utils/validate'
import type { MeResponse, MfaStatusResponse } from '@/types'

const appStore = useAppStore()
const authStore = useAuthStore()
const organizationStore = useOrganizationStore()

/** 账号信息以 `/auth/me` 为准（它包含部门与状态，登录响应里没有）。 */
const me = ref<MeResponse | null>(null)
const meLoading = ref(false)

const departmentName = computed<string>(() => {
  const id = me.value?.department_id ?? null
  if (id === null) return '未分配'
  return organizationStore.options.find((option) => option.id === id)?.label ?? '—'
})

const STATUS_LABEL: Record<MeResponse['status'], string> = {
  ACTIVE: '正常',
  DISABLED: '已禁用',
  LOCKED: '已锁定',
}

async function loadMe(): Promise<void> {
  meLoading.value = true
  try {
    me.value = await getMe()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '账号信息加载失败')
  } finally {
    meLoading.value = false
  }
}

// ---------------------------------------------------------------- 修改口令

const pwdOpen = ref(false)
const pwdSaving = ref(false)
const pwdForm = ref({ current: '', next: '', confirm: '' })

/** 校验规则与后端一致，集中在 `utils/validate` 里，管理面重置口令复用同一份。 */
const pwdError = computed<string | null>(() =>
  pwdForm.value.current === '' && pwdForm.value.next === ''
    ? null
    : validatePassword(pwdForm.value),
)

function openPasswordDialog(): void {
  pwdForm.value = { current: '', next: '', confirm: '' }
  pwdOpen.value = true
}

async function submitPassword(): Promise<void> {
  if (pwdError.value !== null) return
  pwdSaving.value = true
  try {
    await changePassword({ current_password: pwdForm.value.current, new_password: pwdForm.value.next })
    pwdOpen.value = false
    appStore.showNotice('success', '口令已更新')
    // 强制改密被解除后，顶栏的提醒标签必须跟着消失，否则用户会怀疑没生效。
    await authStore.loadMe()
    await loadMe()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '修改口令失败')
  } finally {
    pwdSaving.value = false
  }
}

// ---------------------------------------------------------------- 两步验证

const mfa = ref<MfaStatusResponse | null>(null)
const mfaLoading = ref(false)
/** 绑定流程的中间态：只有拿到 secret 才进入"输入动态码"这一步。 */
const setupInfo = ref<{ secret: string; uri: string } | null>(null)
const mfaDialogOpen = ref(false)
const mfaCode = ref('')
const mfaBusy = ref(false)
/** 关闭两步验证也需要一次动态码，用独立弹窗，避免两种语义挤在一个输入框。 */
const disableOpen = ref(false)

const MFA_STATUS_LABEL: Record<MfaStatusResponse['status'], string> = {
  DISABLED: '未启用',
  SETUP: '已生成密钥，待验证',
  ENABLED: '已启用',
}

async function loadMfa(): Promise<void> {
  mfaLoading.value = true
  try {
    mfa.value = await getMfaStatus()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '两步验证状态加载失败')
  } finally {
    mfaLoading.value = false
  }
}

async function startSetup(): Promise<void> {
  mfaBusy.value = true
  try {
    const result = await setupMfa()
    setupInfo.value = { secret: result.secret, uri: result.provisioning_uri }
    mfaCode.value = ''
    mfaDialogOpen.value = true
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '生成密钥失败')
  } finally {
    mfaBusy.value = false
  }
}

async function confirmEnable(): Promise<void> {
  mfaBusy.value = true
  try {
    await enableMfa({ code: mfaCode.value.trim() })
    mfaDialogOpen.value = false
    setupInfo.value = null
    appStore.showNotice('success', '两步验证已启用')
    await loadMfa()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '启用失败，请核对动态码')
  } finally {
    mfaBusy.value = false
  }
}

async function confirmDisable(): Promise<void> {
  mfaBusy.value = true
  try {
    await disableMfa({ code: mfaCode.value.trim() })
    disableOpen.value = false
    mfaCode.value = ''
    appStore.showNotice('success', '两步验证已关闭')
    await loadMfa()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '关闭失败，请核对动态码')
  } finally {
    mfaBusy.value = false
  }
}

/** 复制密钥：没有剪贴板权限时退回"选中文本让用户手动复制"。 */
async function copySecret(): Promise<void> {
  const secret = setupInfo.value?.secret
  if (secret === undefined) return
  try {
    await navigator.clipboard.writeText(secret)
    appStore.showNotice('success', '密钥已复制')
  } catch {
    appStore.showNotice('info', '浏览器未授权剪贴板，请手动选中密钥复制')
  }
}

onMounted(() => {
  void loadMe()
  void loadMfa()
  // 部门名要靠部门树翻译；取不到只是显示"—"，不影响这一页的任何操作。
  void organizationStore.ensure()
})
</script>

<template>
  <PageContainer
    title="个人中心"
    description="查看自己的账号信息，修改登录口令，管理两步验证。"
    :icon="IdCardOutline"
  >
    <div class="profile-grid">
      <!-- 账号信息 -->
      <section class="panel profile-card">
        <h3 class="panel__title">账号信息</h3>

        <div class="profile-identity">
          <span class="profile-avatar">{{ (authStore.user?.display_name || authStore.user?.username || '?').trim()[0]?.toUpperCase() }}</span>
          <div class="profile-identity__text">
            <div class="profile-identity__name">
              {{ authStore.user?.display_name || '—' }}
              <NTag v-if="me" size="small" :type="me.status === 'ACTIVE' ? 'success' : 'error'" round>
                {{ STATUS_LABEL[me.status] }}
              </NTag>
            </div>
            <div class="muted">@{{ authStore.user?.username ?? '—' }}</div>
          </div>
        </div>

        <p v-if="meLoading" class="muted">加载中…</p>
        <dl v-else-if="me" class="kv profile-kv">
          <dt>账号</dt>
          <dd>{{ me.username }}</dd>
          <dt>姓名</dt>
          <dd>{{ me.display_name }}</dd>
          <dt>所属部门</dt>
          <dd>{{ departmentName }}</dd>
          <dt>口令状态</dt>
          <dd>{{ me.must_change_password ? '需修改' : '正常' }}</dd>
        </dl>

        <NAlert
          v-if="me?.must_change_password || me?.password_expired"
          type="warning"
          :bordered="false"
          class="profile-alert"
        >
          <template #icon>
            <NIcon :component="InformationCircleOutline" />
          </template>
          你的口令已过期或被要求重置，请先修改口令后再使用其他功能。
        </NAlert>
      </section>

      <!-- 修改口令 -->
      <section class="panel profile-card">
        <h3 class="panel__title">
          <span><NIcon :component="KeyOutline" /> 登录口令</span>
          <NButton size="small" type="primary" @click="openPasswordDialog">修改口令</NButton>
        </h3>
        <p class="muted">
          口令{{ PASSWORD_HINT }}；最近使用过的口令不可重复使用。
        </p>
      </section>

      <!-- 两步验证 -->
      <section class="panel profile-card profile-card--wide">
        <h3 class="panel__title">
          <span><NIcon :component="ShieldCheckmarkOutline" /> 两步验证</span>
          <NButton
            v-if="mfa && (mfa.status === 'DISABLED' || mfa.status === 'SETUP')"
            size="small"
            type="primary"
            :loading="mfaBusy"
            @click="startSetup"
          >
            {{ mfa.status === 'SETUP' ? '重新生成密钥' : '启用两步验证' }}
          </NButton>
          <NButton
            v-else-if="mfa && mfa.status === 'ENABLED'"
            size="small"
            :loading="mfaBusy"
            :disabled="mfa.required"
            @click="
              () => {
                mfaCode = ''
                disableOpen = true
              }
            "
          >
            关闭两步验证
          </NButton>
        </h3>

        <p v-if="mfaLoading" class="muted">加载中…</p>
        <template v-else-if="mfa">
          <div class="profile-tags">
            <NTag :type="mfa.status === 'ENABLED' ? 'success' : 'default'" round>
              {{ MFA_STATUS_LABEL[mfa.status] }}
            </NTag>
            <NTag v-if="mfa.required" type="warning" round>系统要求启用</NTag>
            <NTag v-if="mfa.provider" round>{{ mfa.provider }}</NTag>
          </div>

          <dl class="kv profile-kv">
            <dt>绑定时间</dt>
            <dd>{{ formatDateTime(mfa.setup_at) }}</dd>
            <dt>启用时间</dt>
            <dd>{{ formatDateTime(mfa.enabled_at) }}</dd>
            <dt>最近验证</dt>
            <dd>{{ formatDateTime(mfa.verified_at) }}</dd>
          </dl>

          <NAlert v-if="mfa.required" type="info" :bordered="false" class="profile-alert">
            <template #icon>
              <NIcon :component="InformationCircleOutline" />
            </template>
            当前系统策略要求启用两步验证，因此不能关闭。如需停用请先调整系统参数。
          </NAlert>
          <p v-else-if="mfa.status === 'DISABLED'" class="muted">
            启用后，登录时除口令外还需要输入认证器上的 6 位动态码。
          </p>
        </template>
      </section>
    </div>

    <!-- 修改口令 -->
    <FormDialog
      :open="pwdOpen"
      title="修改登录口令"
      :loading="pwdSaving"
      :error="pwdError"
      confirm-text="确认修改"
      @cancel="pwdOpen = false"
      @submit="submitPassword"
    >
      <div class="form-grid form-grid--single">
        <label class="field">
          <span class="field__label">当前口令</span>
          <input v-model="pwdForm.current" type="password" class="field__control" autocomplete="current-password" />
        </label>
        <label class="field">
          <span class="field__label">新口令</span>
          <input v-model="pwdForm.next" type="password" class="field__control" autocomplete="new-password" />
        </label>
        <label class="field">
          <span class="field__label">确认新口令</span>
          <input v-model="pwdForm.confirm" type="password" class="field__control" autocomplete="new-password" />
        </label>
      </div>
      <p class="hint">修改成功后，本次会话仍然有效；其他设备上的会话不受影响。</p>
    </FormDialog>

    <!-- 绑定动态码 -->
    <FormDialog
      :open="mfaDialogOpen"
      title="启用两步验证"
      :loading="mfaBusy"
      :error="mfaCode.trim() === '' ? '请输入认证器上的 6 位动态码' : null"
      confirm-text="验证并启用"
      @cancel="
        () => {
          mfaDialogOpen = false
          setupInfo = null
        }
      "
      @submit="confirmEnable"
    >
      <p class="muted">在认证器应用（如 Google Authenticator）中扫描二维码，或手动输入下面的密钥：</p>
      <div class="secret">
        <NIcon :component="QrCodeOutline" :size="18" />
        <code class="secret__value">{{ setupInfo?.secret ?? '' }}</code>
        <NButton size="tiny" quaternary @click="copySecret">复制</NButton>
      </div>
      <details class="secret__uri">
        <summary>无法扫码？展开 otpauth 链接</summary>
        <code>{{ setupInfo?.uri ?? '' }}</code>
      </details>
      <label class="field">
        <span class="field__label">动态码</span>
        <input v-model="mfaCode" class="field__control" inputmode="numeric" maxlength="6" placeholder="6 位数字" />
      </label>
      <p class="hint">密钥只在此处显示一次，关闭后无法再次查看。</p>
    </FormDialog>

    <!-- 关闭动态码 -->
    <FormDialog
      :open="disableOpen"
      title="关闭两步验证"
      :loading="mfaBusy"
      :error="mfaCode.trim() === '' ? '请输入当前动态码' : null"
      confirm-text="确认关闭"
      danger
      @cancel="
        () => {
          disableOpen = false
        }
      "
      @submit="confirmDisable"
    >
      <p class="muted">关闭后，仅凭口令即可登录。请输入认证器上的当前动态码以确认是你本人操作。</p>
      <label class="field">
        <span class="field__label">动态码</span>
        <input v-model="mfaCode" class="field__control" inputmode="numeric" maxlength="6" placeholder="6 位数字" />
      </label>
    </FormDialog>
  </PageContainer>
</template>

<style scoped>
.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
  align-items: start;
}

.profile-card {
  margin-bottom: 0;
}

.profile-card--wide {
  grid-column: 1 / -1;
}

.profile-card .panel__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.profile-card .panel__title > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.profile-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.profile-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  flex: 0 0 52px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--vctn-primary) 0%, var(--vctn-primary-hover) 100%);
  color: #fff;
  font-size: 22px;
  font-weight: 600;
}

.profile-identity__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}

.profile-kv dt {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.profile-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.profile-alert {
  margin: 10px 0 0;
}

.secret {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px dashed var(--vctn-border-hover);
  border-radius: var(--vctn-radius);
  background: var(--vctn-fill-muted);
}

.secret__value {
  flex: 1;
  word-break: break-all;
  font-size: 13px;
}

.secret__uri {
  font-size: 12px;
  color: var(--vctn-text-weak);
}

.secret__uri code {
  display: block;
  margin-top: 6px;
  word-break: break-all;
}
</style>
