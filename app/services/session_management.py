"""会话管理服务（Session Phase）。

Frozen 依据
-----------
- Spec `04 §3`：Session 必须记录 id / user / login time / last active / IP /
  user agent / device / expires_at / revoked_at / revoke_reason。
- Spec `04 §4`：支持 revoke one / revoke all；SUPER_ADMIN 可踢正常用户、
  不能被其他管理员踢、仅本人 logout；Department Admin 只能踢管理范围内用户。
- Spec `04 §5`：在线状态 + 后台在线用户查询。
- Spec `10 §3`：SUPER_ADMIN 保护必须集中封装（本模块不含任何超管分支）。
- Spec `10 §7`：Revoke 后 Token 必须不能继续访问；Revoke all 后全部失效。
- Spec `10 §8`：关键安全操作必须可审计。
- Spec `10 §10`：带数据范围的查询必须真正约束在 SQL 层，禁止内存过滤。
- Spec `08 §10`：每个受保护 API 必须经过后端 API Permission 校验。

与 `SessionService` 的分工
------------------------
| 关注点 | 归属 |
|---|---|
| 会话**生命周期**：创建 / 认证 / 刷新 / 本人登出 | `SessionService` |
| 会话**管理**：列表 / 在线查询 / 踢单个 / 踢全部 | 本模块 |

分开的理由不是"文件太长"，而是两者的**授权前提不同**：
`SessionService` 的全部操作只作用于**调用者自己的**会话（令牌即身份，无需数据范围）；
本模块的每个操作都要先回答"我能看到 / 能动**别人**吗"——
即 API 权限 + 数据范围 + SUPER_ADMIN 保护三重判定。
把两者混在一个类里，会让"自己的会话"与"别人的会话"两条路径
共享同一批私有方法，从而很难证明前者没有被后者的范围逻辑反向影响。

判定顺序（每个方法都一致）
------------------------
```text
1. API 权限（08 §10，SUPER_ADMIN 走集中式 bypass）
2. 数据范围（10 §10）—— 目标是否可见 / 可动
3. SUPER_ADMIN 保护（10 §3 / 00 §1#7 / 004 §13·§14）—— 写操作才需要
4. 执行 + 审计
```

第 2 步在 SQL 层也已施加（`SessionRepository._admin_conditions`）。
此处的显式判定不是为了"再过滤一次"，而是为了把
"数据范围内确实没有这个人"（空结果）与"越权请求"（403 + 留痕）区分开 ——
两者混同会让越权探测变得不可观测。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import ResolvedScope
from app.db.base import utc_now
from app.models.enums import SessionRevokeReason, UserStatus
from app.models.session import UserSession
from app.models.user import AdminUser
from app.repositories.department import DepartmentRepository
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService
from app.services.data_scope import DataScopeResolver

#: 审计中的资源类型（`06 §2`）。
SESSIONS_RESOURCE_TYPE = "SESSION"

#: 分页上界（与 `08` 契约的 `pageSize` 上限一致）。
_PAGE_SIZE_MAX = 100


@dataclass(frozen=True, slots=True)
class SessionView:
    """一条会话 + 所属用户 + 在线判定的组合视图。

    为什么把用户与在线判定一起返回，而不是只返回 `UserSession`：
    列表要展示"这是谁的会话"，在线与否也需要用户状态参与判断
    （见 `online_session_condition`）。若把这层拼装放到端点，
    判定逻辑就会有第二个实现点。
    """

    session: UserSession
    user: AdminUser
    online: bool


@dataclass(frozen=True, slots=True)
class SessionPage:
    """会话分页结果。"""

    items: tuple[SessionView, ...]
    total: int
    page_num: int
    page_size: int


@dataclass(frozen=True, slots=True)
class SessionRevokeOutcome:
    """踢单个会话的结果。"""

    session_id: int
    revoked: bool

    @property
    def already_revoked(self) -> bool:
        """是否在本次调用之前就已撤销（语义幂等，不是错误）。"""
        return not self.revoked


@dataclass(frozen=True, slots=True)
class UserSessionsRevokeOutcome:
    """踢某用户全部会话的结果。"""

    user_id: int
    revoked_count: int


def is_session_online(session: UserSession, user: AdminUser, *, now: datetime) -> bool:
    """会话是否**在线**。

    与 `SessionRepository._admin_conditions` 的 `online_only` 条件同一口径：
    **未撤销 + 会话总寿命未过 + 用户为 ACTIVE**。
    两处必须同步修改，否则会出现"筛选出来的是在线、字段却说不在线"的自相矛盾。
    """
    return session.is_active(now) and user.status is UserStatus.ACTIVE


class SessionManagementService:
    """会话管理（列表 / 在线查询 / 踢下线）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._sessions = SessionRepository(session)
        self._users = UserRepository(session)
        self._departments = DepartmentRepository(session)
        self._scope = DataScopeResolver(self._departments)
        self._authz = AuthorizationService(session)
        self._audit = AuditGuard(audit or NullAuditRecorder(), SESSIONS_RESOURCE_TYPE)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_sessions(
        self,
        *,
        actor: CurrentActor,
        page_num: int = 1,
        page_size: int = 20,
        online_only: bool = False,
    ) -> SessionPage:
        """分页列出**数据范围内**的全部会话（含已撤销 / 已过期）。

        `online_only=True` 时只返回在线会话 —— 这就是 Spec `04 §5` 的
        "后台在线用户查询"（每行都带 `username` 与 `online`）。
        """
        _validate_paging(page_num=page_num, page_size=page_size)
        with self._audit.denial_audited(
            actor=actor, action=AuditAction.SESSION_READ, resource_id=None
        ):
            await self._authz.assert_can_manage_sessions(actor=actor)
            scope = await self._scope.resolve(actor)

        page = await self._collect(
            scope,
            page_num=page_num,
            page_size=page_size,
            online_only=online_only,
            user_id=None,
        )
        self._audit.success(
            actor=actor,
            action=AuditAction.SESSION_READ,
            resource_id=None,
            after={"scope": "ALL", "online_only": online_only, "total": page.total},
        )
        return page

    async def list_user_sessions(
        self,
        *,
        actor: CurrentActor,
        user_id: int,
        page_num: int = 1,
        page_size: int = 20,
        online_only: bool = False,
    ) -> SessionPage:
        """分页列出**指定用户**的会话（`08 §4` 的 `GET /users/{id}/sessions`）。

        Raises:
            NotFoundError: 用户不存在或已逻辑删除。
            PermissionDeniedError: 用户不在操作者数据范围内。
        """
        _validate_paging(page_num=page_num, page_size=page_size)
        with self._audit.denial_audited(
            actor=actor, action=AuditAction.SESSION_READ, resource_id=user_id
        ):
            await self._authz.assert_can_manage_sessions(actor=actor)
            scope = await self._scope.resolve(actor)
            await self._load_visible_user(scope=scope, user_id=user_id)

        page = await self._collect(
            scope,
            page_num=page_num,
            page_size=page_size,
            online_only=online_only,
            user_id=user_id,
        )
        self._audit.success(
            actor=actor,
            action=AuditAction.SESSION_READ,
            resource_id=user_id,
            after={"scope": "USER", "online_only": online_only, "total": page.total},
        )
        return page

    # ------------------------------------------------------------------
    # 踢下线
    # ------------------------------------------------------------------
    async def revoke_session(self, *, actor: CurrentActor, session_id: int) -> SessionRevokeOutcome:
        """撤销**单个**会话（`08 §5` 的 `POST /sessions/{id}/revoke`）。

        幂等（DD-11 方案 A）：已撤销的会话再次提交同样返回成功 ——
        `10 §7` 要求的"令牌不可用"在两种情况下都已成立。

        Raises:
            NotFoundError: 会话不存在，或所属用户已不存在 / 已逻辑删除。
            PermissionDeniedError: 会话不在数据范围内，或所属用户是 SUPER_ADMIN。
        """
        with self._audit.denial_audited(
            actor=actor, action=AuditAction.AUTH_SESSION_REVOKE, resource_id=session_id
        ):
            await self._authz.assert_can_manage_sessions(actor=actor)
            scope = await self._scope.resolve(actor)

            target = await self._sessions.get(session_id)
            if target is None:
                raise NotFoundError("会话不存在")
            owner = await self._load_visible_user(scope=scope, user_id=target.user_id)
            await self._authz.assert_can_revoke_session(actor=actor, target_user_id=owner.id)

        revoked = await self._sessions.revoke_and_retire(
            target, reason=SessionRevokeReason.ADMIN_REVOKE, now=utc_now()
        )
        self._audit.success(
            actor=actor,
            action=AuditAction.AUTH_SESSION_REVOKE,
            resource_id=target.id,
            after={
                "scope": "SINGLE",
                "target_user_id": owner.id,
                "revoked_count": 1 if revoked else 0,
                "already_revoked": not revoked,
            },
        )
        return SessionRevokeOutcome(session_id=target.id, revoked=revoked)

    async def revoke_all_sessions(
        self, *, actor: CurrentActor, user_id: int
    ) -> UserSessionsRevokeOutcome:
        """撤销某用户的**全部**会话（`08 §4` 的 `POST /users/{id}/sessions/revoke-all`）。

        只撤销**当前仍有效**的会话：早已自然过期的会话不被打上 `ADMIN_REVOKE`,
        否则审计将无法区分"到期结束"与"被人踢掉"，等于改写历史。

        每个会话都经由 `SessionRepository.revoke_and_retire`
        （与本人登出、单踢完全同一条实现），因此 refresh 哈希留档、
        撤销原因与幂等语义三者与单踢逐字段一致。

        Raises:
            NotFoundError: 用户不存在或已逻辑删除。
            PermissionDeniedError: 用户不在数据范围内，或是 SUPER_ADMIN。
        """
        with self._audit.denial_audited(
            actor=actor, action=AuditAction.AUTH_SESSION_REVOKE, resource_id=user_id
        ):
            await self._authz.assert_can_manage_sessions(actor=actor)
            scope = await self._scope.resolve(actor)
            user = await self._load_visible_user(scope=scope, user_id=user_id)
            await self._authz.assert_can_revoke_session(actor=actor, target_user_id=user.id)

        now = utc_now()
        active = await self._sessions.list_active_for_user(user.id, now=now)
        revoked_count = 0
        for user_session in active:
            if await self._sessions.revoke_and_retire(
                user_session, reason=SessionRevokeReason.ADMIN_REVOKE, now=now
            ):
                revoked_count += 1

        self._audit.success(
            actor=actor,
            action=AuditAction.AUTH_SESSION_REVOKE,
            resource_id=None,
            after={
                "scope": "ALL",
                "target_user_id": user.id,
                "revoked_count": revoked_count,
                "already_revoked": revoked_count == 0,
            },
        )
        return UserSessionsRevokeOutcome(user_id=user.id, revoked_count=revoked_count)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _collect(
        self,
        scope: ResolvedScope,
        *,
        page_num: int,
        page_size: int,
        online_only: bool,
        user_id: int | None,
    ) -> SessionPage:
        """执行列表 + 计数（两者使用**完全相同**的条件）。"""
        now = utc_now()
        rows = await self._sessions.list_for_admin(
            scope,
            now=now,
            page_num=page_num,
            page_size=page_size,
            online_only=online_only,
            user_id=user_id,
        )
        total = await self._sessions.count_for_admin(
            scope,
            now=now,
            online_only=online_only,
            user_id=user_id,
        )
        items = tuple(
            SessionView(
                session=user_session,
                user=owner,
                online=is_session_online(user_session, owner, now=now),
            )
            for user_session, owner in rows
        )
        return SessionPage(items=items, total=total, page_num=page_num, page_size=page_size)

    async def _load_visible_user(self, *, scope: ResolvedScope, user_id: int) -> AdminUser:
        """读取目标用户并校验其在数据范围内。

        判定统一走 `ResolvedScope.allows_user`（`core/scope.py` 声明的
        "服务端二次校验入口"），而不是在此重写一遍部门比较 ——
        重写必然与 SQL 版（`scope_filters.user_scope_condition`）产生第二份真相。

        Raises:
            NotFoundError: 用户不存在 / 已逻辑删除。
            PermissionDeniedError: 不在数据范围内。
        """
        user = await self._users.get(user_id)
        if user is None:
            # 与 `UserService` 同一口径：不存在与已删除都表达为 404，
            # 不区分二者（否则可被用来枚举"哪些 ID 曾经存在"）。
            raise NotFoundError("用户不存在")
        if not scope.allows_user(user_id=user.id, department_id=user.department_id):
            raise PermissionDeniedError("用户不在当前数据范围内")
        return user


def _validate_paging(*, page_num: int, page_size: int) -> None:
    """分页参数兜底校验（与 `UserService.list_users` 同口径）。

    端点层已由 Pydantic 约束（`SessionListQuery`），此处是**纵深防御**：
    Service 是公共入口，直接以 `page_size=10**9` 调用会让查询退化为全表扫描。
    """
    if page_num < 1:
        raise BadRequestError("pageNum 必须大于等于 1")
    if not 1 <= page_size <= _PAGE_SIZE_MAX:
        raise BadRequestError(f"pageSize 必须在 1..{_PAGE_SIZE_MAX} 之间")


__all__ = [
    "SESSIONS_RESOURCE_TYPE",
    "SessionManagementService",
    "SessionPage",
    "SessionRevokeOutcome",
    "SessionView",
    "UserSessionsRevokeOutcome",
    "is_session_online",
]
