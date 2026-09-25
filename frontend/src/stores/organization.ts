import { defineStore } from 'pinia'
import type { DepartmentCreateRequest, DepartmentTreeNode, DepartmentUpdateRequest } from '@/types'
import type { ID } from '@/types/common'
import {
  createDepartment,
  disableDepartment,
  getDepartmentTree,
  updateDepartment,
} from '@/api/endpoints/organization'

/**
 * organizationStore —— 部门树（`08 §4`）。
 *
 * 为什么值得单独一个 store，而不是"哪个页面要用就自己拉一次"：
 *
 * `GET /admin/departments/tree` 是**唯一**的部门查询入口（后端没有扁平列表
 * 端点），而它在**三个**页面里各被拉了一次（部门管理 / 用户管理的筛选器 /
 * 权限配置页的 CUSTOM 部门集合），三处还各写了一份压平逻辑。复制三份的必然
 * 结果是其中的两份会悄悄长歪 —— 例如用户管理页原来把压平拆成了两个互相
 * 调用的函数，只是为了让 TS 别在自引用类型上绕死。
 *
 * 缓存还有一个**安全**理由，不只是"少发一个请求"：部门是数据范围的骨架。
 * 超管 sees 的树比部门管理员宽，如果这份树被缓存在组件里、而缓存又不清，
 * 换账号登录后看到的就是上一个（范围更宽的）用户的部门清单。
 */

/** 深度优先展开的一行。缩进和"路径式标签"都由 `depth` 派生。 */
export interface FlatDepartment {
  id: ID
  name: string
  depth: number
}

export interface DepartmentOption {
  id: ID
  /** 完整继承路径，如 `总公司 / 华东区` —— 同名部门靠路径区分。 */
  label: string
}

interface FlatEntry {
  node: DepartmentTreeNode
  depth: number
}

/**
 * 深度优先压平。
 *
 * 递归函数的参数类型**必须显式写出**，不能用 `Parameters<typeof walk>` 做
 * 自引用 —— TS 会在推断时陷入"参数类型里又引用了同一个函数"的循环，直接
 * 报 TS2502。这是把压平拆成两个互相调用的函数的真正原因，现在只需要一份。
 */
function flattenTree(nodes: DepartmentTreeNode[]): FlatEntry[] {
  const out: FlatEntry[] = []
  const walk = (list: DepartmentTreeNode[], depth: number): void => {
    for (const node of list) {
      out.push({ node, depth })
      walk(node.children, depth + 1)
    }
  }
  walk(nodes, 0)
  return out
}

export const useOrganizationStore = defineStore('organization', {
  state: () => ({
    tree: [] as DepartmentTreeNode[],
    /** 是否**成功**加载过一次。加载失败时保持 false，下次导航会重试。 */
    loaded: false,
    loading: false,
    error: null as string | null,
    /** 同一时刻只发一个请求（两个页面同时挂载时合并）。 */
    inflight: null as Promise<void> | null,
  }),

  getters: {
    /** 带层级的线性序列，供树形渲染与"全选 id"使用。 */
    flat(state): FlatDepartment[] {
      return flattenTree(state.tree).map(({ node, depth }) => ({
        id: node.id,
        name: node.department_name,
        depth,
      }))
    },

    /** 下拉选项：标签是完整路径，避免同名部门选不中。 */
    options(state): DepartmentOption[] {
      const out: DepartmentOption[] = []
      const walk = (nodes: DepartmentTreeNode[], path: string[]): void => {
        for (const node of nodes) {
          const next = [...path, node.department_name]
          out.push({ id: node.id, label: next.join(' / ') })
          walk(node.children, next)
        }
      }
      walk(state.tree, [])
      return out
    },

    ids(state): ID[] {
      return state.tree.map((node) => node.id)
    },

    byId(state): Map<ID, DepartmentTreeNode> {
      const map = new Map<ID, DepartmentTreeNode>()
      const walk = (nodes: DepartmentTreeNode[]): void => {
        for (const node of nodes) {
          map.set(node.id, node)
          walk(node.children)
        }
      }
      walk(state.tree)
      return map
    },
  },

  actions: {
    /** 取树；已成功加载过就直接复用。 */
    ensure(): Promise<void> {
      if (this.loaded) return Promise.resolve()
      if (this.inflight !== null) return this.inflight

      const task = this.reload().finally(() => {
        this.inflight = null
      })
      this.inflight = task
      return task
    },

    /** 无条件重新拉取。 */
    async reload(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        this.tree = await getDepartmentTree()
        this.loaded = true
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '部门树加载失败'
        this.tree = []
        this.loaded = false
      } finally {
        this.loading = false
      }
    },

    /**
     * 新建部门。
     *
     * 成功后重拉树：父节点下要多出一颗子树，只改内存里的某一层会立刻对不上。
     */
    async create(payload: DepartmentCreateRequest): Promise<void> {
      await createDepartment(payload)
      await this.reload()
    },

    /**
     * 改部门。**只发真正改动的字段** —— 后端按 `model_fields_set` 分派，
     * 把没改的字段也塞进去会被当成"显式清空"（后端 FINDING-9-02 的原话：
     * 非全局范围 403 改不动任何字段，全局范围会静默把用户移出部门）。
     * 请求体里出现 `undefined` 的字段同样不发（endpoint 层已经过滤）。
     */
    async update(departmentId: ID, payload: DepartmentUpdateRequest): Promise<void> {
      await updateDepartment(departmentId, payload)
      await this.reload()
    },

    /** 禁用后该部门及其下级不再参与数据范围下推，因此整棵树都要重算。 */
    async disable(departmentId: ID): Promise<void> {
      await disableDepartment(departmentId)
      await this.reload()
    },

    /** 换账号 / 登出时必须清：缓存里的树属于上一个用户的可见范围。 */
    reset(): void {
      this.tree = []
      this.loaded = false
      this.loading = false
      this.error = null
      this.inflight = null
    },
  },
})
