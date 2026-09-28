<script setup lang="ts">
/**
 * 用户管理（FE-06 §2）。
 *
 * 展示层的数据范围（列表天然受后端范围下推约束）与按钮层的 BUTTON 权限
 * 是两件事：前者后端返回多少就是多少，后者由 PermissionButton 控制。
 * 两者都不替代后端鉴权。
 *
 * 关于角色：`POST /users` 接受初始角色集合，但后端**没有**"改某个用户的
 * 角色"的 HTTP 端点（`UserRolesUpdateRequest` 只有模型、没有任何路由引用它）。
 * 因此角色只在"新增"时指定，编辑弹窗里不出现角色字段 —— 前端不能凭
 * 一个不存在的接口去显示"可编辑"。
 */
import { computed, onMounted, ref } from 'vue'
import { NButton, NCheckbox, NIcon, NSelect, NTreeSelect } from 'naive-ui'
import {
  AddOutline,
  CreateOutline,
  KeyOutline,
  LockOpenOutline,
  PersonOutline,
  RefreshOutline,
} from '@vicons/ionicons5'

import { usePageQuery } from '@/composables/usePageQuery'
import { useColumnSettings } from '@/composables/useColumnSettings'
import * as api from '@/api/endpoints/organization'
import type { User } from '@/types'
import type { ID } from '@/types/common'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import PermissionField from '@/components/permission/PermissionField.vue'
import { useAppStore } from '@/stores/app'
import { useDictionaryStore } from '@/stores/dictionaries'
import { useOrganizationStore } from '@/stores/organization'
import { useRolesStore } from '@/stores/roles'
import { formatDateTime, localInputToUtcIso, nowAsLocalInput } from '@/utils/format'
import { PASSWORD_HINT, validatePassword } from '@/utils/validate'
import type { DataTableColumn } from '@/components/data/types'

const appStore = useAppStore()
const dictionaryStore = useDictionaryStore()
const organizationStore = useOrganizationStore()
const rolesStore = useRolesStore()

/**
 * 部门下拉的候选直接取**后端返回的树**，不做压平。
 *
 * 筛选项与表单里的"所属部门"共用同一份 `organizationStore.tree`：
 * 层级展开是唯一的（由 NTreeSelect 按 `children-field` 递归渲染），
 * 页面不再自己压平一层 —— 那会变成第二份层级真相，
 * 一旦压平写错，"层级下拉里看到的父子关系"与"包含下级实际展开的子树"
 * 就会不一致，而这种不一致只在特定数据上才看得出来。
 */
const DEPARTMENT_TREE_FIELDS = {
  keyField: 'id',
  labelField: 'department_name',
  childrenField: 'children',
} as const

/** NTreeSelect / NSelect 的 `update:value` 载荷（库声明的联合类型，需自行收窄）。 */
type SelectValue = string | number | Array<string | number> | null

const filters = ref<{
  keyword: string
  status: string
  department_id: ID | null
  include_sub_departments: boolean
  /** `datetime-local` 的原始本地时间串（`''` = 不限）。发出前转 UTC。 */
  created_from: string
  created_to: string
}>({
  keyword: '',
  status: '',
  department_id: null,
  include_sub_departments: false,
  created_from: '',
  created_to: '',
})

const { rows, total, pageNum, pageSize, loading, error, reload, onPageChange } = usePageQuery<User>(
  (query) => api.listUsers(query),
)

/** 可配置的列（不含操作列 —— 操作列由 DataTable 的操作槽固定渲染）。 */
const dataColumns: Array<DataTableColumn<User>> = [
  { key: 'username', title: '用户名' },
  { key: 'display_name', title: '姓名' },
  { key: 'phone', title: '手机号' },
  { key: 'email', title: '邮箱' },
  { key: 'department_id', title: '部门' },
  { key: 'status', title: '状态', width: '100px' },
  // 下面这些字段后端一直在返回，只是此前没有列去消费它们。`status` 只说明
  // "能不能登录"，而"为什么不能登录 / 上一次口令是什么时候换的"要这三列
  // 才能回答 —— 账号被锁时只看状态列会误判成"已禁用"。
  { key: 'must_change_password', title: '需改密', width: '90px', align: 'center' },
  { key: 'failed_login_count', title: '登录失败', width: '90px', align: 'right' },
  { key: 'locked_until', title: '锁定至', width: '170px' },
  { key: 'password_changed_at', title: '改密时间', width: '170px' },
  { key: 'created_at', title: '创建时间', width: '180px' },
  { key: 'updated_at', title: '更新时间', width: '170px' },
  { key: 'id', title: '用户 ID', width: '200px' },
]
const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<User>('users', dataColumns)

