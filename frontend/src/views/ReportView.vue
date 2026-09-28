<script setup lang="ts">
/**
 * 报表页面（登录后的**默认首页**）。
 *
 * ## 这一页回答什么
 *
 * "系统现在有多少人、多少人在线，以及各域的基础规模。"
 * 全部数字来自**一条**聚合请求（`GET /statistics/overview`）：
 * 分五路去调清单端点会拿到五个不同时刻的快照，而且"在线用户"根本不在
 * 用户域 —— 它是会话表的去重计数（见 `types/statistics.ts`）。
 *
 * ## 无权限 ≠ 0
 *
 * 后端按**域**逐个判权：操作者没有某个域的权限位时，该域以
 * `accessible: false` + 计数 `null` 返回。这里渲染成"无权限"，
 * 绝不兜底成 0 —— "看不到"与"一个都没有"是两件完全不同的事，
 * 后者会让运维以为系统是空的。
 *
 * ## 自己的权限范围也放在这里
 *
 * 一个没有任何管理权限的普通用户会看到整屏"无权限"，那对他毫无用处。
 * 因此页面下半部固定展示**他自己的**权限范围（页面 / 菜单 / 接口 / 按钮 /
 * 字段）与数据范围 —— 这部分不依赖任何管理类权限，人人都有。
 */
import { computed, onMounted, type Component } from 'vue'
import { NAlert, NButton, NIcon, NSpin, NTag } from 'naive-ui'
import {
  AppsOutline,
  BusinessOutline,
  CloudOutline,
  CubeOutline,
  DesktopOutline,
  DocumentTextOutline,
  GridOutline,
  KeyOutline,
  PeopleOutline,
  PulseOutline,
  RefreshOutline,
  ShieldCheckmarkOutline,
  StatsChartOutline,
} from '@vicons/ionicons5'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import { useStatisticsStore } from '@/stores/statistics'
import PageContainer from '@/components/layout/PageContainer.vue'

const appStore = useAppStore()
const authStore = useAuthStore()
const permissionStore = usePermissionStore()
const statisticsStore = useStatisticsStore()

const overview = computed(() => statisticsStore.overview)

const displayName = computed<string>(
  () => authStore.user?.display_name || authStore.user?.username || '管理员',
)

