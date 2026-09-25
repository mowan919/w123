<script setup lang="ts">
/**
 * 角色权限配置（FE-05 §1 / `08 §7` / DD-20 / FE-03 §5）。
 *
 * 三类配置分别保存，不搞"一个按钮保存全部"：
 * 1. 四类二元权限（PAGE / MENU / BUTTON / API）—— 提交语义是**整体替换**，
 *    空数组表示清空该类别（其余类别不受影响）。
 * 2. 字段权限四态（VISIBLE / HIDDEN / READ_ONLY / EDITABLE）—— 逐字段提交。
 * 3. 数据范围五值（DD-07 已冻结）。
 *
 * 整批替换意味着"取消一个勾就提交一次"，这与后端 `RolePermissionIdsRequest`
 * 的语义一致；前端不做增量 PATCH，因为后端没有提供该协议。
 *
 * 授权的目标资源清单来自 `/admin/permission-resources`，而不是当前用户的
 * 权限契约 —— 目标角色可能持有当前管理员看不到的资源，
 * 用契约当选项来源会静默丢掉这些资源。
 *
 * 每次保存之后还会按"当前用户是否持有该角色"决定要不要重拉自己的契约：
 * 给自己的角色加权限后界面上立刻出现对应入口，是这个页面该有的行为。
 */
import { computed, ref, watch } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
import { usePermissionStore } from '@/stores/permission'
import { useOrganizationStore } from '@/stores/organization'
import { useRolesStore } from '@/stores/roles'
import { useResourcesStore } from '@/stores/resources'
import {
  getRoleDataScope,
  getRolePermissions,
  setRoleApiPermissions,
  setRoleButtonPermissions,
  setRoleDataScope,
  setRoleFieldPermissions,
  setRoleMenuPermissions,
  setRolePagePermissions,
} from '@/api/endpoints/roles'
import type {
  DataScopePolicy,
  FieldAccessLevel,
  PermissionResource,
  Role,
  RolePermissionView,
} from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const permissionStore = usePermissionStore()
const organizationStore = useOrganizationStore()
const rolesStore = useRolesStore()
const resourcesStore = useResourcesStore()

type ResourceKind = 'PAGE' | 'MENU' | 'BUTTON' | 'API'

const DATA_SCOPE_OPTIONS: Array<{ value: DataScopePolicy; label: string }> = [
  { value: 'ALL', label: '全部数据' },
  { value: 'DEPARTMENT', label: '本部门' },
  { value: 'DEPARTMENT_CHILDREN', label: '本部门及下级' },
  { value: 'SELF', label: '仅本人' },
  { value: 'CUSTOM', label: '自定义部门集合' },
]

const FIELD_LEVELS: FieldAccessLevel[] = ['VISIBLE', 'HIDDEN', 'READ_ONLY', 'EDITABLE']

const selectedRoleId = ref<ID | null>(null)

const checked = ref<Record<ResourceKind, Set<ID>>>({
  PAGE: new Set(),
  MENU: new Set(),
  BUTTON: new Set(),
  API: new Set(),
})

const fieldLevels = ref<Record<ID, FieldAccessLevel>>({})

const dataScope = ref<DataScopePolicy>('ALL')
const customDepartments = ref<ID[]>([])

const loadingConfig = ref(false)
const saving = ref<ResourceKind | 'FIELDS' | 'DATA_SCOPE' | null>(null)
const pendingReset = ref(false)
const confirmText = ref('')

/**
 * 授权用的候选清单来自 store，不是当前用户的权限契约。
 *
 * 原因写在 resourcesStore 里：被授权的角色可能持有当前管理员看不到的资源，
 * 拿契约当候选来源会静默丢掉它们。
 */
const options = computed<Record<ResourceKind, PermissionResource[]>>(() => ({
  PAGE: resourcesStore.grantable?.PAGE ?? [],
  MENU: resourcesStore.grantable?.MENU ?? [],
  BUTTON: resourcesStore.grantable?.BUTTON ?? [],
  API: resourcesStore.grantable?.API ?? [],
}))

