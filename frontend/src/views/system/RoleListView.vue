<script setup lang="ts">
/**
 * 角色管理（FE-05 §1 / `08 §7`）。
 *
 * 只做角色本体（CRUD）：编码、名称、描述、状态。
 * **权限配置与数据范围配置不在这里** —— 它们属于"权限配置"页：
 * 一是职责不同（这里是角色实体，那里是角色 × 资源的授权），
 * 二是授权页需要反复读取资源清单，放在同一屏会让两边都变慢。
 *
 * 角色继承由后端递归展开（`role_inheritances` + 深度上限 32），
 * 前端既不展示继承树也不参与展开（FE-03 §4）。
 */
import { formatDateTime } from '@/utils/format'
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { AddOutline, CreateOutline, RefreshOutline, ShieldCheckmarkOutline, TrashOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ColumnSettings from '@/components/data/ColumnSettings.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import FormDialog from '@/components/feedback/FormDialog.vue'
import { useAppStore } from '@/stores/app'
import { useColumnSettings } from '@/composables/useColumnSettings'
import { useRolesStore } from '@/stores/roles'
import type { DataTableColumn } from '@/components/data/types'
import type { Role } from '@/types'
import type { ID } from '@/types/common'

const appStore = useAppStore()
const rolesStore = useRolesStore()

interface RoleDraft {
  id: ID | null
  role_code: string
  role_name: string
  description: string
  status: 'ACTIVE' | 'DISABLED'
}

const dataColumns: Array<DataTableColumn<Role>> = [
  { key: 'role_code', title: '角色编码' },
  { key: 'role_name', title: '角色名称' },
  { key: 'data_scope', title: '数据范围' },
  { key: 'status', title: '状态', width: '100px' },
  { key: 'created_at', title: '创建时间', width: '180px' },
]

const {
  visible: visibleColumns,
  items: columnItems,
  toggle: toggleColumn,
  move: moveColumn,
  reset: resetColumns,
} = useColumnSettings<Role>('roles', dataColumns)

const DATA_SCOPE_LABEL: Record<string, string> = {
  ALL: '全部数据',
  DEPARTMENT: '本部门',
  DEPARTMENT_CHILDREN: '本部门及下级',
  SELF: '仅本人',
  CUSTOM: '自定义（见权限配置）',
}

/** 筛选输入只留在页面里（受控于 SearchForm）；分页与结果归 store。 */
const keyword = ref('')
const statusFilter = ref<'' | 'ACTIVE' | 'DISABLED'>('')

function emptyDraft(): RoleDraft {
  return { id: null, role_code: '', role_name: '', description: '', status: 'ACTIVE' }
}

const draft = ref<RoleDraft>(emptyDraft())
const draftOpen = ref(false)
const saving = ref(false)
const pendingDelete = ref<Role | null>(null)
const deleting = ref(false)

const isEditing = computed(() => draft.value.id !== null)

const draftError = computed<string | null>(() => {
  if (!draftOpen.value) return null
  if (draft.value.role_code.trim() === '') return '请填写角色编码'
  if (draft.value.role_name.trim() === '') return '请填写角色名称'
  return null
})

function search(): void {
  void rolesStore.setFilters({ keyword: keyword.value })
}

/** 用命名函数而不是模板内联箭头：内联里同时读写 ref 容易踩类型推断。 */
function onPageChange(next: { pageNum: number; pageSize: number }): void {
  void rolesStore.goToPage(next.pageNum, next.pageSize)
}

async function resetFilters(): Promise<void> {
  keyword.value = ''
  statusFilter.value = ''
  await rolesStore.setFilters({ keyword: '', status: '' })
}

function startCreate(): void {
  draft.value = emptyDraft()
  draftOpen.value = true
}

function startEdit(role: Role): void {
  draft.value = {
    id: role.id,
    role_code: role.role_code,
    role_name: role.role_name,
    description: role.description ?? '',
    status: role.status,
  }
  draftOpen.value = true
}

async function save(): Promise<void> {
  if (draftError.value !== null) return
  const current = draft.value
  saving.value = true
  try {
    if (current.id === null) {
      await rolesStore.create({
        role_code: current.role_code.trim(),
        role_name: current.role_name.trim(),
        description: current.description || null,
        status: current.status,
      })
    } else {
      // 只发真正改动的字段：后端按 `model_fields_set` 分派，
      // 把没改的字段也塞进去会被当成"显式清空"（角色编码只读）。
      await rolesStore.update(current.id, {
        role_name: current.role_name.trim(),
        description: current.description || null,
        status: current.status,
      })
    }
    draftOpen.value = false
    appStore.showNotice('success', current.id === null ? '角色已创建' : '角色已更新')
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = pendingDelete.value
  if (target === null) return
  deleting.value = true
  try {
    await rolesStore.remove(target.id)
    pendingDelete.value = null
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void rolesStore.goToPage(rolesStore.pageNum, rolesStore.pageSize)
})
</script>

<template>
  <PageContainer
    title="角色管理"
    description="维护角色本身：编码、名称、描述与状态。具体能看哪些页面、能改哪些字段，在「权限配置」里按角色设置。"
    :icon="ShieldCheckmarkOutline"
  >
    <SearchForm @search="search" @reset="resetFilters">
      <label class="field">
        <span class="field__label">关键字</span>
        <input v-model="keyword" class="field__control" placeholder="编码或名称" />
      </label>
      <label class="field">
        <span class="field__label">状态</span>
        <select v-model="statusFilter" class="field__control">
          <option value="">全部</option>
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>
    </SearchForm>

    <div class="toolbar">
      <PermissionButton code="role:create" type="primary" @click="startCreate">
        <NIcon :component="AddOutline" />
        新增角色
      </PermissionButton>
      <NButton size="small" :loading="rolesStore.loading" @click="rolesStore.goToPage(rolesStore.pageNum, rolesStore.pageSize)">
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
      <span class="toolbar__end">
        <ColumnSettings
          :items="columnItems"
          :disabled="rolesStore.loading"
          @toggle="toggleColumn"
          @move="moveColumn"
          @reset="resetColumns"
        />
      </span>
    </div>

    <DataTable
      :columns="visibleColumns"
      :rows="rolesStore.rows"
      :loading="rolesStore.loading"
      :error="rolesStore.error"
      :row-key="(row: Role) => row.id"
      empty-text="没有符合条件的角色"
      actions-title="操作"
      actions-width="150px"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-data_scope="{ row }">
        <span class="muted">{{ DATA_SCOPE_LABEL[row.data_scope] ?? row.data_scope }}</span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ formatDateTime(row.created_at) }}</span>
      </template>

      <template #actions="{ row }">
        <span class="table-actions">
          <PermissionButton code="role:update" type="text" @click="startEdit(row)">
            <NIcon :component="CreateOutline" />
            编辑
          </PermissionButton>
          <PermissionButton code="role:delete" type="text" @click="pendingDelete = row">
            <NIcon :component="TrashOutline" />
            删除
          </PermissionButton>
        </span>
      </template>
    </DataTable>

    <Pagination
      :total="rolesStore.total"
      :page-num="rolesStore.pageNum"
      :page-size="rolesStore.pageSize"
      :disabled="rolesStore.loading"
      @change="onPageChange"
    />

    <FormDialog
      :open="draftOpen"
      :title="isEditing ? '编辑角色' : '新增角色'"
      :loading="saving"
      :error="draftError"
      @cancel="draftOpen = false"
      @submit="save"
    >
      <div class="form-grid">
        <label class="field">
          <span class="field__label">角色编码</span>
          <input
            v-model.trim="draft.role_code"
            class="field__control"
            :disabled="isEditing"
            placeholder="如 SUPER_ADMIN"
          />
        </label>
        <label class="field">
          <span class="field__label">角色名称</span>
          <input v-model.trim="draft.role_name" class="field__control" placeholder="如 超级管理员" />
        </label>
        <label class="field">
          <span class="field__label">状态</span>
          <select v-model="draft.status" class="field__control">
            <option value="ACTIVE">启用</option>
            <option value="DISABLED">禁用</option>
          </select>
        </label>
        <label class="field field--full">
          <span class="field__label">描述</span>
          <input v-model.trim="draft.description" class="field__control" placeholder="选填" />
        </label>
      </div>

      <p class="hint">
        <template v-if="isEditing">
          角色编码是权限判定的标识，创建后不可修改；数据范围与资源授权请在「权限配置」页调整。
        </template>
        <template v-else>
          新建的角色默认没有任何权限，创建后请到「权限配置」页为它授权。
        </template>
      </p>
    </FormDialog>

    <ConfirmDialog
      :open="pendingDelete !== null"
      title="删除角色"
      danger
      :confirm-text="deleting ? '删除中…' : '确认删除'"
      :loading="deleting"
      :description="`删除后依赖该角色的用户将失去对应权限。角色编码 ${pendingDelete?.role_code ?? ''} 不可恢复。`"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    />
  </PageContainer>
</template>
