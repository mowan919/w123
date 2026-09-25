<script setup lang="ts">
/** 概览页：只读展示当前身份与数据范围，不放任何权限判定。 */
import { computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { useDictionaryStore } from '@/stores/dictionaries'
import PageContainer from '@/components/layout/PageContainer.vue'

const authStore = useAuthStore()
const permissionStore = usePermissionStore()
const dictionaryStore = useDictionaryStore()

const scopeText = computed<string>(() => {
  switch (permissionStore.dataScopePolicy) {
    case 'ALL':
      return '全部数据'
    case 'DEPARTMENT':
      return '仅本部门'
    case 'DEPARTMENT_CHILDREN':
      return '本部门及子部门'
    case 'SELF':
      return '仅本人'
    case 'CUSTOM':
      return '自定义部门集合'
    default:
      return '未配置'
  }
})

const counts = computed(() => ({
  pages: permissionStore.pages.length,
  menus: permissionStore.menus.length,
  buttons: permissionStore.buttonCodes.size,
  apis: permissionStore.apiCodes.size,
  fields: permissionStore.fieldLevels.size,
}))

onMounted(() => {
  // 演示字典 store 的可用性：失败不阻塞页面渲染。
  void dictionaryStore.ensure('user_status').catch(() => undefined)
})
</script>

<template>
  <PageContainer title="概览">
    <div class="grid">
      <div class="card">
        <h3>当前身份</h3>
        <p>用户名：<b>{{ authStore.user?.username }}</b></p>
        <p>显示名：<b>{{ authStore.user?.display_name }}</b></p>
        <p>用户 ID：<span class="muted">{{ authStore.user?.id }}</span></p>
      </div>
      <div class="card">
        <h3>数据范围</h3>
        <p>{{ scopeText }}</p>
        <p class="muted">
          由后端计算；前端不替代后端数据范围鉴权（FE-06 §4）。
        </p>
      </div>
      <div class="card">
        <h3>已授权资源</h3>
        <ul>
          <li>页面 {{ counts.pages }}</li>
          <li>菜单 {{ counts.menus }}</li>
          <li>按钮 {{ counts.buttons }}</li>
          <li>接口 {{ counts.apis }}</li>
          <li>字段 {{ counts.fields }}</li>
        </ul>
        <p class="muted">权限版本 v{{ permissionStore.version }}</p>
      </div>
    </div>
  </PageContainer>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.card {
  padding: 16px;
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  border-radius: var(--vctn-radius);
}

.card p {
  margin: 4px 0;
}

.card ul {
  margin: 4px 0 8px;
  padding-left: 18px;
}
</style>