/** 字段权限的四个选项定义在 store 之外是因为它同时被下拉框复用。 */
const grantable = computed<PermissionResource[]>(() => resourcesStore.grantable?.FIELD ?? [])

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

/** 角色清单来自 store：它与角色管理页共享同一份缓存，不各自发请求。 */
const roles = computed<Role[]>(() => rolesStore.picker)

async function loadRoles(): Promise<void> {
  await rolesStore.ensurePicker()
  if (selectedRoleId.value === null && roles.value.length > 0) {
    selectedRoleId.value = roles.value[0]?.id ?? null
  }
}

async function loadResources(): Promise<void> {
  await resourcesStore.ensureGrantable()
}

function toIdSet(ids: ID[]): Set<ID> {
  return new Set(ids)
}

function applyView(view: RolePermissionView): void {
  checked.value = {
    PAGE: toIdSet(view.page_ids),
    MENU: toIdSet(view.menu_ids),
    BUTTON: toIdSet(view.button_ids),
    API: toIdSet(view.api_ids),
  }
  const levels: Record<ID, FieldAccessLevel> = {}
  // `field_levels` 的键是 FIELD 资源 ID（后端 `RolePermissionViewResponse` 明确说明）。
  for (const [resourceId, level] of Object.entries(view.field_levels)) {
    levels[resourceId] = level
  }
  fieldLevels.value = levels
}

async function loadConfig(roleId: ID): Promise<void> {
  loadingConfig.value = true
  try {
    const [view, scope] = await Promise.all([getRolePermissions(roleId), getRoleDataScope(roleId)])
    applyView(view)
    dataScope.value = scope.data_scope
    customDepartments.value = [...scope.department_ids]
  } catch (cause) {
    notice(cause, '权限配置加载失败')
  } finally {
    loadingConfig.value = false
  }
}

/**
 * 部门树在这里只是"选择 CUSTOM 集合"的候选来源，不参与任何判权。
 *
 * 数据与部门管理页共用同一份缓存（`organizationStore`），因此这里失败时
 * 页面也不会崩 —— 顶多是 CUSTOM 那一组的复选框列不出来。
 */
async function loadDepartments(): Promise<void> {
  await organizationStore.ensure()
}

/** 切换角色前先确认：当前批次的勾选还没保存。 */
function beforeSelect(roleId: ID): void {
  confirmText.value = '切换角色会丢弃当前未保存的勾选。'
  pendingReset.value = true
  selectedRoleId.value = roleId
}

function cancelSelect(): void {
  pendingReset.value = false
  if (selectedRoleId.value !== null) void loadConfig(selectedRoleId.value)
}

function toggle(kind: ResourceKind, id: ID): void {
  const current = checked.value[kind]
  const next = new Set(current)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  checked.value = { ...checked.value, [kind]: next }
}

function isChecked(kind: ResourceKind, id: ID): boolean {
  return checked.value[kind].has(id)
}

/**
 * 保存成功后同步一次自己的权限契约（FE-03 §5）。
 *
 * 只在该角色与当前用户有交集时刷 —— 给"别人的角色"配权限却把自己踢回
 * 重新加载，是没法解释的体验问题；但只要有交集就必须刷，否则"刚给自己加了
 * 按钮权限、界面上却没出现"会一直存在。
 */
async function refreshSelfIfAffected(roleId: ID): Promise<void> {
  try {
    await permissionStore.refreshIfHoldsRole([roleId])
  } catch {
    // 保存已经成功，契约同步失败只影响菜单的即时性，不能回滚保存结果。
    appStore.showNotice('info', '保存成功，但权限契约同步失败，刷新页面后生效')
  }
}

