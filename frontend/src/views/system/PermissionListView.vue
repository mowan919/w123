<script setup lang="ts">
/**
 * 角色权限配置（FE-05 §1 / `08 §7` / DD-20 / FE-03 §5）。
 *
 * 三块配置分别保存，职责不同：
 * 1. **页面 / 菜单 / 按钮 / 接口** 的四类二元权限 —— 用一棵资源层级树呈现
 *    （菜单 → 页面 → 按钮 / 接口），点父项可把状态带给子项。
 *    提交语义是**按类别整体替换**（后端没有增量 PATCH 协议）。
 * 2. **字段权限**四态（VISIBLE / HIDDEN / READ_ONLY / EDITABLE）—— 逐字段提交。
 *    它不进树：字段表达的是"访问级别"，不是"有没有"，塞进二态勾选框里
 *    必然要在界面上额外发明一个"半选=只读"的约定。
 * 3. **数据范围**五值（DD-07 已冻结）。
 *
 * 授权的目标资源清单来自 `/admin/permission-resources`，而不是当前用户的
 * 权限契约 —— 目标角色可能持有当前管理员看不到的资源，
 * 用契约当选项来源会静默丢掉这些资源。
 *
 * 每次保存之后还会按"当前用户是否持有该角色"决定要不要重拉自己的契约：
 * 给自己的角色加权限后界面上立刻出现对应入口，是这个页面该有的行为。
 */
