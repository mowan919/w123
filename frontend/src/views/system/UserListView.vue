<script setup lang="ts">
/**
 * 用户管理（FE-06 §2）。
 *
 * 展示层的数据范围（列表天然受后端范围下推约束）与按钮层的 BUTTON 权限
 * 是两件事：前者后端返回多少就是多少，后者由 PermissionButton 控制。
 * 两者都不替代后端鉴权。
 */
import { onMounted, ref } from 'vue'
import { usePageQuery } from '@/composables/usePageQuery'
import * as api from '@/api/endpoints/organization'
import type { DepartmentTreeNode, User } from '@/types'
import PageContainer from '@/components/layout/PageContainer.vue'
import SearchForm from '@/components/data/SearchForm.vue'
import DataTable from '@/components/data/DataTable.vue'
import Pagination from '@/components/data/Pagination.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import { useAppStore } from '@/stores/app'
import { useDictionaryStore } from '@/stores/dictionaries'

const appStore = useAppStore()
const dictionaryStore = useDictionaryStore()

const filters = ref<{ keyword: string; status: string; department_id: string }>({
  keyword: '',
  status: '',
  department_id: '',
})

const { rows, total, pageNum, pageSize, loading, error, reload, onPageChange } = usePageQuery<User>(
  (query) => api.listUsers(query),
)

const departmentOptions = ref<Array<{ id: string; label: string }>>([])
const disableTarget = ref<User | null>(null)
const resetTarget = ref<User | null>(null)

function onSearch(): void {
  reload({
    keyword: filters.value.keyword || null,
    status: filters.value.status || null,
    department_id: filters.value.department_id || null,
  })
}

function onReset(): void {
  filters.value = { keyword: '', status: '', department_id: '' }
  reload({})
}

function statusClass(status: string): string {
  if (status === 'ACTIVE') return 'tag tag--active'
  if (status === 'LOCKED') return 'tag tag--locked'
  return 'tag tag--disabled'
}

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

async function confirmReset(): Promise<void> {
  const target = resetTarget.value
  if (target === null) return
  try {
    await api.resetUserPassword(target.id, { new_password: 'Temp@2026' })
    appStore.showNotice('success', '口令已重置，用户首次登录将被要求修改')
    resetTarget.value = null
  } catch (cause) {
    appStore.showNotice('error', cause instanceof Error ? cause.message : '操作失败')
  }
}

onMounted(() => {
  void reload()
  void dictionaryStore.ensure('user_status')
  // 部门树是唯一的部门数据来源（后端没有扁平列表端点）。
  void api
    .getDepartmentTree()
    .then(collectDepartments)
    .catch(() => undefined)
})

/**
 * 把部门树压平为下拉选项。
 *
 * 递归函数的参数类型要**显式写出来**：用 `Parameters<typeof collectNode>`
 * 做自引用会让 TS 在推断时陷入"children 在自己的类型标注里被引用"的循环，
 * 直接报 TS2502。
 */
function collectDepartments(nodes: DepartmentTreeNode[]): void {
  for (const node of nodes) {
    departmentOptions.value.push({ id: node.id, label: node.department_name })
    collectNode(node.children)
  }
}

function collectNode(children: DepartmentTreeNode[]): void {
  for (const child of children) {
    departmentOptions.value.push({ id: child.id, label: child.department_name })
    collectNode(child.children)
  }
}
</script>

<template>
  <PageContainer title="用户管理" description="部门维度的数据范围由后端下推到 SQL，前端不参与判权。">
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
        <select v-model="filters.department_id" class="field__control">
          <option value="">全部</option>
          <option v-for="option in departmentOptions" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select>
      </label>
    </SearchForm>

    <div style="margin-bottom: 12px">
      <PermissionButton code="user:create" type="primary" @click="appStore.showNotice('info', '新建用户入口（后端 UserCreateRequest 已对齐）')">
        新建用户
      </PermissionButton>
    </div>

    <DataTable
      :columns="[
        { key: 'username', title: '用户名' },
        { key: 'display_name', title: '姓名' },
        { key: 'phone', title: '手机号' },
        { key: 'email', title: '邮箱' },
        { key: 'department_id', title: '部门' },
        { key: 'status', title: '状态' },
        { key: 'created_at', title: '创建时间' },
      ]"
      :rows="rows"
      :row-key="(row: User) => row.id"
      :loading="loading"
      :error="error"
      empty-text="没有符合条件的用户"
    >
      <template #cell-status="{ row }">
        <span :class="statusClass(row.status)">{{ dictionaryStore.labelOf('user_status', row.status) || row.status }}</span>
      </template>
      <template #cell-phone="{ row }">
        <PermissionField :code="'field:user.phone'">
          <template #default="{ editable }">
            <input :value="row.phone ?? ''" :readonly="!editable" class="field__control" style="min-width: 120px" />
          </template>
        </PermissionField>
      </template>
      <template #cell-email="{ row }">
        <PermissionField :code="'field:user.email'">
          <template #default="{ editable }">
            <input :value="row.email ?? ''" :readonly="!editable" class="field__control" style="min-width: 200px" />
          </template>
        </PermissionField>
      </template>
      <template #cell-created_at="{ row }">{{ row.created_at }}</template>
    </DataTable>

    <Pagination
      :total="total"
      :page-num="pageNum"
      :page-size="pageSize"
      @change="onPageChange"
    />

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
      :open="resetTarget !== null"
      title="重置口令"
      :description="resetTarget ? `重置 ${resetTarget.username} 的口令后，该用户需重新登录。` : ''"
      confirm-text="确认重置"
      danger
      @cancel="resetTarget = null"
      @confirm="confirmReset"
    />
  </PageContainer>
</template>
