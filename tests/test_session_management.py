"""会话管理服务测试（Session Phase / 验收裁判 `004-session.md`）。

覆盖与裁判条目的对应关系
-----------------------
| 裁判条目 | 用例 |
|---|---|
| 可查询在线用户（§1） | `TestOnlineStatus` |
| 查看 Session（§2）至 revoked_at / reason（§8） | `TestSessionFields` |
| 可 revoke 单个 Session（§9） | `TestRevokeOne` |
| 可 revoke 全部 Session（§10） | `TestRevokeAll` |
| SUPER_ADMIN 可踢正常用户（§11） | `TestSuperAdminProtection` |
| Department Admin 只能踢管理范围内用户（§12） | `TestDataScope` |
| 任何管理员不能踢 SUPER_ADMIN（§13） | `TestSuperAdminProtection` |
| SUPER_ADMIN 只能本人 logout（§14） | `TestSuperAdminProtection` |
| Refresh Token 不保存明文（§15） | `TestPlaintextNeverPersisted` 等 |

另含 `08 §10`（后端 API 权限）与 `10 §10`（范围下推）的专项用例 ——
裁判未逐条列出，但它们是本阶段的安全前提。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.core.security.token import generate_token, hash_token
from app.db.base import utc_now
from app.models import (
    AdminUser,
    PermissionResourceType,
    SessionRefreshTokenHistory,
    UserSession,
    UserStatus,
)
from app.models.enums import RefreshTokenRetirement, SessionRevokeReason
from app.services.actor_factory import ActorFactory
from app.services.session import SessionService
from app.services.session_management import SessionManagementService
from tests.conftest import RecordingAuditRecorder
from tests.factories import (
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_session,
    make_user,
)

pytestmark = pytest.mark.integration

# ---- 部门 ----
DEPT_PARENT = 52001
DEPT_CHILD = 52002
DEPT_OTHER = 52003

# ---- 角色 / 权限资源 ----
ROLE_GLOBAL = 52011
ROLE_DEPT = 52012
ROLE_SELF = 52013
ROLE_NO_PERM = 52014
ROLE_SUPER = 52015
#: SESSION_MANAGE 是**同一个**权限资源：`uq_permission_resources_type_code_active`
#: 约束了 (resource_type, resource_code) 唯一，因此多个角色共享同一个资源 ID。
API_RES_SESSION_MANAGE = 52021

# ---- 用户 ----
U_GLOBAL = 52101
U_DEPT = 52102
U_SELF = 52103
U_NO_PERM = 52104
U_SUPER = 52105
U_IN_PARENT = 52106
U_IN_CHILD = 52107
U_OUT = 52108
U_DISABLED = 52109

# ---- 会话 ----
S_VALID = 52201
S_REVOKED = 52202
S_EXPIRED = 52203
S_IN_CHILD = 52204
S_OUT = 52205
S_DISABLED = 52206
S_SUPER = 52207
S_GLOBAL_OWN = 52208
S_DEPT_OWN = 52209
S_SELF_OWN = 52210
S_NO_PERM_OWN = 52211


@dataclass(frozen=True, slots=True)
class Seeded:
    """一次播种得到的会话与令牌（明文只存在于测试进程内）。"""

    session: UserSession
    access_token: str
    refresh_token: str


async def _seed_session(
    session,
    *,
    session_id: int,
    user_id: int,
    login_at: datetime | None = None,
    access_ttl: timedelta | None = None,
    refresh_ttl: timedelta | None = None,
    revoked: bool = False,
    revoke_reason: SessionRevokeReason | None = None,
    ip: str | None = "10.0.0.9",
    user_agent: str | None = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36",
) -> Seeded:
    """创建一条会话（令牌每次新生成，避免哈希唯一约束冲突）。"""
    access_token = generate_token()
    refresh_token = generate_token()
    started = login_at or utc_now()
    kwargs = {}
    if access_ttl is not None:
        kwargs["access_ttl"] = access_ttl
    if refresh_ttl is not None:
        kwargs["refresh_ttl"] = refresh_ttl

    user_session = await make_session(
        session,
        session_id=session_id,
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        login_at=started,
        revoked_at=(started if revoked else None),
        revoke_reason=(revoke_reason if revoked else None),
        ip=ip,
        user_agent=user_agent,
        device="Chrome · Windows · desktop",
        **kwargs,
    )
    return Seeded(session=user_session, access_token=access_token, refresh_token=refresh_token)


async def _grant(session, *, role_id: int) -> None:
    """给角色授予 SESSION_MANAGE API 权限（`08 §10` 的真实判权依据）。"""
    await link_role_permission(session, role_id=role_id, resource_id=API_RES_SESSION_MANAGE)


@dataclass(frozen=True, slots=True)
class Fixture:
    """播种后的关键对象与已装配的操作者。"""

    actors: dict[str, CurrentActor]
    sessions: dict[str, Seeded]


async def _seed(session) -> Fixture:
    """播种部门 / 角色 / 用户 / 会话，并装配各角色的操作者。"""
    await make_department(session, department_id=DEPT_PARENT, department_code="SESS_PARENT")
    await make_department(
        session,
        department_id=DEPT_CHILD,
        department_code="SESS_CHILD",
        parent_id=DEPT_PARENT,
    )
    await make_department(session, department_id=DEPT_OTHER, department_code="SESS_OTHER")

    # 角色
    await make_role(session, role_id=ROLE_GLOBAL, role_code="SESS_GLOBAL", data_scope=DataScope.ALL)
    await make_role(
        session,
        role_id=ROLE_DEPT,
        role_code="SESS_DEPT",
        data_scope=DataScope.DEPARTMENT_CHILDREN,
    )
    await make_role(session, role_id=ROLE_SELF, role_code="SESS_SELF", data_scope=DataScope.SELF)
    await make_role(
        session, role_id=ROLE_NO_PERM, role_code="SESS_NOPERM", data_scope=DataScope.ALL
    )
    await make_role(session, role_id=ROLE_SUPER, role_code="SUPER_ADMIN", data_scope=DataScope.ALL)

    # 只有前三个角色拿到 SESSION_MANAGE（ROLE_NO_PERM 故意不给）
    await make_permission_resource(
        session,
        resource_id=API_RES_SESSION_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="SESSION_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/sessions",
    )
    await _grant(session, role_id=ROLE_GLOBAL)
    await _grant(session, role_id=ROLE_DEPT)
    await _grant(session, role_id=ROLE_SELF)

    # 用户
    await make_user(
        session,
        user_id=U_GLOBAL,
        username="sess-global",
        department_id=DEPT_PARENT,
    )
    await make_user(session, user_id=U_DEPT, username="sess-dept", department_id=DEPT_PARENT)
    await make_user(session, user_id=U_SELF, username="sess-self", department_id=DEPT_PARENT)
    await make_user(session, user_id=U_NO_PERM, username="sess-noperm", department_id=DEPT_PARENT)
    # SUPER_ADMIN 刻意不分配部门：验证"保护与部门无关"
    await make_user(session, user_id=U_SUPER, username="sess-super", department_id=None)
    await make_user(
        session, user_id=U_IN_PARENT, username="sess-in-parent", department_id=DEPT_PARENT
    )
    await make_user(session, user_id=U_IN_CHILD, username="sess-in-child", department_id=DEPT_CHILD)
    await make_user(session, user_id=U_OUT, username="sess-out", department_id=DEPT_OTHER)
    await make_user(
        session,
        user_id=U_DISABLED,
        username="sess-disabled",
        department_id=DEPT_PARENT,
        status=UserStatus.DISABLED,
    )

    for user_id, role_id in (
        (U_GLOBAL, ROLE_GLOBAL),
        (U_DEPT, ROLE_DEPT),
        (U_SELF, ROLE_SELF),
        (U_NO_PERM, ROLE_NO_PERM),
        (U_SUPER, ROLE_SUPER),
        (U_IN_PARENT, ROLE_DEPT),
        (U_IN_CHILD, ROLE_DEPT),
        (U_OUT, ROLE_DEPT),
        (U_DISABLED, ROLE_DEPT),
    ):
        await link_user_role(session, user_id=user_id, role_id=role_id)

    # 会话：每个被管理对象各一条有效会话
    now = utc_now()
    sessions = {
        "valid": await _seed_session(session, session_id=S_VALID, user_id=U_IN_PARENT),
        "revoked": await _seed_session(
            session,
            session_id=S_REVOKED,
            user_id=U_IN_PARENT,
            revoked=True,
            revoke_reason=SessionRevokeReason.LOGOUT,
        ),
        "expired": await _seed_session(
            session,
            session_id=S_EXPIRED,
            user_id=U_IN_PARENT,
            login_at=now - timedelta(days=8),
            access_ttl=timedelta(days=7),
            refresh_ttl=timedelta(days=7),
        ),
        "in_child": await _seed_session(session, session_id=S_IN_CHILD, user_id=U_IN_CHILD),
        "out": await _seed_session(session, session_id=S_OUT, user_id=U_OUT),
        "disabled": await _seed_session(session, session_id=S_DISABLED, user_id=U_DISABLED),
        "super": await _seed_session(session, session_id=S_SUPER, user_id=U_SUPER),
        "global_own": await _seed_session(session, session_id=S_GLOBAL_OWN, user_id=U_GLOBAL),
        "dept_own": await _seed_session(session, session_id=S_DEPT_OWN, user_id=U_DEPT),
        "self_own": await _seed_session(session, session_id=S_SELF_OWN, user_id=U_SELF),
        "no_perm_own": await _seed_session(session, session_id=S_NO_PERM_OWN, user_id=U_NO_PERM),
    }

    factory = ActorFactory(session)
    actors = {
        "global": await factory.build_for_user_id(U_GLOBAL),
        "dept": await factory.build_for_user_id(U_DEPT),
        "self": await factory.build_for_user_id(U_SELF),
        "no_perm": await factory.build_for_user_id(U_NO_PERM),
        "super": await factory.build_for_user_id(U_SUPER),
    }
    assert all(actor is not None for actor in actors.values())
    return Fixture(actors={k: v for k, v in actors.items() if v is not None}, sessions=sessions)


def _service(session, audit=None) -> SessionManagementService:
    return SessionManagementService(session, audit=audit)


async def _load(session, session_id: int) -> UserSession:
    loaded = await session.get(UserSession, session_id)
    assert loaded is not None
    return loaded


def _ids(page) -> set[int]:
    return {view.session.id for view in page.items}


# ---------------------------------------------------------------------------
# §1 在线状态 / 在线用户查询
# ---------------------------------------------------------------------------
class TestOnlineStatus:
    """`04 §5`：在线状态由有效 Session 等规则计算；后台应提供在线用户查询。"""

    async def test_online_filter_keeps_only_usable_sessions(self, db_session) -> None:
        fixture = await _seed(db_session)
        page = await _service(db_session).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT, online_only=True
        )
        # U_IN_PARENT 有 3 条会话：有效 / 已撤销 / 已过期
        assert _ids(page) == {S_VALID}
        assert page.total == 1
        assert all(view.online for view in page.items)

    async def test_online_filter_excludes_disabled_user(self, db_session) -> None:
        """用户被禁用时其会话不可用（`authenticate` 会拒绝），故不算在线。"""
        fixture = await _seed(db_session)
        page = await _service(db_session).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_DISABLED, online_only=True
        )
        assert page.items == ()
        assert page.total == 0

    async def test_disabled_user_session_still_visible_when_not_filtered(self, db_session) -> None:
        """不筛在线时必须能看到它（排查"为什么这个账号突然掉线"需要它）。"""
        fixture = await _seed(db_session)
        page = await _service(db_session).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_DISABLED
        )
        assert _ids(page) == {S_DISABLED}
        assert page.items[0].online is False

    async def test_online_field_agrees_with_filter(self, db_session) -> None:
        """响应里的 `online` 字段与 `online=true` 的筛选结果必须一致。"""
        fixture = await _seed(db_session)
        service = _service(db_session)

        unfiltered = await service.list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        filtered = await service.list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT, online_only=True
        )
        assert {view.session.id for view in unfiltered.items if view.online} == _ids(filtered)

    async def test_global_list_covers_all_users_in_scope(self, db_session) -> None:
        fixture = await _seed(db_session)
        page = await _service(db_session).list_sessions(
            actor=fixture.actors["global"], online_only=True, page_size=100
        )
        # 全范围在线会话：U_IN_PARENT / U_IN_CHILD(×1 each) + 各管理员自身
        assert S_VALID in _ids(page)
        assert S_IN_CHILD in _ids(page)
        assert S_OUT in _ids(page)  # 全局范围应包含"其他部门"
        # 被禁用用户与已撤销 / 已过期会话不在在线列表里
        assert S_DISABLED not in _ids(page)
        assert S_REVOKED not in _ids(page)
        assert S_EXPIRED not in _ids(page)


# ---------------------------------------------------------------------------
# §2-§8 会话字段可见性
# ---------------------------------------------------------------------------
class TestSessionFields:
    """裁判 §2-§8：Session / 登录时间 / 最后活跃 / IP / UA·Device / expiry / revoked_at·reason。"""

    async def test_row_exposes_every_required_field(self, db_session) -> None:
        fixture = await _seed(db_session)
        page = await _service(db_session).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        view = next(item for item in page.items if item.session.id == S_VALID)
        row = view.session

        assert row.user_id == U_IN_PARENT
        assert row.login_at is not None
        assert row.last_active_at is not None
        assert row.ip == "10.0.0.9"
        assert row.user_agent is not None
        assert row.device == "Chrome · Windows · desktop"
        assert row.expires_at > row.login_at
        assert row.refresh_expires_at >= row.expires_at
        assert row.revoked_at is None
        assert row.revoke_reason is None
        # 所属用户信息一并返回，供列表直接展示
        assert view.user.username == "sess-in-parent"

    async def test_revoked_row_shows_time_and_reason(self, db_session) -> None:
        fixture = await _seed(db_session)
        page = await _service(db_session).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        row = next(item.session for item in page.items if item.session.id == S_REVOKED)
        assert row.revoked_at is not None
        assert row.revoke_reason is SessionRevokeReason.LOGOUT

    async def test_response_model_exposes_no_token_material(self) -> None:
        """响应契约里**没有任何**令牌字段（明文与哈希都不暴露）。"""
        from app.schemas.session import SessionResponse

        field_names = set(SessionResponse.model_fields)
        assert not {name for name in field_names if "token" in name}
        assert "password_hash" not in field_names


# ---------------------------------------------------------------------------
# §9 踢单个会话
# ---------------------------------------------------------------------------
class TestRevokeOne:
    """裁判 §9：可 revoke 单个 Session；`10 §7`：Revoke 后 Token 必须不能继续访问。"""

    async def test_revoke_invalidates_access_and_refresh(self, db_session) -> None:
        fixture = await _seed(db_session)
        target = fixture.sessions["valid"]

        outcome = await _service(db_session).revoke_session(
            actor=fixture.actors["global"], session_id=S_VALID
        )
        assert outcome.revoked is True
        assert outcome.already_revoked is False

        row = await _load(db_session, S_VALID)
        assert row.revoked_at is not None
        assert row.revoke_reason is SessionRevokeReason.ADMIN_REVOKE

        # 令牌立即不可用（`10 §7`）—— access 与 refresh 两条路径都要验
        from app.core.errors import AuthenticationError

        service = SessionService(db_session)
        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=target.access_token)
        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=target.refresh_token)

    async def test_revoke_is_idempotent_and_keeps_first_reason(self, db_session) -> None:
        """DD-11 方案 A：语义幂等；且不改写第一个撤销原因（第一个才是真相）。"""
        fixture = await _seed(db_session)
        service = _service(db_session)

        await service.revoke_session(actor=fixture.actors["global"], session_id=S_REVOKED)
        again = await service.revoke_session(actor=fixture.actors["global"], session_id=S_REVOKED)
        assert again.revoked is False
        assert again.already_revoked is True

        row = await _load(db_session, S_REVOKED)
        assert row.revoke_reason is SessionRevokeReason.LOGOUT

    async def test_unknown_session_is_not_found(self, db_session) -> None:
        fixture = await _seed(db_session)
        with pytest.raises(NotFoundError):
            await _service(db_session).revoke_session(
                actor=fixture.actors["global"], session_id=599999
            )

    async def test_revoke_audited(self, db_session, audit_recorder) -> None:
        fixture = await _seed(db_session)
        await _service(db_session, audit_recorder).revoke_session(
            actor=fixture.actors["global"], session_id=S_VALID
        )
        event = audit_recorder.find("AUTH_SESSION_REVOKE")
        assert event is not None
        assert str(event.result) == "SUCCESS"
        assert event.resource_type == "SESSION"
        assert event.resource_id == S_VALID
        assert event.after_data["scope"] == "SINGLE"
        assert event.after_data["target_user_id"] == U_IN_PARENT
        assert event.after_data["revoked_count"] == 1


# ---------------------------------------------------------------------------
# §10 踢全部会话
# ---------------------------------------------------------------------------
class TestRevokeAll:
    """裁判 §10：可 revoke 全部 Session；`10 §7`：全部对应 Session 都必须失效。"""

    async def test_revoke_all_invalidates_every_active_session(self, db_session) -> None:
        fixture = await _seed(db_session)
        outcome = await _service(db_session).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        # U_IN_PARENT 有 3 条会话，但只有 1 条当前有效
        assert outcome.revoked_count == 1
        assert outcome.user_id == U_IN_PARENT

        row = await _load(db_session, S_VALID)
        assert row.revoked_at is not None
        assert row.revoke_reason is SessionRevokeReason.ADMIN_REVOKE

        from app.core.errors import AuthenticationError

        with pytest.raises(AuthenticationError):
            await SessionService(db_session).authenticate(
                access_token=fixture.sessions["valid"].access_token
            )

    async def test_revoke_all_does_not_rewrite_history(self, db_session) -> None:
        """已撤销 / 已自然过期的会话不被改写 —— 否则审计无法区分"到期"与"被踢"。"""
        fixture = await _seed(db_session)
        await _service(db_session).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )

        already = await _load(db_session, S_REVOKED)
        assert already.revoke_reason is SessionRevokeReason.LOGOUT

        expired = await _load(db_session, S_EXPIRED)
        assert expired.revoked_at is None
        assert expired.revoke_reason is None

    async def test_revoke_all_revokes_multiple_sessions(self, db_session) -> None:
        """同一用户的多条会话都要失效（`10 §7` 的"全部对应 Session"）。"""
        fixture = await _seed(db_session)
        await _seed_session(db_session, session_id=52221, user_id=U_IN_PARENT)
        await _seed_session(
            db_session,
            session_id=52222,
            user_id=U_IN_PARENT,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1",
        )

        outcome = await _service(db_session).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        assert outcome.revoked_count == 3

        # `10 §7`："Revoke all 后所有对应 Session 都必须失效"——
        # 判据是**不再存在可用会话**，而不是"一条未撤销的都不剩"：
        # 已自然过期的那条（S_EXPIRED）按设计保持原样（改它等于改写历史）。
        alive = (
            (
                await db_session.execute(
                    select(UserSession.id).where(
                        UserSession.user_id == U_IN_PARENT,
                        UserSession.revoked_at.is_(None),
                        UserSession.refresh_expires_at > utc_now(),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert alive == []

    async def test_revoke_all_retires_refresh_tokens_like_single_revoke(self, db_session) -> None:
        """全踢与单踢共用同一实现：都要为 refresh 哈希留档（取证线索一致）。"""
        fixture = await _seed(db_session)
        await _service(db_session).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        retired = (
            (
                await db_session.execute(
                    select(SessionRefreshTokenHistory.reason).where(
                        SessionRefreshTokenHistory.session_id == S_VALID
                    )
                )
            )
            .scalars()
            .all()
        )
        assert RefreshTokenRetirement.SESSION_REVOKED in retired
        # 留档的是**哈希**，而留档用的正是那条会话当时的 refresh 令牌
        retired_hash = (
            await db_session.execute(
                select(SessionRefreshTokenHistory.token_hash).where(
                    SessionRefreshTokenHistory.session_id == S_VALID
                )
            )
        ).scalar_one()
        assert retired_hash == hash_token(fixture.sessions["valid"].refresh_token)

    async def test_revoke_all_on_user_without_sessions(self, db_session) -> None:
        """没有有效会话时同样是成功（语义幂等），只是计数为 0。"""
        fixture = await _seed(db_session)
        await make_user(db_session, user_id=52131, username="sess-nosessions")
        outcome = await _service(db_session).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=52131
        )
        assert outcome.revoked_count == 0

    async def test_revoke_all_audited_with_count(self, db_session, audit_recorder) -> None:
        fixture = await _seed(db_session)
        await _service(db_session, audit_recorder).revoke_all_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        event = audit_recorder.find("AUTH_SESSION_REVOKE")
        assert event is not None
        assert event.after_data["scope"] == "ALL"
        assert event.after_data["target_user_id"] == U_IN_PARENT
        assert event.after_data["revoked_count"] == 1


# ---------------------------------------------------------------------------
# §13 / §14 SUPER_ADMIN 保护
# ---------------------------------------------------------------------------
class TestSuperAdminProtection:
    """裁判 §13/§14：任何管理员不能踢 SUPER_ADMIN；SUPER_ADMIN 只能本人 logout。"""

    async def test_super_admin_can_revoke_normal_user(self, db_session) -> None:
        """裁判 §11：SUPER_ADMIN 可踢正常用户。"""
        fixture = await _seed(db_session)
        outcome = await _service(db_session).revoke_session(
            actor=fixture.actors["super"], session_id=S_VALID
        )
        assert outcome.revoked is True

    async def test_even_super_admin_cannot_revoke_peer_super_admin(self, db_session) -> None:
        """§13 取更严读法：**任何**管理员（含另一位 SUPER_ADMIN）都不得经管理端点撤销。"""
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        with pytest.raises(PermissionDeniedError):
            await _service(db_session, recorder).revoke_session(
                actor=fixture.actors["super"], session_id=S_SUPER
            )

        row = await _load(db_session, S_SUPER)
        assert row.revoked_at is None  # 拒绝必须"什么都没做"
        assert recorder.failures(), "越权尝试必须留痕"

    async def test_global_admin_cannot_revoke_super_admin(self, db_session) -> None:
        """全范围管理员也踢不动超管（保护与数据范围无关）。"""
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        with pytest.raises(PermissionDeniedError):
            await _service(db_session, recorder).revoke_session(
                actor=fixture.actors["global"], session_id=S_SUPER
            )
        assert (await _load(db_session, S_SUPER)).revoked_at is None
        assert recorder.failures()

    async def test_cannot_revoke_all_super_admin_sessions(self, db_session) -> None:
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        with pytest.raises(PermissionDeniedError):
            await _service(db_session, recorder).revoke_all_sessions(
                actor=fixture.actors["super"], user_id=U_SUPER
            )
        assert (await _load(db_session, S_SUPER)).revoked_at is None
        assert recorder.failures()

    async def test_super_admin_session_ends_by_own_logout(self, db_session) -> None:
        """§14：SUPER_ADMIN 只能本人 logout —— 唯一合法的结束路径必须真的可用。"""
        fixture = await _seed(db_session)
        revoked = await SessionService(db_session).logout(
            access_token=fixture.sessions["super"].access_token
        )
        assert revoked is True
        row = await _load(db_session, S_SUPER)
        assert row.revoke_reason is SessionRevokeReason.LOGOUT

    async def test_disable_remains_available_as_recovery_path(self, db_session) -> None:
        """被禁用的超管会话立即失效 —— 说明"不能踢"不等于"无法处置"。"""
        from app.core.errors import AuthenticationError

        fixture = await _seed(db_session)
        user = await db_session.get(AdminUser, U_SUPER)
        assert user is not None
        user.status = UserStatus.DISABLED
        await db_session.flush()

        with pytest.raises(AuthenticationError):
            await SessionService(db_session).authenticate(
                access_token=fixture.sessions["super"].access_token
            )


# ---------------------------------------------------------------------------
# §12 数据范围（Department Admin）
# ---------------------------------------------------------------------------
class TestDataScope:
    """裁判 §12：Department Admin 只能踢管理范围内用户；`10 §10`：范围下推 SQL。"""

    async def test_department_admin_sees_only_own_subtree(self, db_session) -> None:
        fixture = await _seed(db_session)
        page = await _service(db_session).list_sessions(actor=fixture.actors["dept"], page_size=100)
        visible = _ids(page)
        assert S_VALID in visible
        assert S_IN_CHILD in visible  # 子部门在范围内（`00 §1#1`）
        assert S_OUT not in visible  # 其他部门不可见

    async def test_scope_is_applied_in_sql_not_in_memory(self, db_session) -> None:
        """`total` 来自带范围条件的 SQL 计数：若先取全部再内存过滤，总数会偏大。"""
        fixture = await _seed(db_session)
        page = await _service(db_session).list_sessions(actor=fixture.actors["dept"], page_size=100)
        all_rows = (await db_session.execute(select(UserSession.id))).scalars().all()
        assert page.total < len(all_rows)
        assert page.total == len(page.items)  # 范围内总数与返回行数一致

    async def test_department_admin_cannot_list_out_of_scope_user(self, db_session) -> None:
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        with pytest.raises(PermissionDeniedError):
            await _service(db_session, recorder).list_user_sessions(
                actor=fixture.actors["dept"], user_id=U_OUT
            )
        assert recorder.failures()

    async def test_department_admin_cannot_revoke_out_of_scope_session(self, db_session) -> None:
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        with pytest.raises(PermissionDeniedError):
            await _service(db_session, recorder).revoke_session(
                actor=fixture.actors["dept"], session_id=S_OUT
            )
        assert (await _load(db_session, S_OUT)).revoked_at is None
        assert recorder.failures()

    async def test_department_admin_cannot_revoke_all_out_of_scope_user(self, db_session) -> None:
        fixture = await _seed(db_session)
        with pytest.raises(PermissionDeniedError):
            await _service(db_session).revoke_all_sessions(
                actor=fixture.actors["dept"], user_id=U_OUT
            )
        assert (await _load(db_session, S_OUT)).revoked_at is None

    async def test_department_admin_can_revoke_in_scope_session(self, db_session) -> None:
        fixture = await _seed(db_session)
        outcome = await _service(db_session).revoke_session(
            actor=fixture.actors["dept"], session_id=S_IN_CHILD
        )
        assert outcome.revoked is True

    async def test_self_scope_admin_can_only_touch_own_sessions(self, db_session) -> None:
        """SELF 范围：只能管自己的会话（fail-closed，绝不退化为"本部门所有人"）。"""
        fixture = await _seed(db_session)
        service = _service(db_session)

        own = await service.list_sessions(actor=fixture.actors["self"], page_size=100)
        assert _ids(own) == {S_SELF_OWN}

        with pytest.raises(PermissionDeniedError):
            await service.revoke_session(actor=fixture.actors["self"], session_id=S_VALID)

        outcome = await service.revoke_session(actor=fixture.actors["self"], session_id=S_SELF_OWN)
        assert outcome.revoked is True

    async def test_soft_deleted_user_sessions_are_hidden(self, db_session) -> None:
        """逻辑删除 / 不存在的目标按 404 处理，且不参与列表（`02 §5`）。"""
        fixture = await _seed(db_session)
        user = await db_session.get(AdminUser, U_IN_PARENT)
        assert user is not None
        user.deleted_at = utc_now()
        await db_session.flush()

        with pytest.raises(NotFoundError):
            await _service(db_session).list_user_sessions(
                actor=fixture.actors["global"], user_id=U_IN_PARENT
            )
        page = await _service(db_session).list_sessions(
            actor=fixture.actors["global"], page_size=100
        )
        assert S_VALID not in _ids(page)


# ---------------------------------------------------------------------------
# 08 §10 API 权限（后端强制授权）
# ---------------------------------------------------------------------------
class TestApiPermission:
    """`08 §10`：每个受保护 API 必须经过后端 API Permission 校验。"""

    async def test_missing_api_permission_is_denied(self, db_session) -> None:
        fixture = await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, recorder)

        with pytest.raises(PermissionDeniedError):
            await service.list_sessions(actor=fixture.actors["no_perm"])
        with pytest.raises(PermissionDeniedError):
            await service.revoke_session(actor=fixture.actors["no_perm"], session_id=S_NO_PERM_OWN)
        assert len(recorder.failures()) == 2

    async def test_api_permission_and_scope_are_both_required(self, db_session) -> None:
        """两层是"与"关系：有权限但越范围、在范围内但无权限，都必须拒绝。"""
        fixture = await _seed(db_session)
        with pytest.raises(PermissionDeniedError):
            await _service(db_session).revoke_session(
                actor=fixture.actors["dept"], session_id=S_OUT
            )
        with pytest.raises(PermissionDeniedError):
            await _service(db_session).list_user_sessions(
                actor=fixture.actors["no_perm"], user_id=U_IN_PARENT
            )

    async def test_super_admin_bypasses_api_permission(self, db_session) -> None:
        """集中式 bypass（`10 §3`）：SUPER_ADMIN 无需被授予 SESSION_MANAGE。"""
        fixture = await _seed(db_session)
        page = await _service(db_session).list_sessions(
            actor=fixture.actors["super"], page_size=100
        )
        assert page.total > 0


# ---------------------------------------------------------------------------
# 审计与脱敏
# ---------------------------------------------------------------------------
class TestAuditAndMasking:
    """`10 §8` 关键安全操作可审计；`10 §4` 不得记录令牌明文。"""

    async def test_read_is_audited(self, db_session, audit_recorder) -> None:
        fixture = await _seed(db_session)
        await _service(db_session, audit_recorder).list_user_sessions(
            actor=fixture.actors["global"], user_id=U_IN_PARENT
        )
        event = audit_recorder.find("SESSION_READ")
        assert event is not None
        assert event.resource_id == U_IN_PARENT
        assert event.operator_id == U_GLOBAL

    async def test_no_token_material_in_audit(self, db_session, audit_recorder) -> None:
        """审计里既不能有明文令牌，也不能有哈希（哈希同样不是审计内容）。"""
        fixture = await _seed(db_session)
        service = _service(db_session, audit_recorder)
        await service.revoke_session(actor=fixture.actors["global"], session_id=S_VALID)
        await service.revoke_all_sessions(actor=fixture.actors["global"], user_id=U_IN_PARENT)
        await service.list_sessions(actor=fixture.actors["global"])

        blob = repr(
            [
                (event.before_data, event.after_data, event.operator_username)
                for event in audit_recorder.events
            ]
        )
        for seeded in fixture.sessions.values():
            assert seeded.access_token not in blob
            assert seeded.refresh_token not in blob
            assert hash_token(seeded.access_token) not in blob
            assert hash_token(seeded.refresh_token) not in blob

    async def test_paging_validation(self, db_session) -> None:
        fixture = await _seed(db_session)
        service = _service(db_session)
        with pytest.raises(BadRequestError):
            await service.list_sessions(actor=fixture.actors["global"], page_num=0)
        with pytest.raises(BadRequestError):
            await service.list_sessions(actor=fixture.actors["global"], page_size=101)

    async def test_paging_returns_stable_slices(self, db_session) -> None:
        fixture = await _seed(db_session)
        service = _service(db_session)
        first = await service.list_sessions(actor=fixture.actors["global"], page_num=1, page_size=3)
        second = await service.list_sessions(
            actor=fixture.actors["global"], page_num=2, page_size=3
        )
        assert len(first.items) == 3
        assert _ids(first) & _ids(second) == set()
        assert first.total == second.total


# ---------------------------------------------------------------------------
# §15 Refresh Token 不保存明文（以原始 SQL 复核）
# ---------------------------------------------------------------------------
class TestPlaintextNeverPersisted:
    """裁判 §15：Refresh Token 不保存明文。"""

    async def test_raw_columns_hold_only_hashes(self, db_session) -> None:
        from sqlalchemy import text

        fixture = await _seed(db_session)
        rows = (
            await db_session.execute(
                text("select access_token_hash, refresh_token_hash from sessions")
            )
        ).all()
        assert rows
        known = {
            hash_token(seeded.access_token): hash_token(seeded.refresh_token)
            for seeded in fixture.sessions.values()
        }
        for access_hash, refresh_hash in rows:
            assert len(access_hash) == 64
            assert len(refresh_hash) == 64
            assert access_hash in known  # 逆命题：库里存的确实是这些令牌的哈希
            assert known[access_hash] == refresh_hash

        retired = (
            (await db_session.execute(text("select token_hash from session_refresh_token_history")))
            .scalars()
            .all()
        )
        assert all(len(item) == 64 for item in retired)