import { computed, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { KeyOutline, SaveOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import PermissionTree from '@/components/permission/PermissionTree.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
import { usePermissionStore } from '@/stores/permission'
import { useOrganizationStore } from '@/stores/organization'
import { useRolesStore } from '@/stores/roles'
import { useResourcesStore } from '@/stores/resources'
import { resolveSubmission, unavailableCount, universeOf } from '@/composables/usePermissionTree'
import type { PermissionTreeInput } from '@/composables/usePermissionTree'
import {
  getRoleDataScope,
  getRolePermissions,
  putRoleGrant,
  setRoleDataScope,
  setRoleFieldPermissions,
} from '@/api/endpoints/roles'
import { GRANT_KINDS, GRANT_KIND_LABEL, emptySelection } from '@/types'
import type { DataScopePolicy, FieldAccessLevel, GrantKind, GrantSelection, Role, RolePermissionView } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const permissionStore = usePermissionStore()
const organizationStore = useOrganizationStore()
const rolesStore = useRolesStore()
const resourcesStore = useResourcesStore()

const DATA_SCOPE_OPTIONS: Array<{ value: DataScopePolicy; label: string }> = [
  { value: 'ALL', label: '全部数据' },
  { value: 'DEPARTMENT', label: '本部门' },
  { value: 'DEPARTMENT_CHILDREN', label: '本部门及下级' },
  { value: 'SELF', label: '仅本人' },
  { value: 'CUSTOM', label: '自定义部门集合' },
]

const FIELD_LEVELS: FieldAccessLevel[] = ['VISIBLE', 'HIDDEN', 'READ_ONLY', 'EDITABLE']

const selectedRoleId = ref<ID | null>(null)

/** 界面上正在编辑的四类授权。 */
const selection = ref<GrantSelection>(emptySelection())

/**
 * 该角色在库里的**现状**。
 *
 * 它有两个用途，都不是"备份"：
 * 1. 判断有没有改动（没改就不提交 —— 一次无改动提交会写一条审计并递增
 *    权限版本，纯噪音）。
 * 2. 保留"候选清单之外"的既有授权（见 `resolveSubmission`）。
 */
const original = ref<GrantSelection>(emptySelection())

const fieldLevels = ref<Record<ID, FieldAccessLevel>>({})

const dataScope = ref<DataScopePolicy>('ALL')
const customDepartments = ref<ID[]>([])

const loadingConfig = ref(false)
const savingGrants = ref(false)
const savingFields = ref(false)
const savingScope = ref(false)
const pendingReset = ref(false)
const confirmText = ref('')

/** 权限树的输入：四类资源清单 + 真实的菜单挂载关系。 */
const treeInput = computed<PermissionTreeInput>(() => ({
  menus: resourcesStore.grantable?.MENU ?? [],
  pages: resourcesStore.grantable?.PAGE ?? [],
  buttons: resourcesStore.grantable?.BUTTON ?? [],
  apis: resourcesStore.grantable?.API ?? [],
  menuPages: resourcesStore.menuPages,
}))

const universe = computed(() => universeOf(treeInput.value))

/**
 * 候选清单之外的既有授权数量（>0 时必须在界面上说出来）。
 *
 * 资源清单是**分类取回且有上限**的，角色可能持有没被取回的资源。
 * 保存时这些会被原样保留（`resolveSubmission`），但管理员有权知道
 * "这个角色的授权不是你在上面看到的全部"。
 */
const preservedCounts = computed<Record<GrantKind, number>>(() => {
  const scope = universe.value
  return {
    PAGE: unavailableCount(scope.PAGE, original.value.PAGE),
    MENU: unavailableCount(scope.MENU, original.value.MENU),
    BUTTON: unavailableCount(scope.BUTTON, original.value.BUTTON),
    API: unavailableCount(scope.API, original.value.API),
  }
})

const preservedTotal = computed(() =>
  GRANT_KINDS.reduce((sum, kind) => sum + preservedCounts.value[kind], 0),
)

/** 字段权限的候选（FIELD 与二元授权分开管理）。 */
const grantableFields = computed(() => resourcesStore.grantable?.FIELD ?? [])

/** 角色清单来自 store：它与角色管理页共享同一份缓存，不各自发请求。 */
const roles = computed<Role[]>(() => rolesStore.picker)

function sameIdSet(left: readonly ID[], right: readonly ID[]): boolean {
  if (left.length !== right.length) return false
  const seen = new Set(left)
  return right.every((id) => seen.has(id))
}

const grantsDirty = computed(() =>
  GRANT_KINDS.some((kind) => !sameIdSet(selection.value[kind], original.value[kind])),
)

function notice(cause: unknown, fallback: string): void {
  appStore.showNotice('error', cause instanceof Error ? cause.message : fallback)
}

async function loadRoles(): Promise<void> {
  await rolesStore.ensurePicker()
  if (selectedRoleId.value === null && roles.value.length > 0) {
    selectedRoleId.value = roles.value[0]?.id ?? null
  }
}

/**
 * 取授权候选清单与菜单层级。
 *
 * 两者的失败**互不牵连**：菜单层级取不到只是树上少一层分组
 * （页面会落到「未挂载菜单的页面」下），授权能力完全不受影响。
 */
async function loadResources(): Promise<void> {
  await resourcesStore.ensureGrantable()
  await resourcesStore.ensureMenuPages()
}

function applyView(view: RolePermissionView): void {
  const next: GrantSelection = {
    PAGE: [...view.page_ids],
    MENU: [...view.menu_ids],
    BUTTON: [...view.button_ids],
    API: [...view.api_ids],
  }
  selection.value = next
  original.value = {
    PAGE: [...next.PAGE],
    MENU: [...next.MENU],
    BUTTON: [...next.BUTTON],
    API: [...next.API],
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
    appStore.showNotice('info', '已保存，但界面权限刷新失败，刷新页面后生效')
  }
}

/**
 * 保存四类授权。
 *
 * **顺序执行、逐个记录成败**，不用 `Promise.all`：四类各自是一次
 * "整体替换"，任何一个失败都必须能被准确地说出来是哪一类。
 * `Promise.all` 只给第一个错误，其余类别是成是败无从得知，
 * 而界面此时显示的是本地勾选状态 —— 那正是"界面说授权了、库里没有"
 * 这类最难排查的问题的温床。
 *
 * 无论成败，最后都重拉一次真实配置：宁可让管理员在界面上看到
 * "有一类没保存上"，也不要让他对着一个与库不一致的界面继续改。
 */
async function saveGrants(): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null || !grantsDirty.value) return
  savingGrants.value = true
  const failed: string[] = []
  try {
    for (const kind of GRANT_KINDS) {
      const ids = resolveSubmission(
        kind,
        selection.value,
        universe.value[kind],
        original.value[kind],
      )
      try {
        await putRoleGrant(kind, roleId, ids)
      } catch (cause) {
        failed.push(GRANT_KIND_LABEL[kind])
        notice(cause, `${GRANT_KIND_LABEL[kind]}保存失败`)
      }
    }
    if (failed.length === 0) appStore.showNotice('success', '权限已保存')
    else
      appStore.showNotice(
        'error',
        `${failed.join(' / ')} 未保存成功，其余类别已生效。请修正后重试。`,
      )
  } finally {
    savingGrants.value = false
    await loadConfig(roleId)
    await refreshSelfIfAffected(roleId)
  }
}

