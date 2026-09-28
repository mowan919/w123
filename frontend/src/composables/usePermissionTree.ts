import type { ID } from '@/types/common'
import { GRANT_KINDS } from '@/types'
import type { GrantKind, GrantSelection, PermissionResource } from '@/types'

/**
 * 权限树的纯逻辑（无 Vue 依赖，可单测）。
 *
 * ## 为什么需要它
 *
 * 权限配置页原来是四列互不相干的复选框（PAGE / MENU / BUTTON / API），
 * 管理员看不出"哪些按钮属于哪个页面"，只能靠资源编码猜。树把同一批资源
 * 按后端**真实存在**的关系组织起来：菜单树（`parent_id`）→ 菜单挂载的页面
 * （`menu_pages`）→ 页面的按钮 / 接口（`parent_id`）。
 *
 * ## 一条不可越过的约束：父子**不能**强绑定
 *
 * 直觉上的"全联动"是"父项勾选状态 = 所有子项都勾选"，但真实数据否定了它：
 * `DEPARTMENT_ADMIN` 持有 4 个页面却只持有其中 9 个按钮
 * （`system:role:page` 被授权但它的按钮一个都没授；
 * `system:department:page` 只授了 create / update，没授 disable）。
 * 若父项状态由子项派生，那么任何人在这页按一次"保存"，
 * 这个角色的授权就会被**悄悄改成另一个形状** —— 页面被吞掉或按钮被放大，
 * 两种都是权限事故。
 *
 * 因此本模块的语义是：
 *
 * 1. **每个节点自己的勾选状态 = 它自己在不在授权集合里**（四类各自独立，
 *    与后端 `role_permissions` 的存储形状一一对应）。
 * 2. **联动只发生在"点击"时**：点一个节点，把同一状态向下给它的所有后代
 *    （含自身）。这是"一次点选带出一整块"的便利，不是状态推导。
 * 3. 父节点额外显示 `已授权/总数`，让"页面在、按钮不全"这种混合态**可见**，
 *    而不是被一个半选图标糊过去。
 *
 * `GrantKind` / `GrantSelection` 定义在 `types/permission.ts`：
 * 它们是领域概念（四类二元权限），不是这个模块私有的形状。
 */

/**
 * 数据异常分组。
 *
 * 树里 `kind === null` 的节点**只可能是**这两类分组 —— 菜单分组本身
 *（`系统管理` / `日志管理`）是 MENU 资源，`kind` 为 `'MENU'`。
 * 因此"是不是异常"不需要额外的布尔字段去猜。
 *
 * - `UNMOUNTED_PAGE`：页面没有被任何菜单挂载 ⇒ 侧边栏里没有入口，
 *   只能直接输入 URL 访问（判权只认 Page，所以授权本身有效）；
 * - `ORPHAN_MENU`：菜单的上级不存在（分类清单被截断或数据里有坏引用）
 *   ⇒ 它会被前端提到根层，导航层级与配置的不一致。
 */
export type TreeAnomaly = 'UNMOUNTED_PAGE' | 'ORPHAN_MENU'

/** 异常分组的显示名。**唯一来源** —— 组件与用例都从这里取或钉住它。 */
export const ANOMALY_GROUP_NAME: Record<TreeAnomaly, string> = {
  UNMOUNTED_PAGE: '未挂载菜单的页面',
  ORPHAN_MENU: '未归入上级菜单的菜单',
}

/** 一句话说明"这组东西为什么在这里、要怎么办"，直接渲染给管理员看。 */
export const ANOMALY_HINT: Record<TreeAnomaly, string> = {
  UNMOUNTED_PAGE: '没有导航入口，只能直接输入地址访问；需要入口请到「权限资源」页把它挂到某个菜单下',
  ORPHAN_MENU: '上级菜单不存在，导航里会被提到顶层；请到「权限资源」页修正它的上级',
}

export interface PermissionTreeNode {
  /**
   * `null` 表示**纯分组标签**（例如「未挂载菜单的页面」）：
   * 它不对应任何资源，因此不可勾选、不参与级联，仅用于分组。
   */
  kind: GrantKind | null
  id: ID | null
  code: string
  name: string
  /** 副标题：接口显示 `GET /sessions`，其余为空串。 */
  meta: string
  /** 见 `TreeAnomaly`。只有分组节点可能带它。 */
  anomaly?: TreeAnomaly
  children: PermissionTreeNode[]
}

