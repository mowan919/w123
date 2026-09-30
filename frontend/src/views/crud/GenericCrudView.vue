<script setup lang="ts">
/**
 * GenericCrudView（VCTN §33）—— `crud/generic` 这一个注册表键的入口。
 *
 * 它只做一件事：**从当前路由解出"我在维护哪一个资源"**，然后把渲染
 * 交给 `CrudResourcePanel`。
 *
 * 为什么路由能反推出资源
 * ---------------------
 * 后端为 44 个实体生成的 PAGE 契约是 `/v31/<kebab>` + `component_path` = `crud/generic`
 * （见 `app/api/v1/endpoints/v31_*.py` 的 `prefix` 与 `scripts/_v31_seed.py`）。
 * 44 个页面共用同一个组件，靠路径里的 `<kebab>` 区分：
 * `/v31/biz-user` → 资源 `biz_user`（`V31_META_BY_KEBAB['biz-user']`）。
 *
 * `:key="kebab"` 不是装饰
 * ----------------------
 * vue-router 在同一个组件树上导航到"另一个路径"时，`<RouterView>` 会复用
 * 组件实例（不重新 mount）。虽然这里每条路由拿到的 `defineAsyncComponent`
 * 包装对象不同、实际会重建，但那属于 vue-router 的实现细节，**不该成为
 * 正确性的依赖**：一旦复用发生，`useColumnSettings` / `usePageQuery`
 * 这些"setup 期一次性初始化"的状态就会残留上一个资源的值。
 * 显式加 `:key` 让"换资源 = 重建面板"变成结构上的保证。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NAlert, NIcon } from 'naive-ui'
import { ConstructOutline } from '@vicons/ionicons5'
import PageContainer from '@/components/layout/PageContainer.vue'
import CrudResourcePanel from './CrudResourcePanel.vue'
import { V31_META_BY_KEBAB, type V31ResourceMeta } from '@/api/endpoints/v31-meta'

const route = useRoute()

/**
 * 路由路径 → kebab。
 *
 * 兼容带与不带尾斜杠两种写法；`meta.permission`（`v31:<kebab>:page`）只作兜底 ——
 * 主判据是路径，因为路径就是后端契约里的 `route_path`，两者必然一致。
 */
const kebab = computed<string>(() => {
  const fromPath = route.path.replace(/^\/+/, '').replace(/\/+$/, '')
  if (fromPath.startsWith('v31/')) return fromPath.slice('v31/'.length)
  const code = typeof route.meta.permission === 'string' ? route.meta.permission : ''
  const match = /^v31:(.+):page$/.exec(code)
  return match?.[1] ?? ''
})

const meta = computed<V31ResourceMeta | null>(() => V31_META_BY_KEBAB[kebab.value] ?? null)
</script>

<template>
  <CrudResourcePanel v-if="meta !== null" :key="kebab" :meta="meta" />

  <!--
    反查不到资源只可能是**路由与契约脱节**：契约里配了 `/v31/xxx` 的页面，
    但生成器没见过 `xxx` 这张表（或 `v31-meta.ts` 没重新生成）。
    这里如实报出来而不是渲染一张空表格 —— 后者会被当成"这个表本来就没数据"。
  -->
  <PageContainer v-else title="资源未登记" description="这条路由对应的资源不在 V3.1 元数据里。">
    <NAlert type="warning" :bordered="false">
      <template #icon>
        <NIcon :component="ConstructOutline" />
      </template>
      当前路径：<code>{{ route.path }}</code>（kebab：<code>{{ kebab || '（空）' }}</code>）。
      请确认后端已播种该 PAGE 契约，且 <code>scripts/gen_v31_crud.py</code> 已重新生成
      <code>v31-meta.ts</code>。
    </NAlert>
  </PageContainer>
</template>