async function saveFields(): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null) return
  savingFields.value = true
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
    savingFields.value = false
  }
}

async function saveDataScope(): Promise<void> {
  const roleId = selectedRoleId.value
  if (roleId === null) return
  savingScope.value = true
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
    savingScope.value = false
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
  appStore.showNotice('info', `你的权限已被更新到版本 ${contractVersion.value}，请重新加载本页后再修改`)
})

async function boot(): Promise<void> {
  await Promise.all([loadRoles(), loadResources(), loadDepartments()])
  const first = selectedRoleId.value
  if (first !== null) await loadConfig(first)
}

void boot()
</script>

<template>
  <PageContainer
    title="权限配置"
    description="按角色配置它能看到哪些页面、能点哪些按钮、能读改哪些字段，以及能看到哪个范围的数据。"
    :icon="KeyOutline"
  >
    <div class="picker">
      <label class="field">
        <span class="field__label">
          <NIcon :component="KeyOutline" />
          角色
        </span>
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
      <span class="muted">上方为资源授权，修改后点「保存权限」；字段权限与数据范围各自单独保存。</span>
    </div>
    <p v-if="rolesStore.pickerMightBeTruncated" class="hint">
      角色数量较多，这里的下拉可能未取全；查不到目标角色时可到「角色管理」页按关键字检索。
    </p>

    <div v-if="loadingConfig" class="state"><span class="spinner" aria-hidden="true" /><span>加载配置…</span></div>

    <template v-else>
      <section class="panel">
        <h3 class="panel__title">页面 / 菜单 / 按钮 / 接口授权</h3>
        <PermissionTree
          v-model="selection"
          :menus="treeInput.menus"
          :pages="treeInput.pages"
          :buttons="treeInput.buttons"
          :apis="treeInput.apis"
          :menu-pages="treeInput.menuPages"
        />

        <div class="panel__actions">
          <PermissionButton
            code="role:assign-permission"
            type="primary"
            :disabled="!grantsDirty"
            :loading="savingGrants"
            @click="saveGrants"
          >
            <NIcon :component="SaveOutline" />
            保存权限
          </PermissionButton>
          <span v-if="!grantsDirty" class="muted">没有改动</span>
        </div>

        <p class="hint">
          取消某类别的全部勾选并保存，即清空该类别的授权；其他类别不受影响。
          角色继承由后端递归展开，这里改的是**本角色直接持有**的授权。
        </p>
        <p v-if="preservedTotal > 0" class="hint">
          该角色还持有 {{ preservedTotal }} 项未出现在上方清单中的授权
          （页面 {{ preservedCounts.PAGE }} / 菜单 {{ preservedCounts.MENU }} /
          按钮 {{ preservedCounts.BUTTON }} / 接口 {{ preservedCounts.API }}）——
          它们不在候选范围内，保存时会**原样保留**，不会被这次提交清掉。
        </p>
        <p v-if="resourcesStore.grantableMightBeTruncated" class="hint">
          资源数量较多，这里的清单可能未取全；可到「权限资源」页按类型检索后再授权。
        </p>
        <p v-if="resourcesStore.menuPagesError !== null" class="hint">
          菜单层级未加载（{{ resourcesStore.menuPagesError }}）；页面统一列在「未挂载菜单的页面」下，授权不受影响。
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
            <tr v-for="field in grantableFields" :key="field.id">
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
        <PermissionButton code="role:assign-permission" :loading="savingFields" @click="saveFields">
          <NIcon :component="SaveOutline" />
          保存字段权限
        </PermissionButton>
        <p class="hint">
          设为「隐藏」的字段既不会出现在接口返回里，也无法被直接提交修改。
        </p>
      </section>

      <section class="panel">
        <h3 class="panel__title">数据范围</h3>
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
          <p v-if="organizationStore.flat.length === 0" class="muted">部门树加载失败，暂时无法选择自定义部门</p>
        </div>

        <PermissionButton code="role:config-data-scope" :loading="savingScope" @click="saveDataScope">
          <NIcon :component="SaveOutline" />
          保存数据范围
        </PermissionButton>
        <p class="hint">
          范围决定该角色能看到哪些部门的数据（例如只看本部门、或只看本人）。
          保存后立即生效，角色下的用户下次请求即按新范围返回。
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

.panel__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.depts {
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
  padding: 6px 10px;
  margin-bottom: 10px;
}
</style>
