"""统计概览端点（报表页面 / 前端默认首页）。

| 方法 | 路径 | 依据 |
|---|---|---|
| GET | `/statistics/overview` | 报表页需求；契约属 INTERIM（`docs/DESIGN-DECISIONS.md §18`） |

关于授权位置（`DEBT-10-01` 的同类）
--------------------------------
本端点**不在路由层**声明单一权限位，因为报表是登录后的**默认落地页** ——
给它绑一个具体权限位，任何不具备该位的用户一登录就撞在 403 上。

授权改由**服务层按域逐个完成**（`app/services/statistics.py`）：
每个分组先问"操作者有没有这个域的权限位"，有则给真实计数
（users / sessions / departments 另叠加数据范围），没有则整个分组不返回数字。
因此"每个受保护 API 都经过后端 API Permission 校验"（`08 §10`）依然成立 ——
变的只是绑定位置，与 `sessions` / `dicts` / `params` 三条既有路径同一种形态
（因此同样登记在 `tests/test_route_authorization_guard.py` 的白名单里）。

与 `GET /auth/permissions` 的区别（那条也是"每次打开页面都调用"）
--------------------------------------------------------------
`/auth/permissions` 返回的是**调用者本人**的权限快照，含数据范围本身，
因此它不需要任何权限位（拥有它并不揭示别人的信息）。
本端点返回的是**别人**的汇总数字（有多少用户、谁在线），
因此每个分组都必须先过该域的权限位 —— 二者不可类比。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import CurrentActorDep, StatisticsServiceDep
from app.core.response import success_response
from app.schemas.statistics import (
    AuditStatistics,
    DepartmentStatistics,
    RoleStatistics,
    SessionStatistics,
    StatisticsOverviewResponse,
    UserStatistics,
)
from app.services.statistics import StatisticsOverview

router = APIRouter(tags=["Statistics"])


def _to_response(overview: StatisticsOverview) -> StatisticsOverviewResponse:
    """领域结果 → 响应 DTO。

    每个 `None` 分组输出为 `accessible=false` + 计数 `null`，
    **不是 0**：把"没权限看"渲染成 0 会让报表在无权限时看起来
    像"系统是空的"，那是一个比缺数据严重得多的误导。
    """
    users = overview.users
    sessions = overview.sessions
    departments = overview.departments
    roles = overview.roles
    audit = overview.audit

    return StatisticsOverviewResponse(
        generated_at=overview.generated_at,
        scope_policy=overview.scope_policy,
        users=UserStatistics(
            accessible=users is not None,
            total=users.total if users is not None else None,
            active=users.active if users is not None else None,
            disabled=users.disabled if users is not None else None,
        ),
        sessions=SessionStatistics(
            accessible=sessions is not None,
            online_users=sessions.online_users if sessions is not None else None,
            online_sessions=sessions.online_sessions if sessions is not None else None,
            total=sessions.total if sessions is not None else None,
        ),
        departments=DepartmentStatistics(
            accessible=departments is not None,
            total=departments.total if departments is not None else None,
        ),
        roles=RoleStatistics(
            accessible=roles is not None,
            total=roles.total if roles is not None else None,
        ),
        audit=AuditStatistics(
            accessible=audit is not None,
            today=audit.today if audit is not None else None,
            total=audit.total if audit is not None else None,
        ),
    )


@router.get("/statistics/overview", summary="统计概览（报表页面）")
async def statistics_overview(
    actor: CurrentActorDep,
    service: StatisticsServiceDep,
) -> JSONResponse:
    """一次请求返回报表页所需的全部聚合指标。

    **不落审计**：本端点没有目标资源、不改变任何状态，且是登录后的默认落地页 ——
    每次打开首页写一条审计，会让审计表以"每个用户每次登录"的频率增长，
    真正要追责的事件被淹没。理由与边界见 `app/services/statistics.py` 的模块文档。

    分组不可见时**也不返回 403**：那不是"越权被拒"（没有任何请求被拒绝），
    而是"这个人的权限集合里没有这一项"，与菜单少显示一项是同一件事。
    没有发生授权判定失败，因此没有 FAILURE 留痕可言。
    """
    overview = await service.overview(actor=actor)
    return success_response(_to_response(overview))
