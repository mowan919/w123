import { http } from '../client'
import type { StatisticsOverview } from '@/types'

/**
 * 统计概览（报表页面）。
 *
 * 后端只有这一条读端点，授权在**服务层按域逐个完成**：操作者没有权限的分组
 * 会以 `accessible: false` + 计数 `null` 返回，而不是 403。
 *
 * 因此调用方**不要**写 403 分支 —— 一次报表请求不会因为"某个域没权限"
 * 而整体失败；要处理的是每个分组的 `accessible`。
 * 这样设计的原因见后端 `app/api/v1/endpoints/statistics.py` 的模块文档：
 * 报表是登录后的默认落地页，整体 403 会让没有管理权限的用户一登录就撞错误页。
 */
export function getStatisticsOverview(): Promise<StatisticsOverview> {
  return http.get<StatisticsOverview>('/admin/statistics/overview')
}
