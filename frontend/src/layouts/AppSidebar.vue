<script setup lang="ts">
/**
 * 侧边栏：菜单项**全部来自** `permissionStore.menuTree`（后端权限结果）。
 *
 * 这里没有任何业务权限白名单 —— FE-03 §7 明令禁止。
 * 菜单结构、图标、层级都由后端给，前端只负责渲染。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { usePermissionStore } from '@/stores/permission'
import type { MenuNode } from '@/stores/permission'

const permissionStore = usePermissionStore()

const tree = computed<MenuNode[]>(() => permissionStore.menuTree)
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <span class="sidebar__logo">V</span>
      <span class="sidebar__name">VCTN 管理后台</span>
    </div>
    <nav class="sidebar__nav" aria-label="主导航">
      <template v-if="tree.length > 0">
        <template v-for="node in tree" :key="node.id">
          <!-- 叶子且能解出路由 → 直接链接；否则渲染成不可点的标题。 -->
          <RouterLink
            v-if="node.children.length === 0 && node.path !== ''"
            class="sidebar__item"
            :to="node.path"
          >
            <span class="sidebar__icon">{{ node.icon ?? '•' }}</span>
            <span>{{ node.name }}</span>
          </RouterLink>
          <div v-else-if="node.children.length === 0" class="sidebar__item is-static">
            <span class="sidebar__icon">{{ node.icon ?? '•' }}</span>
            <span>{{ node.name }}</span>
          </div>
          <div v-else class="sidebar__group">
            <div class="sidebar__group-title">
              <span class="sidebar__icon">{{ node.icon ?? '▤' }}</span>
              <span>{{ node.name }}</span>
            </div>
            <RouterLink
              v-for="child in node.children"
              :key="child.id"
              class="sidebar__item sidebar__item--child"
              :to="child.path"
            >
              <span>{{ child.name }}</span>
            </RouterLink>
          </div>
        </template>
      </template>
      <p v-else class="sidebar__empty">没有可用菜单</p>
    </nav>
  </aside>
</template>