/**
 * 时间区间填反了。
 *
 * 本地时间串是按字典序可比的（`YYYY-MM-DDTHH:mm`，补零到固定宽度），
 * 因此不需要先转 UTC 再比 —— 而且**必须**用本地串比：
 * 转换会引入一次时区换算，比较时再出错就没人看得出来了。
 */
const createdRangeInvalid = computed<boolean>(
  () =>
    filters.value.created_from !== '' &&
    filters.value.created_to !== '' &&
    filters.value.created_from > filters.value.created_to,
)

function onSearch(): void {
  // 区间反了就如实拒绝，不静默交换两端：静默交换会让用户以为筛的是自己填的区间。
  // 后端同样会 400（`UserService.list_users`），但本地拦一次能给出一句人话。
  if (createdRangeInvalid.value) {
    appStore.showNotice('error', '创建时间的起始不能晚于结束')
    return
  }
  reload({
    keyword: filters.value.keyword || null,
    status: filters.value.status || null,
    department_id: filters.value.department_id,
    // 没选部门时"包含下级"没有意义：后端会忽略它，但少发一个无意义参数
    // 能让请求日志里"这次到底按什么筛的"一眼可读。
    include_sub_departments:
      filters.value.department_id !== null && filters.value.include_sub_departments,
    // 时间必须转成带时区的 UTC 串再发（详见 `localInputToUtcIso`）：
    // 原样发本地串时，后端把它当 naive datetime 绑到 timestamptz 上，
    // 解释权归服务端时区，服务器一旦不是 +08:00 就整块偏 8 小时且不报错。
    created_from: localInputToUtcIso(filters.value.created_from),
    created_to: localInputToUtcIso(filters.value.created_to),
  })
}

/**
 * 把「结束时间」设为此刻。
 *
 * 只填结束时间，不动起始时间：最常见的用法是"看某天以来的用户"——
 * 起始时间是自己选的，结束时间几乎总是"到现在"。两个一起覆盖会把手填的
 * 起始时间冲掉，而那正是唯一需要人思考的值。
 */
function setCreatedToNow(): void {
  filters.value.created_to = nowAsLocalInput()
}

function onReset(): void {
  filters.value = {
    keyword: '',
    status: '',
    department_id: null,
    include_sub_departments: false,
    created_from: '',
    created_to: '',
  }
  reload({})
}

function statusClass(status: string): string {
  if (status === 'ACTIVE') return 'tag tag--active'
  if (status === 'LOCKED') return 'tag tag--locked'
  return 'tag tag--disabled'
}

/** 列表只拿到 department_id（雪花 ID），直接显示是数字串 —— 翻译成部门名。 */
const departmentLabel = computed<Map<string, string>>(() => {
  const map = new Map<string, string>()
  for (const option of organizationStore.options) map.set(option.id, option.label)
  return map
})

// ---------------------------------------------------------------- 新增 / 编辑

interface UserDraft {
  id: ID | null
  username: string
  password: string
  display_name: string
  /** `null` 表示未分配部门（而不是空串）—— 与后端 `department_id: null` 同义。 */
  department_id: ID | null
  phone: string
  email: string
  role_ids: ID[]
}

function emptyDraft(): UserDraft {
  return {
    id: null,
    username: '',
    password: '',
    display_name: '',
    department_id: null,
    phone: '',
    email: '',
    role_ids: [],
  }
}

/** 角色下拉的选项。带上编码，因为同名角色只能靠它区分。 */
const roleOptions = computed<Array<{ label: string; value: ID }>>(() =>
  rolesStore.picker.map((role) => ({
    label: `${role.role_name}（${role.role_code}）`,
    value: role.id,
  })),
)

