/**
 * 统计概览（报表页面）—— 与后端 `app/schemas/statistics.py` **逐字段对齐**。
 *
 * 两个必须照抄的约定：
 *
 * 1. 每个分组都有 `accessible`，不可见时计数为 `null`。
 *    前端**不得**把 `null` 兜底成 `0` —— "没权限看"与"一个都没有"
 *    是两件事，渲染成 0 会让报表在无权限时看起来像"系统是空的"。
 * 2. `online_users` 是**去重后的人**，`online_sessions` 是会话数。
 *    一个人开三个标签页就是 3 条会话、1 个人。两者都要展示，
 *    只显示前者会让"数字为什么比昨天大"无法解释。
 */

import type { DateTime } from './common'
import type { DataScopePolicy } from './permission'

/** 用户域（**受数据范围约束**）。 */
export interface UserStatistics {
  accessible: boolean
  total: number | null
  active: number | null
  disabled: number | null
}

/** 会话域（**受数据范围约束**）。 */
export interface SessionStatistics {
  accessible: boolean
  /** 在线用户数（按 user_id 去重）。 */
  online_users: number | null
  /** 在线会话数（同一用户可有多条）。 */
  online_sessions: number | null
  /** 历史会话总数（含已撤销 / 已过期）。 */
  total: number | null
}

/** 只有一个"总数"的域（部门 / 角色）。 */
export interface TotalStatistics {
  accessible: boolean
  total: number | null
}

/** 审计域（**全局，不受数据范围约束**）。 */
export interface AuditStatistics {
  accessible: boolean
  /** 今日（UTC 自然日 00:00 起）记录数。 */
  today: number | null
  total: number | null
}

export interface StatisticsOverview {
  /** 本次统计的生成时刻（UTC）。 */
  generated_at: DateTime
  /**
   * `users` / `sessions` / `departments` 三个分组所依据的数据范围策略。
   * `roles` 与 `audit` 是全局计数，不适用该范围 —— 展示时必须说清楚，
   * 否则会被读成"我可见的角色有 N 个"。
   */
  scope_policy: DataScopePolicy
  users: UserStatistics
  sessions: SessionStatistics
  departments: TotalStatistics
  roles: TotalStatistics
  audit: AuditStatistics
}
