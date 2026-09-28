"""统计概览服务（报表页面的数据来源）。

Frozen / 已裁定依据
------------------
- Spec `04 §5`：在线状态与"后台在线用户查询" —— 在线判定的**唯一口径**在
  `app.repositories.session.online_session_condition`，本模块只负责做聚合。
- Spec `08 §10`：每个受保护 API 必须经过后端 API Permission 校验。
- Spec `10 §3`：SUPER_ADMIN 的 bypass 只能出现在集中式授权层。
- Spec `10 §10`：带数据范围的查询必须真正约束在 SQL 层，禁止内存过滤。

为什么"报表读"不落审计
--------------------
`10 §8` 要求"关键安全操作"可审计，读聚合数字不在其中：本端点没有目标资源、
不改变任何状态，而且它是**登录后的默认落地页**。若每打开一次首页就写一条审计，
审计表会以"每个用户每次登录"的频率增长，真正需要追责的事件被淹没在噪声里 ——
而审计 append-only 且保留两年，写进去的噪声是撤不回来的。

同理，某个分组不可见时也**不写 FAILURE 审计**：那不是"越权被拒"
（没有发生任何被拒绝的请求），而是"这个人的权限集合里没有这一项"，
与菜单少显示一项属于同一件事。

可见性模型（为什么不整体 403）
----------------------------
本端点只要求**已认证**，内容按域逐个判权：

```text
有权 → 该分组给出真实计数（users / sessions / departments 另叠加数据范围）
无权 → 该分组返回 None，端点据此输出 accessible=false 且计数为 null
```

整体 403 的写法更"简单"，但报表是**默认首页**：任何没有管理权限的普通用户
一登录就会撞在错误页上。逐个域降级的结果是"看得见自己有权看的那几项"，
安全性完全相同（无权的那部分一个数字都不返回），可用性差很多。

权限 → 分组 的映射**刻意复用各域既有的权限位**，不新增 `REPORT_READ`：
多一个权限位就要多一轮"谁能拿到它"的授权治理（资源定义 + 角色授权 + 迁移），
而它带来的可见性在安全上与现有权限位完全等价 ——
每个数字的能见度都不超过"直接去那个域的列表页翻一遍"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import CurrentActor
from app.core.scope import DataScope, ResolvedScope
from app.db.base import utc_now
from app.models.enums import UserStatus
from app.repositories.department import DepartmentRepository
from app.repositories.log_query import LogQueryRepository
from app.repositories.role import RoleRepository
from app.repositories.session import SessionListFilters, SessionRepository
from app.repositories.user import UserRepository
from app.services.authorization import ApiPermissionCode, AuthorizationService
from app.services.data_scope import DataScopeResolver


def utc_day_start(now: datetime) -> datetime:
    """`now` 所在 UTC 自然日的零点（`06 §2` 的时间统一为 UTC）。

    用 UTC 而不是服务器本地时区：本系统所有落库时间都是 UTC，
    若"今日"按本地时区切，同一个数字在不同部署环境（不同 TZ）下会不一样，
    而它出现在报表上时没有任何标注能让人看出这一点。
    """
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


# ----------------------------------------------------------------------
# 领域结果（每个 `| None` 表达"该域不可见"）
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserMetrics:
    """用户域计数（数据范围内）。"""

    total: int
    active: int
    disabled: int


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    """会话域计数（数据范围内）。"""

    online_users: int
    online_sessions: int
    total: int


@dataclass(frozen=True, slots=True)
class TotalMetric:
    """只有一个"总数"的域（部门 / 角色）。"""

    total: int


@dataclass(frozen=True, slots=True)
class AuditMetrics:
    """审计域计数（全局）。"""

    today: int
    total: int


@dataclass(frozen=True, slots=True)
class StatisticsOverview:
    """报表页一次请求需要的全部指标。

    字段为 `None` = **该域不可见**（操作者没有该域的权限位）。
    调用方必须把 `None` 渲染成"无权限"，不能退化成 0
    （"看不到"与"一个都没有"是两件事）。
    """

    generated_at: datetime
    scope_policy: DataScope
    users: UserMetrics | None
    sessions: SessionMetrics | None
    departments: TotalMetric | None
    roles: TotalMetric | None
    audit: AuditMetrics | None


class StatisticsService:
    """跨域只读聚合（报表页面）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._sessions = SessionRepository(session)
        self._departments = DepartmentRepository(session)
        self._roles = RoleRepository(session)
        self._logs = LogQueryRepository(session)
        self._scopes = DataScopeResolver(self._departments)
        self._authz = AuthorizationService(session)

    async def overview(self, *, actor: CurrentActor) -> StatisticsOverview:
        """生成一次统计快照。

        所有计数取自**同一个** `now`：会话在线判定依赖当前时间，
        若每个分组各自取一次 `utc_now()`，慢查询下会出现
        "在线会话数取自 T1、在线用户数取自 T2"这种同一响应内不一致的快照。
        单个 `now` 让整个响应在时间上自洽。
        """
        now = utc_now()
        codes = await self._authz.effective_api_codes(actor=actor)

        can_users = ApiPermissionCode.USER_MANAGE in codes
        can_sessions = ApiPermissionCode.SESSION_MANAGE in codes
        can_departments = ApiPermissionCode.DEPARTMENT_MANAGE in codes
        can_roles = ApiPermissionCode.ROLE_MANAGE in codes
        can_audit = ApiPermissionCode.AUDIT_READ in codes

        # 数据范围解析要查部门子树（递归 CTE），只有确实要看受范围约束的分组时
        # 才值得付这次开销 —— 一个只审计权限的用户不该为它多等一次查询。
        scope: ResolvedScope | None = None
        if can_users or can_sessions or can_departments:
            scope = await self._scopes.resolve(actor)

        users: UserMetrics | None = None
        sessions: SessionMetrics | None = None
        departments: TotalMetric | None = None
        if scope is not None:
            if can_users:
                users = await self._user_metrics(scope)
            if can_sessions:
                sessions = await self._session_metrics(scope, now=now)
            if can_departments:
                departments = TotalMetric(total=await self._departments.count_in_scope(scope))

        roles: TotalMetric | None = None
        if can_roles:
            # 角色是**全局配置面**，没有"属于哪个部门"的语义，因此不施加范围。
            roles = TotalMetric(total=await self._roles.count_roles())

        audit: AuditMetrics | None = None
        if can_audit:
            audit = AuditMetrics(
                today=await self._logs.count_audit_logs(created_from=utc_day_start(now)),
                total=await self._logs.count_audit_logs(),
            )

        return StatisticsOverview(
            generated_at=now,
            # 一个受范围约束的分组都看不到时，仍如实回报操作者自身的范围策略：
            # 它描述的是"这个人处在什么范围"，与他有没有报表权限无关。
            scope_policy=scope.scope if scope is not None else actor.data_scope,
            users=users,
            sessions=sessions,
            departments=departments,
            roles=roles,
            audit=audit,
        )

    # ------------------------------------------------------------------
    # 各域计数
    # ------------------------------------------------------------------
    async def _user_metrics(self, scope: ResolvedScope) -> UserMetrics:
        """用户域：总数 + 按状态拆分。

        三次 `COUNT(*)` 走同一个 `_scoped_conditions`，因此
        `active + disabled == total` 恒成立（未逻辑删除的用户必然处于
        某个状态；若将来新增第三个状态，等式变成不等式，
        而它由这里的同源条件保证不会被静默掩盖）。
        """
        total = await self._users.count_in_scope(scope)
        active = await self._users.count_in_scope(scope, status=UserStatus.ACTIVE)
        disabled = await self._users.count_in_scope(scope, status=UserStatus.DISABLED)
        return UserMetrics(total=total, active=active, disabled=disabled)

    async def _session_metrics(self, scope: ResolvedScope, *, now: datetime) -> SessionMetrics:
        """会话域：在线用户（去重）/ 在线会话 / 历史会话总数。

        `online=None` 表示"不按在线状态筛选"，即全部历史会话 —— 与
        `GET /sessions` 省略 `online` 的默认行为完全一致。
        """
        online = SessionListFilters(online=True)
        return SessionMetrics(
            online_users=await self._sessions.count_users_for_admin(scope, now=now, filters=online),
            online_sessions=await self._sessions.count_for_admin(scope, now=now, filters=online),
            total=await self._sessions.count_for_admin(scope, now=now),
        )


__all__ = [
    "AuditMetrics",
    "SessionMetrics",
    "StatisticsOverview",
    "StatisticsService",
    "TotalMetric",
    "UserMetrics",
    "utc_day_start",
]
