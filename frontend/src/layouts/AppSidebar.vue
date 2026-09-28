<script setup lang="ts">
/**
 * 侧边栏：菜单项**全部来自** `permissionStore.menuTree`（后端权限结果）。
 *
 * 这里没有任何业务权限白名单 —— FE-03 §7 明令禁止。
 * 菜单结构、层级都由后端给，前端只负责渲染。
 *
 * 关于图标
 * --------
 * `icon` 字段是后端存的**图标名称**（如 "setting"），不是可渲染字符。
 * 曾经直接 `{{ node.icon }}` 输出，"setting" 四个字母叠在菜单文字上。
 *
 * 现在的解析顺序是 **名称 → 编码 → 默认图标**：
 * 名称表覆盖后端已配置图标的情形；编码表覆盖后端没配图标的情形
 * （初始数据里只有顶级菜单配了图标，九个子菜单是 null —— 只认名称的话
 * 侧边栏看起来"一整个没有图标"）。
 *
 * ⚠️ 编码表是**纯展示映射**，不是权限白名单：命不中只回退默认图标，
 * 既不隐藏菜单也不放行菜单，可见性完全由后端返回的树决定。
 */
import { computed, ref, watch, type Component } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  AlbumsOutline,
  BookOutline,
  BusinessOutline,
  ChevronForwardOutline,
  DesktopOutline,
  DocumentTextOutline,
  GitNetworkOutline,
  KeyOutline,
  OptionsOutline,
  PeopleOutline,
  PersonCircleOutline,
  SettingsOutline,
  ShieldCheckmarkOutline,
  StatsChartOutline,
} from '@vicons/ionicons5'
import { usePermissionStore } from '@/stores/permission'
import type { MenuNode } from '@/stores/permission'
import { HOME_PATH } from '@/router/guard'

const permissionStore = usePermissionStore()
const route = useRoute()

const tree = computed<MenuNode[]>(() => permissionStore.menuTree)

/** 后端 `icon` 名称 → 图标组件。 */
const ICON_BY_NAME: Record<string, Component> = {
  setting: SettingsOutline,
  user: PeopleOutline,
  users: PeopleOutline,
  department: BusinessOutline,
  role: ShieldCheckmarkOutline,
  permission: KeyOutline,
  session: DesktopOutline,
  dictionary: BookOutline,
  param: OptionsOutline,
  'audit-log': DocumentTextOutline,
  trace: GitNetworkOutline,
  log: DocumentTextOutline,
}

/** 菜单**编码** → 图标组件：后端没配图标时按编码兜底。 */
const ICON_BY_CODE: Record<string, Component> = {
  'system:system': SettingsOutline,
  'system:user': PeopleOutline,
  'system:department': BusinessOutline,
  'system:role': ShieldCheckmarkOutline,
  'system:permission': KeyOutline,
  'system:permission-resource': AlbumsOutline,
  'system:session': DesktopOutline,
  'system:dictionary': BookOutline,
  'system:param': OptionsOutline,
  'system:audit-log': DocumentTextOutline,
  'system:trace': GitNetworkOutline,
  // 「日志管理」是顶级**分组**（迁移 `phase11_log_menu` 建立），
  // 它的两个子菜单编码仍是 `system:*` —— 本轮只调整层级不改编码。
  'log:manage': DocumentTextOutline,
}

function iconOf(node: MenuNode): Component {
  const byName = node.icon === null ? undefined : ICON_BY_NAME[node.icon]
  return byName ?? ICON_BY_CODE[node.code] ?? SettingsOutline
}

/**
 * 当前高亮的菜单。
 *
 * 按**路径相等**判定而不是靠 `router-link-active`：vue-router 的 active
 * 是"匹配记录是当前记录的子集"，对这里一堆平级路由虽然结果正确，
 * 但父级分组标题（不是链接）拿不到任何 active 类 —— 表现为
 * "点了子菜单，父级分组毫无反应"，看不出自己在哪一栏。
 *
 * 路径相等则父子都能算：先定位叶子，再把祖先链标成"含活动项"。
 */
const activeIds = computed<Set<string>>(() => {
  const ids = new Set<string>()
  const path = route.path
  const walk = (nodes: MenuNode[], ancestors: string[]): void => {
    for (const node of nodes) {
      const chain = [...ancestors, node.id]
      if (node.path === path && node.children.length === 0) {
        for (const id of chain) ids.add(id)
      }
      walk(node.children, chain)
    }
  }
  walk(tree.value, [])
  return ids
})

/** 树里是否已经有菜单命中当前路径（用于"没有任何高亮"时的高亮兜底提示）。 */
function isActive(node: MenuNode): boolean {
  return activeIds.value.has(node.id)
}

/** 分组标题：自身或任一后代命中即点亮。 */
function isGroupActive(node: MenuNode): boolean {
  return isActive(node)
}

/**
 * 分组是否被收起。
 *
 * 存的是**收起**集合而不是展开集合：默认状态（集合为空）= 全部展开。
 * 反过来存就要在菜单树到达时先把所有分组灌一遍，而"树什么时候到"
 * 取决于异步请求 —— 灌早了会被覆盖，灌晚了会闪一下全收起。
 *
 * 分组标题**不做导航**：它可能没有关联页面（`系统管理` / `日志管理` 都是
 * 纯分组），点它跳转只会落到一个空路由。点击的语义是展开 / 收起。
 */