const scopeText = computed<string>(() => {
  // 优先用**响应里**的范围，而不是本地权限 store 的那份：
  // 这一栏紧挨着"数据时刻"，描述的是"这些数字是在什么范围下算出来的"，
  // 而唯一有资格回答这个问题的就是产出这些数字的那次请求。
  // 两者理论上一致；真出现分歧时，以响应为准才不会给出解释不了的数字。
  // （权限 store 那份是兜底：首次加载失败时至少还能说明我是谁。）
  switch (statisticsStore.overview?.scope_policy ?? permissionStore.dataScopePolicy) {
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

interface MetricCard {
  key: string
  label: string
  /** `null` = 该域不可见（或尚未加载）。 */
  value: number | null
  /** 该域是否可见。为 false 时`value` 必为 null。 */
  accessible: boolean
  /** 卡片的副标题（口径说明 / 拆分）。 */
  hint: string
  icon: Component
  tint: string
  /** 是否是"当前在线"这类会动的指标（画一个呼吸点）。 */
  live?: boolean
}

/**
 * 指标卡片。
 *
 * 顺序即优先级：**注册用户 / 在线用户**必须在前两位 —— 它们是这一页存在的理由，
 * 其余是"顺手能算出来"的补充。把补充项排到前面会让首页的第一眼
 * 落在"今日审计 13 条"这种次要数字上。
 */
const cards = computed<MetricCard[]>(() => {
  const data = overview.value
  if (data === null) return []
  const users = data.users
  const sessions = data.sessions
  return [
    {
      key: 'registered_users',
      label: '注册用户',
      value: users.total,
      accessible: users.accessible,
      hint:
        users.accessible && users.active !== null && users.disabled !== null
          ? `启用 ${users.active} · 禁用 ${users.disabled}`
          : '账号总数（未逻辑删除）',
      icon: PeopleOutline,
      tint: '#3b6ef6',
    },
    {
      key: 'online_users',
      label: '在线用户',
      value: sessions.online_users,
      accessible: sessions.accessible,
      hint:
        sessions.accessible && sessions.online_sessions !== null
          ? `在线会话 ${sessions.online_sessions}（一人可有多条）`
          : '当前会话有效的用户（去重）',
      icon: PulseOutline,
      tint: '#12a150',
      live: true,
    },
    {
      key: 'online_sessions',
      label: '在线会话',
      value: sessions.online_sessions,
      accessible: sessions.accessible,
      hint: '未撤销且会话总寿命未过',
      icon: DesktopOutline,
      tint: '#0ea5a5',
    },
    {
      key: 'total_sessions',
      label: '历史会话',
      value: sessions.total,
      accessible: sessions.accessible,
      hint: '含已撤销 / 已过期',
      icon: KeyOutline,
      tint: '#7c5cff',
    },
    {
      key: 'departments',
      label: '部门数',
      value: data.departments.total,
      accessible: data.departments.accessible,
      hint: '未逻辑删除（按数据范围）',
      icon: BusinessOutline,
      tint: '#d97706',
    },
    {
      key: 'roles',
      label: '角色数',
      value: data.roles.total,
      accessible: data.roles.accessible,
      hint: '全局计数，不受数据范围约束',
      icon: ShieldCheckmarkOutline,
      tint: '#e5484d',
    },
    {
      key: 'audit_today',
      label: '今日审计',
      value: data.audit.today,
      accessible: data.audit.accessible,
      hint:
        data.audit.accessible && data.audit.total !== null
          ? `累计 ${data.audit.total} 条`
          : 'UTC 自然日 00:00 起',
      icon: DocumentTextOutline,
      tint: '#6b7688',
    },
  ]
})

/** 一个分组都看不见的情况：整页只有"自己的权限范围"有意义。 */
const nothingAccessible = computed<boolean>(
  () => overview.value !== null && cards.value.every((card) => !card.accessible),
)

/** 首次加载（还没有任何数据、也还没失败）时才给占位，避免整页空白。 */
const showSkeleton = computed<boolean>(
  () => overview.value === null && statisticsStore.error === null,
)

/** 自己的权限范围（不依赖任何管理类权限，人人都有）。 */
const myScopes = computed<MetricCard[]>(() => [
  {
    key: 'pages',
    label: '可访问页面',
    value: permissionStore.pages.length,
    accessible: true,
    hint: '已获授权的页面',
    icon: AppsOutline,
    tint: '#3b6ef6',
  },
  {
    key: 'menus',
    label: '可见菜单',
    value: permissionStore.menus.length,
    accessible: true,
    hint: '侧栏实际展示的项',
    icon: GridOutline,
    tint: '#7c5cff',
  },
  {
    key: 'apis',
    label: '可调用接口',
    value: permissionStore.apiCodes.size,
    accessible: true,
    hint: '接口级授权（后端同样校验）',
    icon: CloudOutline,
    tint: '#0ea5a5',
  },
  {
    key: 'buttons',
    label: '可用按钮',
    value: permissionStore.buttonCodes.size,
    accessible: true,
    hint: '页面内的操作按钮',
    icon: CubeOutline,
    tint: '#d97706',
  },
  {
    key: 'fields',
    label: '受控字段',
    value: permissionStore.fieldLevels.size,
    accessible: true,
    hint: '字段级访问级别',
    icon: KeyOutline,
    tint: '#12a150',
  },
])

function display(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('zh-CN')
}

async function refresh(): Promise<void> {
  await statisticsStore.refresh()
  if (statisticsStore.error === null) {
    appStore.showNotice('success', '统计数据已更新')
  }
}

onMounted(() => {
  void statisticsStore.load()
})
</script>

<template>
  <PageContainer title="报表" description="系统运行概况：用户、会话与各域规模" :icon="StatsChartOutline">
    <!-- 欢迎区：身份 + 数据范围 + 快照时刻。"我现在是谁、能看多宽、数字是什么时候的"。 -->
    <section class="hero">
      <div class="hero__id">
        <span class="hero__avatar">{{ (displayName[0] ?? '?').toUpperCase() }}</span>
        <div class="hero__meta">
          <h2 class="hero__name">{{ displayName }}，欢迎回来</h2>
          <p class="hero__sub">
            用户名 {{ authStore.user?.username ?? '—' }} · 数据范围 {{ scopeText }}
          </p>
        </div>
      </div>
      <div class="hero__side">
        <div class="hero__tags">
          <NTag
            round
            size="small"
            :color="{ color: 'rgba(255,255,255,0.16)', textColor: '#fff', borderColor: 'transparent' }"
          >
            <template v-if="statisticsStore.generatedAtText">
              数据时刻 {{ statisticsStore.generatedAtText }}
            </template>
            <template v-else>尚未加载</template>
          </NTag>
          <NTag
            round
            size="small"
            :color="{ color: 'rgba(255,255,255,0.16)', textColor: '#fff', borderColor: 'transparent' }"
          >
            权限版本 v{{ permissionStore.version }}
          </NTag>
        </div>
        <NButton
          size="small"
          secondary
          :loading="statisticsStore.loading"
          class="hero__refresh"
          @click="refresh"
        >
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新
        </NButton>
      </div>
    </section>

    <NAlert
      v-if="statisticsStore.error"
      type="error"
      :bordered="false"
      class="report__alert"
      closable
      @close="statisticsStore.error = null"
    >
      {{ statisticsStore.error }}
    </NAlert>

    <NSpin :show="statisticsStore.loading && overview === null">
      <!-- 主指标：注册用户 / 在线用户 打头 -->
      <section class="stats" aria-label="系统统计">
        <article
          v-for="card in cards"
          :key="card.key"
          class="stat"
          :class="{ 'is-locked': !card.accessible }"
        >
          <span class="stat__icon" :style="{ background: `${card.tint}1f`, color: card.tint }">
            <NIcon :component="card.icon" :size="20" />
          </span>
          <div class="stat__body">
            <p class="stat__label">
              {{ card.label }}
              <span v-if="card.live && card.accessible && card.value !== null" class="stat__live" />
            </p>
            <template v-if="card.accessible">
              <p class="stat__value" :style="{ color: card.tint }">{{ display(card.value) }}</p>
              <p class="stat__hint">{{ card.hint }}</p>
            </template>
            <template v-else>
              <p class="stat__value is-locked">无权限</p>
              <p class="stat__hint">当前账号没有查看这一域的权限</p>
            </template>
          </div>
        </article>

        <!-- 首次加载（还没有任何数据，也还没失败）时给占位，避免整页空白。
             加载**失败**时不给骨架：那会让"请求挂了"看起来像"一直在加载"。 -->
        <article
          v-for="n in showSkeleton ? 4 : 0"
          :key="`skeleton-${n}`"
          class="stat is-skeleton"
        >
          <span class="skeleton skeleton--icon" />
          <div class="stat__body">
            <span class="skeleton skeleton--line" />
            <span class="skeleton skeleton--number" />
          </div>
        </article>
      </section>
    </NSpin>

    <p v-if="nothingAccessible" class="report__empty">
      当前账号没有任何统计查看权限。下列"我的权限范围"仍可查看 ——
      它只描述你自己被授予了什么，不需要任何管理类权限。
    </p>

    <!-- 我的权限范围：不依赖任何管理类权限，因此放在"无权限"提示之后作兜底价值 -->
    <section class="section">
      <h3 class="section__title">我的权限范围</h3>
      <div class="stats stats--compact">
        <article v-for="item in myScopes" :key="item.key" class="stat">
          <span class="stat__icon" :style="{ background: `${item.tint}1f`, color: item.tint }">
            <NIcon :component="item.icon" :size="18" />
          </span>
          <div class="stat__body">
            <p class="stat__label">{{ item.label }}</p>
            <p class="stat__value" :style="{ color: item.tint }">{{ display(item.value) }}</p>
            <p class="stat__hint">{{ item.hint }}</p>
          </div>
        </article>
      </div>
    </section>

    <p class="note">
      数字为一次请求生成的同一时刻快照。用户 / 会话 / 部门按你的数据范围统计，
      角色与审计是全局计数 —— 后者不受数据范围约束。
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

.hero__side {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero__tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 深色渐变底上的 secondary 按钮几乎看不见，显式给一层半透明白皮。 */
.hero__refresh {
  --n-color: rgba(255, 255, 255, 0.16) !important;
  --n-color-hover: rgba(255, 255, 255, 0.26) !important;
  --n-color-pressed: rgba(255, 255, 255, 0.32) !important;
  --n-text-color: #fff !important;
  --n-border: 1px solid rgba(255, 255, 255, 0.28) !important;
  --n-border-hover: 1px solid rgba(255, 255, 255, 0.46) !important;
}

.report__alert {
  margin-bottom: 12px;
}

.report__empty {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: var(--vctn-radius);
  border: 1px dashed var(--vctn-border-hover);
  background: var(--vctn-fill-muted);
  color: var(--vctn-text-weak);
  font-size: 13px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(224px, 1fr));
  gap: 12px;
}

.stats--compact {
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}

.stat {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border-radius: var(--vctn-radius);
  background: var(--vctn-surface);
  border: 1px solid var(--vctn-border);
  box-shadow: var(--vctn-shadow-sm);
  transition:
    transform var(--vctn-motion),
    box-shadow var(--vctn-motion);
}

.stat:hover {
  transform: translateY(-2px);
  box-shadow: var(--vctn-shadow-md);
}

/* 无权限的卡片保持可见但降一级：直接隐藏会让人以为"这一项不存在"，
   而它确实存在、只是这个人看不到。 */
.stat.is-locked {
  background: var(--vctn-fill-muted);
  border-style: dashed;
}

.stat.is-locked:hover {
  transform: none;
  box-shadow: var(--vctn-shadow-sm);
}

.stat__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex: 0 0 auto;
}

.stat__body {
  min-width: 0;
}

.stat__label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}

/* "在线"这类会动的指标：一个呼吸点比任何文字都更快地说明它是实时值。 */
.stat__live {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--vctn-success);
  box-shadow: 0 0 0 0 rgba(18, 161, 80, 0.5);
  animation: live-pulse 1.8s ease-out infinite;
}

