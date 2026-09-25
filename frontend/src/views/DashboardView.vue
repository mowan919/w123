<script setup lang="ts">
/**
 * 概览页：只读展示当前身份与已授权资源的**数量**，不放任何权限判定。
 *
 * 注意这里的边界：数量来自后端返回的权限契约。前端不据此放行任何 UI ——
 * 真正的按钮/接口级拦截由 `PermissionButton` 与后端守卫完成（FE-06 §4）。
 */
import { computed, onMounted } from 'vue'
import { NProgress, NTag } from 'naive-ui'
import {
  AppsOutline,
  CloudOutline,
  CubeOutline,
  GridOutline,
  KeyOutline,
} from '@vicons/ionicons5'

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

/** 已授权资源磁贴：图标与颜色随资源类型走，不随权限强弱走。 */
const stats = computed(() => [
  { key: 'pages', label: '可访问页面', value: permissionStore.pages.length, icon: AppsOutline, tint: '#3b6ef6' },
  { key: 'menus', label: '可见菜单', value: permissionStore.menus.length, icon: GridOutline, tint: '#7c5cff' },
  { key: 'apis', label: '可调用接口', value: permissionStore.apiCodes.size, icon: CloudOutline, tint: '#0ea5a5' },
  { key: 'buttons', label: '可用按钮', value: permissionStore.buttonCodes.size, icon: CubeOutline, tint: '#d97706' },
  { key: 'fields', label: '受控字段', value: permissionStore.fieldLevels.size, icon: KeyOutline, tint: '#12a150' },
])

/** 最大值用于让进度条有统一的参照，只表达"相对量级"，不代表任何配额。 */
const maxValue = computed(() => Math.max(1, ...stats.value.map((s) => s.value)))

const displayName = computed<string>(() => authStore.user?.display_name || authStore.user?.username || '管理员')

onMounted(() => {
  // 演示字典 store 的可用性：失败不阻塞页面渲染。
  void dictionaryStore.ensure('user_status').catch(() => undefined)
})
</script>

<template>
  <PageContainer title="概览" :description="`${displayName}，欢迎回来`">
    <!-- 欢迎区：身份 + 数据范围，一眼回答"我现在是谁、能看多宽"。 -->
    <section class="hero">
      <div class="hero__id">
        <span class="hero__avatar">{{ (displayName[0] ?? '?').toUpperCase() }}</span>
        <div class="hero__meta">
          <h2 class="hero__name">{{ displayName }}</h2>
          <p class="hero__sub">
            用户名 {{ authStore.user?.username ?? '—' }} · ID
            {{ authStore.user?.id ?? '—' }}
          </p>
        </div>
      </div>
      <div class="hero__tags">
        <NTag round :bordered="false" type="info" size="small">数据范围：{{ scopeText }}</NTag>
        <NTag round :bordered="false" size="small">权限版本 v{{ permissionStore.version }}</NTag>
      </div>
    </section>

    <!-- 资源磁贴 -->
    <section class="stats">
      <article v-for="item in stats" :key="item.key" class="stat">
        <span class="stat__icon" :style="{ background: `${item.tint}1f`, color: item.tint }">
          <component :is="item.icon" />
        </span>
        <div class="stat__body">
          <p class="stat__label">{{ item.label }}</p>
          <p class="stat__value" :style="{ color: item.tint }">{{ item.value }}</p>
        </div>
        <NProgress
          class="stat__bar"
          type="line"
          :percentage="Math.round((item.value / maxValue) * 100)"
          :show-indicator="false"
          :height="4"
          :border-radius="2"
          :fill-border-radius="2"
          :color="item.tint"
        />
      </article>
    </section>

    <p class="note">
      以上为后端计算并下发的权限契约概览；前端不据此替代服务端鉴权（FE-06 §4）。
    </p>
  </PageContainer>
</template>

<style scoped>
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 18px 20px;
  margin-bottom: 14px;
  border-radius: var(--vctn-radius-lg);
  color: #fff;
  background: linear-gradient(120deg, #17233d 0%, #1d3a8a 60%, var(--vctn-primary) 100%);
  box-shadow: var(--vctn-shadow-md);
}

.hero__id {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.hero__avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.28);
  font-size: 19px;
  font-weight: 650;
  flex: 0 0 auto;
}

.hero__name {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.hero__sub {
  margin: 2px 0 0;
  font-size: 12px;
  opacity: 0.82;
}

.hero__tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.stat {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: var(--vctn-radius);
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  box-shadow: var(--vctn-shadow-sm);
  overflow: hidden;
  transition:
    transform var(--vctn-motion),
    box-shadow var(--vctn-motion);
}

.stat:hover {
  transform: translateY(-2px);
  box-shadow: var(--vctn-shadow-md);
}

.stat__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  flex: 0 0 auto;
  font-size: 20px;
}

.stat__body {
  min-width: 0;
}

.stat__label {
  margin: 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}

.stat__value {
  margin: 2px 0 0;
  font-size: 26px;
  font-weight: 650;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

/* 进度条压在磁贴底部：它是"相对量级"的点缀，不该抢数字的位置。 */
.stat__bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 0;
}

.note {
  margin: 14px 0 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}
</style>