/**
 * 草稿**始终是对象**，另用 `draftOpen` 控制显隐。
 *
 * 用 `draft: UserDraft | null` 会让模板里出现 `draft?.username`，
 * 而 `v-model` **不能**绑定可选链表达式（编译器直接报错）——
 * 于是每个字段都得写 `draft!.x`，一个 `!` 写漏就是运行时的空指针。
 */
const draft = ref<UserDraft>(emptyDraft())
const draftOpen = ref(false)
const saving = ref(false)

const isEditing = computed(() => draft.value.id !== null)

/** 提交前的字段校验；返回 null 表示可提交。 */
const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  const current = draft.value
  if (current.username.trim() === '') return '请填写用户名'
  if (current.display_name.trim() === '') return '请填写姓名'
  if (current.id === null) return validatePassword({ next: current.password })
  return null
})

/**
 * 把 NSelect / NTreeSelect 的联合类型收窄回 `ID`。
 *
 * 选项的 `value` 全部是后端下发的 ID **字符串**，所以 `String(item)` 是恒等映射，
 * 不做任何数值转换（`types/common.ts` 明确禁止把业务 ID 落到 `number` 上，
 * 超过 `Number.MAX_SAFE_INTEGER` 会静默丢位）。
 */
function toIdList(value: SelectValue): ID[] {
  if (Array.isArray(value)) return value.map((item) => String(item))
  return value === null ? [] : [String(value)]
}

function toSingleId(value: SelectValue): ID | null {
  if (Array.isArray(value)) {
    const first = value[0]
    return first === undefined ? null : String(first)
  }
  return value === null ? null : String(value)
}

/**
 * 筛选器里的部门变化。
 *
 * 清空部门时必须**同时**关掉"包含下级"：否则开关看起来还是打开的，
 * 但请求里已经不带 `include_sub_departments`（`onSearch` 会忽略它），
 * 界面状态与实际生效的筛选条件不一致 —— 下次有人接着说
 * "勾着包含下级呢，怎么没查出来"，问题就会指向后端。
 */
function onFilterDepartment(value: SelectValue): void {
  filters.value.department_id = toSingleId(value)
  if (filters.value.department_id === null) filters.value.include_sub_departments = false
}

function onDraftDepartment(value: SelectValue): void {
  draft.value.department_id = toSingleId(value)
}

function onDraftRoles(value: SelectValue): void {
  draft.value.role_ids = toIdList(value)
}

function startCreate(): void {
  draft.value = emptyDraft()
  // 沿用当前筛选的部门：在"某部门"筛选下新建用户，多半就是想建在那个部门。
  draft.value.department_id = filters.value.department_id
  draftOpen.value = true
  // 角色清单是懒加载的（不在首屏拉），打开弹窗时才要。
  void rolesStore.ensurePicker()
}

function startEdit(user: User): void {
  draft.value = {
    id: user.id,
    username: user.username,
    password: '',
    display_name: user.display_name,
    department_id: user.department_id ?? null,
    phone: user.phone ?? '',
    email: user.email ?? '',
    role_ids: [],
  }
  draftOpen.value = true
}