async function saveKind(kind: ResourceKind): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null) return
  saving.value = kind
  const ids = [...checked.value[kind]]
  try {
    if (kind === 'PAGE') await setRolePagePermissions(roleId, ids)
    else if (kind === 'MENU') await setRoleMenuPermissions(roleId, ids)
    else if (kind === 'BUTTON') await setRoleButtonPermissions(roleId, ids)
    else await setRoleApiPermissions(roleId, ids)
    appStore.showNotice('success', '已保存')
    await loadConfig(roleId)
    await refreshSelfIfAffected(roleId)
  } catch (cause) {
    notice(cause, '保存失败')
  } finally {
    saving.value = null
  }
}

async function saveFields(): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null) return
  saving.value = 'FIELDS'
  try {
    const fields = Object.entries(fieldLevels.value).map(([resourceId, accessLevel]) => ({
      resourceId,
      accessLevel,
    }))
    await setRoleFieldPermissions(roleId, fields)
    appStore.showNotice('success', '已保存')
    await loadConfig(roleId)
    await refreshSelfIfAffected(roleId)
  } catch (cause) {
    notice(cause, '字段权限保存失败')
  } finally {
    saving.value = null
  }
}

async function saveDataScope(): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null) return
  saving.value = 'DATA_SCOPE'
  try {
    // 非 CUSTOM 必须提交空数组：后端 `RoleDataScopeRequest` 会把非空集合视为
    // "以为已限定、实际未限定"并直接拒绝。
    await setRoleDataScope(roleId, {
      data_scope: dataScope.value,
      department_ids: dataScope.value === 'CUSTOM' ? [...customDepartments.value] : [],
    })
    appStore.showNotice('success', '已保存')
    await loadConfig(roleId)
    await refreshSelfIfAffected(roleId)
  } catch (cause) {
    notice(cause, '数据范围保存失败')
  } finally {
    saving.value = null
  }
}