export interface PermissionTreeRow {
  /** 折叠状态的键。分组节点用名字，资源节点用 `KIND:id`。 */
  key: string
  node: PermissionTreeNode
  depth: number
  hasChildren: boolean
  /** 自身 + 后代中可授权项的总数。 */
  totalCount: number
  /** 其中已经在授权集合里的数量。 */
  grantedCount: number
}

export interface PermissionTreeInput {
  menus: PermissionResource[]
  pages: PermissionResource[]
  buttons: PermissionResource[]
  apis: PermissionResource[]
  /**
   * 菜单 ID → 已挂载页面 ID。
   *
   * **必须**来自后端 `menu_pages`（`GET /admin/permission-resources/{id}/pages`），
   * 不能靠资源编码的命名规律推（`system:user` ↔ `system:user:page`）：
   * 那是把一份约定当成事实，将来只要有一个页面不按这个规律编码，
   * 它在界面上就会凭空消失（而且没有任何报错）。
   */
  menuPages: Record<ID, ID[]>
}

/** 资源节点在折叠集合与授权集合里的键。 */
export function grantKey(kind: GrantKind, id: ID): string {
  return `${kind}:${id}`
}

export function rowKey(node: PermissionTreeNode): string {
  return node.kind === null || node.id === null
    ? `group:${node.name}`
    : grantKey(node.kind, node.id)
}

function nodeOf(kind: GrantKind, resource: PermissionResource): PermissionTreeNode {
  const method = resource.api_method ?? ''
  const path = resource.api_path ?? ''
  return {
    kind,
    id: resource.id,
    code: resource.resource_code,
    name: resource.resource_name,
    meta: method === '' && path === '' ? '' : `${method} ${path}`.trim(),
    children: [],
  }
}

function bySortOrder(left: PermissionResource, right: PermissionResource): number {
  if (left.sort_order !== right.sort_order) return left.sort_order - right.sort_order
  return left.resource_code.localeCompare(right.resource_code)
}

/**
 * 按后端的真实关系构造权限树。
 *
 * 结构：菜单树（`parent_id`）→ 该菜单挂载的页面 → 页面的按钮与接口。
 * 没有被任何菜单挂载的页面单独归到「未挂载菜单的页面」分组下 ——
 * 它们依然是可授权的 PAGE（`09 §4` 判权只认 Page），
 * 只是当前没有导航入口，漏掉它们会让"页面明明授权了却不生效"无从排查。
 */