/** 空串一律转 null：后端按 `model_fields_set` 分派，空串会被当作"把值改成空"。 */
function nullable(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

async function saveDraft(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  saving.value = true
  try {
    if (current.id === null) {
      await api.createUser({
        username: current.username.trim(),
        password: current.password,
        display_name: current.display_name.trim(),
        department_id: current.department_id,
        phone: nullable(current.phone),
        email: nullable(current.email),
        role_ids: current.role_ids.length > 0 ? current.role_ids : undefined,
      })
      appStore.showNotice('success', `已创建用户 ${current.username.trim()}`)
    } else {
      await api.updateUser(current.id, {
        display_name: current.display_name.trim(),
        department_id: current.department_id,
        phone: nullable(current.phone),
        email: nullable(current.email),
      })
      appStore.showNotice('success', '用户信息已更新')
    }
    draftOpen.value = false
    await reload()
  } catch (cause) {
    // 原样回显后端错误：唯一性冲突、数据范围越界这些原因改写不得。
    appStore.showNotice('error', cause instanceof Error ? cause.message : '保存失败')
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 禁用 / 启用 / 重置口令

const disableTarget = ref<User | null>(null)
const enableTarget = ref<User | null>(null)
const resetTarget = ref<User | null>(null)
const resetPassword = ref('')
const resetting = ref(false)

const resetError = computed<string | null>(() =>
  resetTarget.value === null ? null : validatePassword({ next: resetPassword.value }),
)

async function confirmDisable(): Promise<void> {
  const target = disableTarget.value
  if (target === null) return
  try {
    await api.disableUser(target.id)
    appStore.showNotice('success', `已禁用用户 ${target.username}`)
    disableTarget.value = null
    await reload()
  } catch (cause) {
    // 后端会拒绝"禁用最后一个 SUPER_ADMIN"（RISK-002），这里原样回显。
    appStore.showNotice('error', cause instanceof Error ? cause.message : '操作失败')
  }
}

async function confirmEnable(): Promise<void> {
  const target = enableTarget.value
  if (target === null) return
  try {
    await api.enableUser(target.id)
    appStore.showNotice('success', `已启用用户 ${target.username}`)
    enableTarget.value = null
    await reload()
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '操作失败')
  }
}

function openReset(user: User): void {
  resetPassword.value = ''
  resetTarget.value = user
}

async function confirmReset(): Promise<void> {
  const target = resetTarget.value
  if (target === null || resetError.value !== null) return
  resetting.value = true
  try {
    await api.resetUserPassword(target.id, { new_password: resetPassword.value })
    appStore.showNotice('success', `已重置 ${target.username} 的口令，其首次登录需重新设置`)
    resetTarget.value = null
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '操作失败')
  } finally {
    resetting.value = false
  }
}

onMounted(async () => {
  void reload()
  void dictionaryStore.ensure('user_status')
  // 部门树是唯一的部门数据来源（后端没有扁平列表端点）。取回失败不弹错误：
  // 部门筛选器空着不影响列表本身。
  await organizationStore.ensure()
})
</script>

<template>
  <PageContainer
    title="用户管理"
    description="维护账号的基本信息、所属部门与状态，并可为用户重置登录口令。"
    :icon="PersonOutline"
  >
    <SearchForm @search="onSearch" @reset="onReset">
      <label class="field">
        <span class="field__label">关键字</span>
        <input v-model.trim="filters.keyword" class="field__control" placeholder="用户名 / 姓名" />
      </label>
      <label class="field">
        <span class="field__label">状态</span>
        <select v-model="filters.status" class="field__control">
          <option value="">全部</option>
          <option value="ACTIVE">正常</option>
          <option value="DISABLED">禁用</option>
          <option value="LOCKED">锁定</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">部门</span>
        <NTreeSelect
          v-bind="DEPARTMENT_TREE_FIELDS"
          :value="filters.department_id"
          :options="organizationStore.tree"
          clearable
          filterable
          placeholder="全部"
          @update:value="onFilterDepartment"
        />
      </label>
      <label class="field">
        <span class="field__label">部门范围</span>
        <NCheckbox
          :checked="filters.include_sub_departments"
          :disabled="filters.department_id === null"
          @update:checked="(checked: boolean) => (filters.include_sub_departments = checked)"
        >
          包含下级部门
        </NCheckbox>
      </label>
      <div class="field">
        <span class="field__label">创建时间</span>
        <div class="field__row">
          <!--
            两端各自带 `aria-label` 而不是靠外层 `<span class="field__label">`：
            一组日期输入只能有一个可见标签，"起/止"必须落到控件自身，
            否则读屏软件把两个输入读成同一个字段。
          -->
          <input
            v-model="filters.created_from"
            class="field__control"
            type="datetime-local"
            aria-label="创建时间起始"
          />
          <span class="muted">~</span>
          <input
            v-model="filters.created_to"
            class="field__control"
            type="datetime-local"
            aria-label="创建时间结束"
          />
          <!--
            「此刻」是给"结束时间"用的快捷入口：起始时间几乎总要人自己选
            （"看某天以来的"），结束时间则几乎总是"到现在"。
          -->
          <button
            type="button"
            class="btn btn--text btn--text-primary"
            title="把结束时间设为当前时间"
            @click="setCreatedToNow"
          >
            此刻
          </button>
        </div>
      </div>
    </SearchForm>

    <p v-if="createdRangeInvalid" class="hint">
      创建时间的起始晚于结束，修改后再查询（查询会被拒绝，不会静默交换两端）。
    </p>

    <div class="toolbar">
      <PermissionButton code="user:create" type="primary" @click="startCreate">
        <NIcon :component="AddOutline" />
        新建用户
      </PermissionButton>
      <NButton size="small" @click="reload()">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
      <span class="toolbar__end">
        <ColumnSettings
          :items="columnItems"
          :disabled="loading"
          @toggle="toggleColumn"
          @move="moveColumn"
          @reset="resetColumns"
        />
      </span>
    </div>

    <DataTable
      :columns="visibleColumns"
      :rows="rows"
      :row-key="(row: User) => row.id"
      :loading="loading"
      :error="error"
      empty-text="没有符合条件的用户"
      actions-title="操作"
      actions-width="260px"
    >
      <template #cell-status="{ row }">
        <span :class="statusClass(row.status)">{{ dictionaryStore.labelOf('user_status', row.status) || row.status }}</span>
      </template>
      <template #cell-phone="{ row }">
        <!--
          ⚠️ `code` 必须是**契约里的 `field_key`**（`phone`），不是 FIELD 资源的
          `resource_code`（`field:phone`）。这里曾经写成 `'field:user.phone'` ——
          一个永远匹配不上的键，于是这两列对**任何角色**（含超管）都渲染成空白，
          而且不报任何错：`getFieldPermission` 对未知键 fail-closed 返回 HIDDEN。
          可用的 field_key 由 `scripts/seed_data.py` 的 FIELDS 定义。
        -->
        <PermissionField code="phone">
          <template #default>
            <!-- 纯文本，不是输入框。列表里既没有保存入口，把值渲染成
                 `<input readonly placeholder="未填写">` 只会让空值看起来像
                 "一个待填的框"（截图里它和真正的筛选框长得一模一样），
                 长号码还会被输入框内边距截断。空值统一走 `—`。 -->
            <span v-if="row.phone" class="clip" :title="row.phone">{{ row.phone }}</span>
            <span v-else class="muted">—</span>
          </template>
        </PermissionField>
      </template>
      <template #cell-email="{ row }">
        <PermissionField code="email">
          <template #default>
            <span v-if="row.email" class="clip" style="--clip-width: 220px" :title="row.email">
              {{ row.email }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </PermissionField>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ formatDateTime(row.created_at) }}</span>
      </template>
      <template #cell-updated_at="{ row }">
        <span class="muted">{{ formatDateTime(row.updated_at) }}</span>
      </template>
      <template #cell-must_change_password="{ row }">
        <span class="tag" :class="row.must_change_password ? 'tag--locked' : ''">
          {{ row.must_change_password ? '需改密' : '否' }}
        </span>
      </template>
      <template #cell-failed_login_count="{ row }">
        <!-- 0 次是常态，不做任何标记；有失败记录才提醒 -->
        <span v-if="row.failed_login_count === 0" class="muted">0</span>
        <span v-else class="tag tag--locked">{{ row.failed_login_count }}</span>
      </template>
      <template #cell-locked_until="{ row }">
        <span class="muted">{{ formatDateTime(row.locked_until) }}</span>
      </template>
      <template #cell-password_changed_at="{ row }">
        <span class="muted">{{ formatDateTime(row.password_changed_at) }}</span>
      </template>
      <template #cell-id="{ row }">
        <code class="muted">{{ row.id }}</code>
      </template>
      <template #cell-department_id="{ row }">
        {{ (row.department_id !== null && departmentLabel.get(row.department_id)) || '—' }}
      </template>

      <template #actions="{ row }">
        <span class="table-actions">
          <PermissionButton code="user:update" type="text-primary" @click="startEdit(row)">
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton code="user:reset-password" type="text-warn" @click="openReset(row)">
            <NIcon :component="KeyOutline" />
            重置口令
          </PermissionButton>
          <PermissionButton
            v-if="row.status !== 'ACTIVE'"
            code="user:enable"
            type="text-success"
            @click="enableTarget = row"
          >
            <NIcon :component="LockOpenOutline" />
            启用
          </PermissionButton>
          <PermissionButton
            v-else
            code="user:disable"
            type="text-danger"
            @click="disableTarget = row"
          >
            禁用
          </PermissionButton>
        </span>
      </template>
    </DataTable>

    <Pagination
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      @change="onPageChange"
    />

    <!-- 新增 / 编辑 -->
    <FormDialog
      :open="draftOpen"
      :title="isEditing ? '编辑用户' : '新增用户'"
      :loading="saving"
      :error="draftError"
      :width="640"
      @cancel="draftOpen = false"
      @submit="saveDraft"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">用户名</span>
          <input
            v-model.trim="draft.username"
            class="field__control"
            :disabled="isEditing"
            placeholder="登录名"
          />
        </label>
        <label class="field">
          <span class="field__label">姓名</span>
          <input v-model.trim="draft.display_name" class="field__control" placeholder="显示名称" />
        </label>

        <label v-if="!isEditing" class="field">
          <span class="field__label">初始口令</span>
          <input v-model="draft.password" type="password" class="field__control" autocomplete="new-password" />
        </label>
        <label class="field">
          <span class="field__label">所属部门</span>
          <NTreeSelect
            v-bind="DEPARTMENT_TREE_FIELDS"
            :value="draft.department_id"
            :options="organizationStore.tree"
            clearable
            filterable
            placeholder="未分配"
            @update:value="onDraftDepartment"
          />
        </label>

        <label class="field">
          <span class="field__label">手机号</span>
          <input v-model.trim="draft.phone" class="field__control" placeholder="选填" />
        </label>
        <label class="field">
          <span class="field__label">邮箱</span>
          <input v-model.trim="draft.email" class="field__control" placeholder="选填" />
        </label>

        <label v-if="!isEditing" class="field field--full">
          <span class="field__label">角色</span>
          <NSelect
            :value="draft.role_ids"
            multiple
            filterable
            :options="roleOptions"
            :loading="rolesStore.pickerLoading"
            :max-tag-count="3"
            placeholder="可多选"
            @update:value="onDraftRoles"
          />
          <span class="hint">
            为账号指定一个或多个角色；不选表示暂不授予任何权限。角色较多时可直接输入名称筛选。
          </span>
        </label>
      </div>

      <p class="hint">
        <template v-if="isEditing">
          用户名是登录标识，创建后不可修改；角色的调整入口未开放。
        </template>
        <template v-else>
          初始口令{{ PASSWORD_HINT }}；用户首次登录需重新设置口令。
        </template>
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="disableTarget !== null"
      title="禁用用户"
      :description="disableTarget ? `禁用后 ${disableTarget.username} 将无法登录，现有会话也会被撤销。` : ''"
      confirm-text="确认禁用"
      danger
      @cancel="disableTarget = null"
      @confirm="confirmDisable"
    />

    <ConfirmDialog
      :open="enableTarget !== null"
      title="启用用户"
      :description="enableTarget ? `启用后 ${enableTarget.username} 可恢复正常登录。` : ''"
      confirm-text="确认启用"
      @cancel="enableTarget = null"
      @confirm="confirmEnable"
    />

    <FormDialog
      :open="resetTarget !== null"
      title="重置登录口令"
      :loading="resetting"
      :error="resetError"
      confirm-text="确认重置"
      danger
      @cancel="resetTarget = null"
      @submit="confirmReset"
    >
      <p class="muted">
        为 <strong>{{ resetTarget?.username }}</strong> 设置一个新的登录口令。重置后该用户
        首次登录会被要求重新设置口令。
      </p>
      <label class="field">
        <span class="field__label">新口令</span>
        <input v-model="resetPassword" type="password" class="field__control" autocomplete="new-password" />
      </label>
      <p class="hint">{{ PASSWORD_HINT }}。</p>
    </FormDialog>
  </PageContainer>
</template>