function toggleDepartment(id: ID): void {
  const next = new Set(customDepartments.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  customDepartments.value = [...next]
}

watch(
  selectedRoleId,
  (value) => {
    if (value !== null) void loadConfig(value)
  },
  { immediate: false },
)

// 契约版本变化意味着"当前管理员看到的权限变了"，此时缓存的授权视图可能已过期。
// 只重置本地提示，不替用户改写任何配置。
const contractVersion = computed<number>(() => permissionStore.version)

watch(contractVersion, () => {
  appStore.showNotice('info', `权限契约已更新到版本 ${contractVersion.value}，请重新加载权限配置后再修改`)
})

async function boot(): Promise<void> {
  await Promise.all([loadRoles(), loadResources(), loadDepartments()])
  const first = selectedRoleId.value
  if (first !== null) await loadConfig(first)
}

void boot()
</script>

<template>
  <PageContainer title="权限配置" description="授权语义为整体替换：保存后该类别只保留当前勾选的资源。">
    <div class="picker">
      <label class="field">
        <span class="field__label">角色</span>
        <select
          class="field__control"
          :value="selectedRoleId ?? ''"
          @change="beforeSelect(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="role in roles" :key="role.id" :value="role.id">
            {{ role.role_name }}（{{ role.role_code }}）
          </option>
        </select>
      </label>
      <PermissionButton code="role:assign-permission" @click="selectedRoleId !== null && loadConfig(selectedRoleId)">
        重新加载
      </PermissionButton>
    </div>
    <p v-if="rolesStore.pickerMightBeTruncated" class="hint">
      角色较多时这份清单可能未取全；找不到目标角色请到「角色管理」页按关键字筛选。
    </p>

    <div v-if="loadingConfig" class="state"><span class="spinner" aria-hidden="true" /><span>加载配置…</span></div>

    <template v-else>
      <section class="panel">
        <h3 class="panel__title">页面 / 菜单 / 按钮 / API 授权</h3>
        <div class="grid">
          <div v-for="kind in (['PAGE', 'MENU', 'BUTTON', 'API'] as ResourceKind[])" :key="kind" class="group">
            <div class="group__head">
              <span>{{ kind }}</span>
              <PermissionButton
                code="role:assign-permission"
                :loading="saving === kind"
                @click="saveKind(kind)"
              >
                保存
              </PermissionButton>
            </div>
            <label v-for="item in options[kind]" :key="item.id" class="check">
              <input
                type="checkbox"
                :checked="isChecked(kind, item.id)"
                @change="toggle(kind, item.id)"
              />
              <span>{{ item.resource_name }}</span>
              <code class="muted">{{ item.resource_code }}</code>
            </label>
            <p v-if="options[kind].length === 0" class="muted">该类别还没有资源</p>
          </div>
        </div>
        <p class="hint">空数组提交表示清空该类别的全部授权；其余类别不受影响。</p>
        <p v-if="resourcesStore.grantableMightBeTruncated" class="hint">
          资源较多时这份清单可能未取全；找不到目标资源请到「权限资源」页按类型筛选。
        </p>
      </section>

      <section class="panel">
        <h3 class="panel__title">字段权限</h3>
        <table class="mini-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>field_key</th>
              <th>访问级别</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="field in grantable" :key="field.id">
              <td>{{ field.resource_name }}</td>
              <td><code>{{ field.field_key }}</code></td>
              <td>
                <select
                  :value="fieldLevels[field.id] ?? 'HIDDEN'"
                  @change="
                    fieldLevels = {
                      ...fieldLevels,
                      [field.id]: ($event.target as HTMLSelectElement).value as FieldAccessLevel,
                    }
                  "
                >
                  <option v-for="level in FIELD_LEVELS" :key="level" :value="level">{{ level }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
        <PermissionButton code="role:assign-permission" :loading="saving === 'FIELDS'" @click="saveFields">
          保存字段权限
        </PermissionButton>
        <p class="hint">
          字段权限的四态由后端再次校验；前端这里的设置只决定"让不让改"，
          HIDDEN 的字段即使被直接提交也会被后端拒绝。
        </p>
      </section>

      <section class="panel">
        <h3 class="panel__title">数据范围（DD-07）</h3>
        <div class="radios">
          <label v-for="option in DATA_SCOPE_OPTIONS" :key="option.value" class="check">
            <input v-model="dataScope" type="radio" :value="option.value" />
            <span>{{ option.label }}</span>
          </label>
        </div>

        <div v-if="dataScope === 'CUSTOM'" class="depts">
          <label
            v-for="dept in organizationStore.flat"
            :key="dept.id"
            class="check"
            :style="{ paddingLeft: `${dept.depth * 18}px` }"
          >
            <input
              type="checkbox"
              :checked="customDepartments.includes(dept.id)"
              @change="toggleDepartment(dept.id)"
            />
            <span>{{ dept.name }}</span>
          </label>
          <p v-if="organizationStore.flat.length === 0" class="muted">部门树加载失败，无法配置 CUSTOM 集合</p>
        </div>

        <PermissionButton code="role:config-data-scope" :loading="saving === 'DATA_SCOPE'" @click="saveDataScope">
          保存数据范围
        </PermissionButton>
        <p class="hint">
          部门维度的数据范围由后端下推到 SQL。切换策略后，该角色下所有用户下一次请求即生效。
        </p>
      </section>
    </template>

    <ConfirmDialog
      :open="pendingReset"
      title="切换角色"
      :description="confirmText"
      confirm-text="切换"
      @cancel="cancelSelect"
      @confirm="
        () => {
          pendingReset = false
          const id = selectedRoleId
          if (id !== null) void loadConfig(id)
        }
      "
    />
  </PageContainer>
</template>

<style scoped>
.picker {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
}

.panel {
  padding: 14px;
  margin-bottom: 12px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.panel__title {
  font-size: 15px;
  margin-bottom: 10px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.group {
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  padding: 10px;
}

.group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-weight: 600;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  cursor: pointer;
}

.hint {
  margin: 10px 0 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.radios {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 10px;
}

.depts {
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  padding: 6px 10px;
  margin-bottom: 10px;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 10px;
}

.mini-table th,
.mini-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--vctn-border);
  text-align: left;
  font-weight: 500;
}

.mini-table select {
  padding: 4px 8px;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  background: var(--vctn-surface);
  font: inherit;
}
</style>