export function buildPermissionTree(input: PermissionTreeInput): PermissionTreeNode[] {
  const pageById = new Map<ID, PermissionResource>(input.pages.map((page) => [page.id, page]))

  /** 页面 → 该页面的按钮 + 接口。 */
  const pageNodeOf = (page: PermissionResource): PermissionTreeNode => {
    const node = nodeOf('PAGE', page)
    const children = [
      ...input.buttons.filter((item) => item.parent_id === page.id).map((item) => nodeOf('BUTTON', item)),
      ...input.apis.filter((item) => item.parent_id === page.id).map((item) => nodeOf('API', item)),
    ]
    children.sort((left, right) => {
      if (left.kind !== right.kind) return left.kind === 'BUTTON' ? -1 : 1
      return left.code.localeCompare(right.code)
    })
    node.children = children
    return node
  }

  const mountedPageIds = new Set<ID>()
  for (const ids of Object.values(input.menuPages)) {
    for (const id of ids) mountedPageIds.add(id)
  }

  /**
   * 已经渲染过的菜单 ID。
   *
   * 同时承担两个职责：防止**重复渲染**（同一个菜单被两条路径收进来），
   * 以及让数据里万一存在菜单环（A 的父是 B、B 的父是 A）时递归能终止。
   * 后端在资源写入期有环检测，这里是纵深防御 —— 界面卡死比少一行更难排查。
   */
  const renderedMenus = new Set<ID>()

  const menuNodeOf = (menu: PermissionResource): PermissionTreeNode => {
    renderedMenus.add(menu.id)
    const node = nodeOf('MENU', menu)
    const children: PermissionTreeNode[] = []
    // 子菜单按 sort_order 排在前面，挂载的页面跟在后面 ——
    // 导航树里也是这个顺序，两处一致才不会让管理员对着两个不同的层级找东西。
    const subMenus = input.menus
      .filter((item) => item.parent_id === menu.id && !renderedMenus.has(item.id))
      .sort(bySortOrder)
      .map(menuNodeOf)
    children.push(...subMenus)

    const mounted = (input.menuPages[menu.id] ?? [])
      .map((pageId) => pageById.get(pageId))
      .filter((page): page is PermissionResource => page !== undefined)
      .sort(bySortOrder)
    children.push(...mounted.map(pageNodeOf))

    node.children = children
    return node
  }

  const roots = input.menus
    .filter((menu) => menu.parent_id === null)
    .sort(bySortOrder)
    .map(menuNodeOf)

  // 防御：菜单的 `parent_id` 指向了一个不在清单里的菜单（分类清单被截断、
  // 或数据里存在坏引用）。这些菜单不是根、也不会被任何父菜单收进来，
  // 直接丢掉就等于"资源在界面上不见了" —— 那会让"授权了却没生效"无从排查。
  const leftovers = input.menus.filter((menu) => !renderedMenus.has(menu.id)).sort(bySortOrder)
  if (leftovers.length > 0) {
    const orphanGroup: PermissionTreeNode = {
      kind: null,
      id: null,
      code: '',
      name: ANOMALY_GROUP_NAME.ORPHAN_MENU,
      meta: '上级菜单缺失',
      anomaly: 'ORPHAN_MENU',
      children: [],
    }
    for (const menu of leftovers) {
      if (!renderedMenus.has(menu.id)) orphanGroup.children.push(menuNodeOf(menu))
    }
    roots.push(orphanGroup)
  }

  // 没有被任何菜单挂载的页面单独归到「未挂载菜单的页面」分组下 ——
  // 它们依然是可授权的 PAGE（`09 §4` 判权只认 Page），
  // 只是当前没有导航入口，漏掉它们会让"页面明明授权了却不生效"无从排查。
  //
  // ⚠️ 这一组**正常情况应当是空的**。它出现只有两种可能：
  //   1. 后端确实有意让某个页面不挂菜单（少见）；
  //   2. 配置漏了（多数）—— `scripts/seed_data.py` 的 `MENU_PAGES`
  //      曾经漏掉 `system:permission-resource:page`，于是「权限资源」页
  //      在侧栏里没有任何入口，只能手敲 URL。
  // 所以这一组不是"又一个分组"，而是**待处理的配置问题**，
  // 组件侧会额外渲染一句说明（见 `ANOMALY_HINT`）。
  const unmounted = input.pages
    .filter((page) => !mountedPageIds.has(page.id))
    .sort(bySortOrder)
  if (unmounted.length > 0) {
    roots.push({
      kind: null,
      id: null,
      code: '',
      name: ANOMALY_GROUP_NAME.UNMOUNTED_PAGE,
      meta: '没有导航入口',
      anomaly: 'UNMOUNTED_PAGE',
      children: unmounted.map(pageNodeOf),
    })
  }

  return roots
}

/** 授权集合 → `KIND:id` 集合（判定热路径用）。 */
export function selectionToSet(selection: GrantSelection): Set<string> {
  const out = new Set<string>()
  for (const kind of GRANT_KINDS) {
    for (const id of selection[kind]) out.add(grantKey(kind, id))
  }
  return out
}

function summarize(
  node: PermissionTreeNode,
  granted: ReadonlySet<string>,
): { total: number; granted: number } {
  let total = 0
  let hit = 0
  if (node.kind !== null && node.id !== null) {
    total += 1
    if (granted.has(grantKey(node.kind, node.id))) hit += 1
  }
  for (const child of node.children) {
    const sub = summarize(child, granted)
    total += sub.total
    hit += sub.granted
  }
  return { total, granted: hit }
}

/** 展平成可渲染的行；被折叠的节点其子树整体跳过。 */
export function flattenTree(
  nodes: PermissionTreeNode[],
  selection: GrantSelection,
  collapsed: ReadonlySet<string>,
): PermissionTreeRow[] {
  const granted = selectionToSet(selection)
  const out: PermissionTreeRow[] = []
  const walk = (list: PermissionTreeNode[], depth: number): void => {
    for (const node of list) {
      const key = rowKey(node)
      const summary = summarize(node, granted)
      out.push({
        key,
        node,
        depth,
        hasChildren: node.children.length > 0,
        totalCount: summary.total,
        grantedCount: summary.granted,
      })
      if (node.children.length > 0 && !collapsed.has(key)) walk(node.children, depth + 1)
    }
  }
  walk(nodes, 0)
  return out
}