@keyframes live-pulse {
  70% {
    box-shadow: 0 0 0 7px rgba(18, 161, 80, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(18, 161, 80, 0);
  }
}

.stat__value {
  margin: 4px 0 0;
  font-size: 26px;
  font-weight: 650;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.stat__value.is-locked {
  font-size: 17px;
  font-weight: 600;
  color: var(--vctn-text-disabled);
}

.stat__hint {
  margin: 4px 0 0;
  color: var(--vctn-text-weak);
  font-size: 11px;
  line-height: 1.4;
}

.section {
  margin-top: 18px;
}

.section__title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--vctn-text);
}

.note {
  margin: 14px 0 0;
  color: var(--vctn-text-weak);
  font-size: 12px;
}

/* ---------- 骨架 ---------- */
.stat.is-skeleton {
  pointer-events: none;
}

.skeleton {
  display: block;
  border-radius: var(--vctn-radius-sm);
  background: var(--vctn-fill-subtle);
  animation: skeleton-breathe 1.4s ease-in-out infinite;
}

.skeleton--icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex: 0 0 auto;
}

.skeleton--line {
  width: 68px;
  height: 11px;
}

.skeleton--number {
  width: 96px;
  height: 22px;
  margin-top: 8px;
}

@keyframes skeleton-breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

@media (prefers-reduced-motion: reduce) {
  .stat__live,
  .skeleton {
    animation: none;
  }
}
</style>
