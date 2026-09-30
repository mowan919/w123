import { http } from '../client'
import type { ID, PageResult } from '@/types/common'

/**
 * V3.1 四新增域（统一业务用户 / 成长中心 / Tools / Blog）的**通用 CRUD** 客户端
 * （VCTN §33）。
 *
 * 为什么这里只有 5 个函数却服务 44 张表
 * ------------------------------------
 * 后端这 44 个实体的结构层端点是**同一个形状**：
 *
 *   GET    /admin/<kebab>            → { list, total, pageNum, pageSize }
 *   GET    /admin/<kebab>/{id}       → 单条
 *   POST   /admin/<kebab>            → 单条
 *   PUT    /admin/<kebab>/{id}       → 单条
 *   DELETE /admin/<kebab>/{id}       → 被删除的那一条
 *
 * 逐表写 44 份文件名不同、内容相同的函数只会制造 44 处可以写错的地方。
 * 资源由 `kebab` 参数区分（`biz-user` / `blog-article` / …），
 * 与后端的 `APIRouter(prefix="/<kebab>")` 一一对应。
 *
 * ⚠️ 路径写的是 `/admin/<kebab>` 而不是 `/v31/<kebab>` ——
 * 前端 `baseUrl` 已经是 `/api/v1`（见 `router/index.ts`），
 * 而后端 `settings.api_v1_prefix` 是 `/api/v1/admin`。
 * 路由里的 `/v31/xxx` 是 **SPA 的页面地址**，与这里的接口地址无关。
 *
 * 业务规则（等级计算 / 积分记账 / 工具执行 / 博客发布流）属 §09-D 未冻结项，
 * 前端同样**不实现** —— 它只做结构层的增删改查。
 */

/** 一行结构层记录：字段集由后端契约决定，因此是开放索引 + 稳定的三个时间戳。 */
export interface CrudRecord {
  id: ID
  created_at: string
  updated_at: string | null
  [key: string]: unknown
}

/** 列表查询：分页参数 + 任意等值过滤列（后端 `XListQuery` 的 `filters()`）。 */
export interface CrudListQuery {
  pageNum: number
  pageSize: number
  [key: string]: string | number | boolean | null | undefined
}

export function listRecords<T extends CrudRecord = CrudRecord>(
  kebab: string,
  query: CrudListQuery,
): Promise<PageResult<T>> {
  return http.get<PageResult<T>>(`/admin/${kebab}`, query)
}

export function getRecord<T extends CrudRecord = CrudRecord>(
  kebab: string,
  id: ID,
): Promise<T> {
  return http.get<T>(`/admin/${kebab}/${id}`)
}

export function createRecord<T extends CrudRecord = CrudRecord>(
  kebab: string,
  body: Record<string, unknown>,
): Promise<T> {
  return http.post<T>(`/admin/${kebab}`, body)
}

export function updateRecord<T extends CrudRecord = CrudRecord>(
  kebab: string,
  id: ID,
  body: Record<string, unknown>,
): Promise<T> {
  return http.put<T>(`/admin/${kebab}/${id}`, body)
}

export function deleteRecord<T extends CrudRecord = CrudRecord>(
  kebab: string,
  id: ID,
): Promise<T> {
  return http.delete<T>(`/admin/${kebab}/${id}`)
}