/** 树里全部节点的键（「收起全部」用）。 */
export function allRowKeys(nodes: PermissionTreeNode[]): string[] {
  const out: string[] = []
  const walk = (list: PermissionTreeNode[]): void => {
    for (const node of list) {
      out.push(rowKey(node))
      walk(node.children)
    }
  }
  walk(nodes)
  return out
}

/** 有子节点的节点的键（「收起全部」只收有下级的，叶子没有可收的东西）。 */
export function expandableRowKeys(nodes: PermissionTreeNode[]): string[] {
  const out: string[] = []
  const walk = (list: PermissionTreeNode[]): void => {
    for (const node of list) {
      if (node.children.length > 0) out.push(rowKey(node))
      walk(node.children)
    }
  }
  walk(nodes)
  return out
}

/**
 * 树里的数据异常分组及其**受影响条数**（无异常时返回空数组）。
 *
 * 只扫**根层**：两个异常分组都挂在根上（见 `buildPermissionTree`），
 * 递归扫一遍只是多花时间，不会多找到东西。
 *
 * 返回条数而不是布尔值：界面要说"有 N 个页面没有导航入口"，
 * 而这个 N 只有这里知道（`children.length`）。
 */
export function collectAnomalies(
  nodes: PermissionTreeNode[],
): Array<{ kind: TreeAnomaly; count: number }> {
  const out: Array<{ kind: TreeAnomaly; count: number }> = []
  for (const node of nodes) {
    if (node.anomaly !== undefined) out.push({ kind: node.anomaly, count: node.children.length })
  }
  return out
}

/** 该节点自身 + 全部后代中的可授权项（分组节点自身不计）。 */
export function collectKeys(node: PermissionTreeNode): Array<{ kind: GrantKind; id: ID }> {
  const out: Array<{ kind: GrantKind; id: ID }> = []
  if (node.kind !== null && node.id !== null) out.push({ kind: node.kind, id: node.id })
  for (const child of node.children) out.push(...collectKeys(child))
  return out
}

/** 每个节点自身 + 后代的可授权键（判定某个节点是否"整块已授权"用）。 */
export function keysOfTree(nodes: PermissionTreeNode[]): string[] {
  const out: string[] = []
  for (const node of nodes) {
    for (const entry of collectKeys(node)) out.push(grantKey(entry.kind, entry.id))
  }
  return out
}


/**
 * 点选一个节点：把 `checked` 施加到它自己与它的全部后代。
 *
 * 返回**新的**选择对象（不改入参）—— 与 `useColumnSettings` 同一约定：
 * 就地改 Set / 数组会让 Vue 的响应式在"值没变但引用没换"时漏掉更新。
 */
export function applyCascade(
  selection: GrantSelection,
  node: PermissionTreeNode,
  checked: boolean,
): GrantSelection {
  const next: GrantSelection = {
    PAGE: [...selection.PAGE],
    MENU: [...selection.MENU],
    BUTTON: [...selection.BUTTON],
    API: [...selection.API],
  }
  for (const entry of collectKeys(node)) {
    const set = new Set(next[entry.kind])
    if (checked) set.add(entry.id)
    else set.delete(entry.id)
    next[entry.kind] = [...set]
  }
  return next
}

/** 某类资源的候选 id 全集（保存时用于识别"清单之外的既有授权"）。 */
export function universeOf(input: PermissionTreeInput): Record<GrantKind, Set<ID>> {
  const pageIds = new Set(input.pages.map((item) => item.id))
  const menuIds = new Set(input.menus.map((item) => item.id))
  const buttonIds = new Set(input.buttons.map((item) => item.id))
  // 接口可能挂在清单外的资源下（父资源被截断），因此接口的候选集合是
  // "被树收进来的接口 + 全部已知接口"。用全量更安全：只要它在清单里，
  // 就被视为"看得见"，用户对它的取舍就是有意的。
  const apiIds = new Set(input.apis.map((item) => item.id))
  return { PAGE: pageIds, MENU: menuIds, BUTTON: buttonIds, API: apiIds }
}

