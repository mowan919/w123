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
import { onMounted, ref } from 'vue'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import { useAppStore } from '@/stores/app'
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

const columns: Array<DataTableColumn<Role>> = [
  { key: 'role_code', title: '角色编码' },
  { key: 'role_name', title: '角色名称' },
  { key: 'data_scope', title: '数据范围' },
  { key: 'status', title: '状态', width: '100px' },
  { key: 'created_at', title: '创建时间', width: '180px' },
]

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

const draft = ref<RoleDraft | null>(null)
const saving = ref(false)
const pendingDelete = ref<Role | null>(null)
const deleting = ref(false)

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
  draft.value = { id: null, role_code: '', role_name: '', description: '', status: 'ACTIVE' }
}

function startEdit(role: Role): void {
  draft.value = { id: role.id, role_code: role.role_code, role_name: role.role_name, description: role.description ?? '', status: role.status }
}

async function save(): Promise<void> {
  const current = draft.value
  if (current === null) return
  saving.value = true
  try {
    if (current.id === null) {
      await rolesStore.create({
        role_code: current.role_code,
        role_name: current.role_name,
        description: current.description,
        status: current.status,
      })
    } else {
      // 只发真正改动的字段：后端按 `model_fields_set` 分派，
      // 把没改的字段也塞进去会被当成"显式清空"（角色编码只读）。
      await rolesStore.update(current.id, {
        role_name: current.role_name,
        description: current.description,
        status: current.status,
      })
    }
    draft.value = null
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
  <PageContainer title="角色管理" description="角色是权限的载体。角色本身的继承关系由后端展开，前端只维护角色实体。">
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
      <PermissionButton code="role:create" type="primary" @click="startCreate">新增角色</PermissionButton>
      <span class="muted">角色编码不可改（SUPER_ADMIN 等特权角色以此为标识）；删除前请确认没有用户仅依赖该角色</span>
    </div>

    <DataTable
      :columns="columns"
      :rows="rolesStore.rows"
      :loading="rolesStore.loading"
      :error="rolesStore.error"
      :row-key="(row: Role) => row.id"
      empty-text="没有符合条件的角色"
    >
      <template #cell-status="{ row }">
        <span class="tag" :class="row.status === 'ACTIVE' ? 'tag--active' : 'tag--disabled'">
          {{ row.status === 'ACTIVE' ? '启用' : '禁用' }}
        </span>
      </template>
      <template #cell-data_scope="{ row }">
        <div class="cell">
          <PermissionButton code="role:edit" type="text" @click="startEdit(row)">编辑</PermissionButton>
          <span class="muted">{{ DATA_SCOPE_LABEL[row.data_scope] ?? row.data_scope }}</span>
          <span class="muted">（授权与数据范围见「权限配置」页）</span>
        </div>
      </template>
      <template #cell-created_at="{ row }">
        <span class="muted">{{ row.created_at }}</span>
      </template>
    </DataTable>

    <Pagination
      :total="rolesStore.total"
      :page-num="rolesStore.pageNum"
      :page-size="rolesStore.pageSize"
      :disabled="rolesStore.loading"
      @change="onPageChange"
    />

    <div v-if="draft !== null" class="editor">
      <h3 class="editor__title">{{ draft.id === null ? '新增角色' : '编辑角色' }}</h3>
      <label class="field">
        <span class="field__label">角色编码</span>
        <input v-model="draft.role_code" class="field__control" :disabled="draft.id !== null" placeholder="如 SUPER_ADMIN" />
      </label>
      <label class="field">
        <span class="field__label">角色名称</span>
        <input v-model="draft.role_name" class="field__control" />
      </label>
      <label class="field">
        <span class="field__label">状态</span>
        <select v-model="draft.status" class="field__control">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">禁用</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">描述</span>
        <input v-model="draft.description" class="field__control" />
      </label>
      <div class="editor__actions">
        <button class="btn btn--primary" type="button" :disabled="saving" @click="save">
          <span v-if="saving" class="spinner spinner--sm" aria-hidden="true" />
          保存
        </button>
        <button class="btn" type="button" :disabled="saving" @click="draft = null">取消</button>
      </div>
    </div>

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

<style scoped>
.cell {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