const collapsed = ref<Set<string>>(new Set())

function toggleGroup(id: string): void {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
}

function isGroupOpen(node: MenuNode): boolean {
  return !collapsed.value.has(node.id)
}

/** 当前路由所在的分组链 —— 用户收起过的分组，只要自己走进去就要重新展开。 */
const activeGroupIds = computed<Set<string>>(() => {
  const out = new Set<string>()
  const walk = (nodes: MenuNode[]): void => {
    for (const node of nodes) {
      if (isGroupActive(node)) out.add(node.id)
      walk(node.children)
    }
  }
  walk(tree.value)
  return out
})

/**
 * 路由（或菜单树）变化后展开当前所在的分组。
 *
 * 没有这一条，用户收起「日志管理」再通过面包屑 / 直接改 URL 进「审计日志」，
 * 侧栏里就既没有高亮也没有条目 —— 看起来像"这一页不在菜单里"。
 * 折叠是导航的**辅助**，不能反过来把当前位置藏起来。
 */
watch([() => route.path, tree], () => {
  if (collapsed.value.size === 0) return
  const next = new Set(collapsed.value)
  for (const id of activeGroupIds.value) next.delete(id)
  if (next.size !== collapsed.value.size) collapsed.value = next
})

/** 个人中心是**静态**入口（不属于权限契约），单独放在侧栏底部。 */
const PROFILE_PATH = '/profile'

/**
 * 报表是**静态**入口，与个人中心同类：它是登录后的默认首页，
 * 必须人人可达，因此不进权限契约、不参与菜单树的渲染。
 *
 * 单独列在动态菜单**之前**：它是默认落地页，如果只能靠面包屑回去，
 * "我在哪一层菜单里"这个问题就没有入口可答。
 * 它同样**不是**权限白名单 —— 可见性由后端决定的部分仍是上面那棵树。
 */
const REPORT_PATH = HOME_PATH
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <span class="sidebar__logo">V</span>
      <span class="sidebar__name">VCTN 管理后台</span>
    </div>
    <nav class="sidebar__nav" aria-label="主导航">
      <!-- 静态首页入口：不来自权限契约（见 REPORT_PATH 的注释）。 -->
      <RouterLink
        class="sidebar__item"
        :class="{ 'is-active': route.path === REPORT_PATH }"
        :to="REPORT_PATH"
      >
        <span class="sidebar__icon"><NIcon :component="StatsChartOutline" :size="18" /></span>
        <span class="sidebar__label">报表</span>
      </RouterLink>

      <template v-if="tree.length > 0">
        <template v-for="node in tree" :key="node.id">
          <!-- 叶子且能解出路由 → 直接链接；否则渲染成不可点的标题。 -->
          <RouterLink
            v-if="node.children.length === 0 && node.path !== ''"
            class="sidebar__item"
            :class="{ 'is-active': isActive(node) }"
            :to="node.path"
          >
            <span class="sidebar__icon"><NIcon :component="iconOf(node)" :size="18" /></span>
            <span class="sidebar__label">{{ node.name }}</span>
          </RouterLink>
          <div v-else-if="node.children.length === 0" class="sidebar__item is-static">
            <span class="sidebar__icon"><NIcon :component="iconOf(node)" :size="18" /></span>
            <span class="sidebar__label">{{ node.name }}</span>
          </div>
          <div v-else class="sidebar__group">
            <!--
              分组标题是 `<button>` 而不是 `<div>`：它**不导航**，但可点击
              （展开 / 收起）。用 button 才能拿到键盘可达与 `aria-expanded`，
              这两点用带 @click 的 div 都拿不到。
            -->
            <button
              type="button"
              class="sidebar__group-title"
              :class="{ 'is-active': isGroupActive(node), 'is-collapsed': !isGroupOpen(node) }"
              :aria-expanded="isGroupOpen(node)"
              :title="node.name"
              @click="toggleGroup(node.id)"
            >
              <span class="sidebar__icon"><NIcon :component="iconOf(node)" :size="18" /></span>
              <span class="sidebar__label">{{ node.name }}</span>
              <NIcon
                class="sidebar__chevron"
                :class="{ 'is-open': isGroupOpen(node) }"
                :component="ChevronForwardOutline"
                :size="14"
              />
            </button>
            <div v-if="isGroupOpen(node)" class="sidebar__group-body">
              <RouterLink
                v-for="child in node.children"
                :key="child.id"
                class="sidebar__item sidebar__item--child"
                :class="{ 'is-active': isActive(child) }"
                :to="child.path"
              >
                <span class="sidebar__icon"><NIcon :component="iconOf(child)" :size="16" /></span>
                <span class="sidebar__label">{{ child.name }}</span>
              </RouterLink>
            </div>
          </div>
        </template>
      </template>
      <p v-else class="sidebar__empty">没有可用菜单</p>
    </nav>

    <!-- 个人中心不属于权限契约（人人都有），因此不进菜单树，固定放底部。 -->
    <div class="sidebar__foot">
      <RouterLink
        class="sidebar__item"
        :class="{ 'is-active': route.path === PROFILE_PATH }"
        :to="PROFILE_PATH"
      >
        <span class="sidebar__icon"><NIcon :component="PersonCircleOutline" :size="18" /></span>
        <span class="sidebar__label">个人中心</span>
      </RouterLink>
    </div>
  </aside>
</template>