/**
 * 批量选择的三种模式。
 *
 * - `all`：把树上全部资源加入授权；
 * - `none`：把树上全部资源移出授权；
 * - `invert`：树上每项**逐个取反**（已授权 → 未授权，未授权 → 已授权）。
 */
export type BulkSelectionMode = 'all' | 'none' | 'invert'

/**
 * 对整棵树做一次批量选择。
 *
 * ## 只动"树上看得见的"资源
 *
 * 三种模式都**只遍历树里的资源 id**，不碰 `selection` 里那些不在树上的条目。
 * 那些是"候选清单之外的既有授权"（资源清单分类取回且有上限，角色可能持有
 * 没被取回的资源），它们在这棵树上根本看不见：
 *
 * - 若 `none` 顺手把它们也删掉，用户会看到"我按了取消全部，保存后还留着几条"
 *   （保存时 `resolveSubmission` 会原样保留）—— 界面与实际不符；
 * - 若 `invert` 去翻转它们，就等于**改动了画面上不存在的东西**：用户看见的
 *   是"A 从勾变没勾"，数据库里却有十几条看不见的授权被翻转了。
 *
 * 所以这里与 `applyCascade` 同一条原则：能改的只有看得见的东西。
 * 界面上另有提示说明"还有 N 项不在清单里、保存时原样保留"。
 *
 * 返回**新的**选择对象（不改入参），与 `applyCascade` / `useColumnSettings` 同一约定。
 */
export function applyBulkSelection(
  selection: GrantSelection,
  nodes: PermissionTreeNode[],
  mode: BulkSelectionMode,
): GrantSelection {
  const inTree: Record<GrantKind, Set<ID>> = {
    PAGE: new Set<ID>(),
    MENU: new Set<ID>(),
    BUTTON: new Set<ID>(),
    API: new Set<ID>(),
  }
  for (const node of nodes) {
    for (const entry of collectKeys(node)) inTree[entry.kind].add(entry.id)
  }

  const next: GrantSelection = {
    PAGE: [...selection.PAGE],
    MENU: [...selection.MENU],
    BUTTON: [...selection.BUTTON],
    API: [...selection.API],
  }

  for (const kind of GRANT_KINDS) {
    const target = inTree[kind]
    // 该类别在树上没有任何资源（例如候选清单里没有 FIELD/API）：不动它。
    // 空集合直接返回"原样"，否则 `none` 会把该类别整体清空 —— 那不是用户的意图。
    if (target.size === 0) continue
    const current = new Set(next[kind])
    for (const id of target) {
      if (mode === 'all') {
        current.add(id)
      } else if (mode === 'none') {
        current.delete(id)
      } else if (current.has(id)) {
        current.delete(id)
      } else {
        current.add(id)
      }
    }
    next[kind] = [...current]
  }

  return next
}

/**
 * 计算某一类最终要提交的 id 集合。
 *
 * ```text
 * 提交 = (候选清单内的勾选) ∪ (候选清单外的既有授权)
 * ```
 *
 * 右半部分不可省：资源清单是**分类取回**的（每类一次、有上限），
 * 若角色持有一条没被取回的资源，直接提交"清单内勾选"会把它删掉 ——
 * 表现为"我什么都没改，保存一下权限就少了一块"。保留它并在界面上提示
 * "有 N 项未出现在清单里、保存时会原样保留"，比静默删掉诚实得多。
 */
export function resolveSubmission(
  kind: GrantKind,
  selection: GrantSelection,
  universe: ReadonlySet<ID>,
  originalGranted: readonly ID[],
): ID[] {
  const kept = originalGranted.filter((id) => !universe.has(id))
  // 去重：某个 id 既可能被"清单内勾选"带上，也可能在 kept 里出现过。
  return [...new Set([...selection[kind].filter((id) => universe.has(id)), ...kept])]
}

/**
 * 被"清单之外"保留下来的授权数量（>0 时界面必须给出提示）。
 *
 * 不留 `kind` 参数：调用方本来就要按类别分别算，多一个只是多余的
 * 第二真相处（传错类别不会报错，只会让提示里的数字对不上）。
 */
export function unavailableCount(
  universe: ReadonlySet<ID>,
  originalGranted: readonly ID[],
): number {
  return originalGranted.filter((id) => !universe.has(id)).length
}
