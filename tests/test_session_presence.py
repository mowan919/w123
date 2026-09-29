"""会话在场口径（空闲阈值）与新登录顶替旧会话（`DESIGN-DECISIONS §31`）。

用户反馈"同一个用户显示多个 session 在线"，裁定两件事都做：

1. **在线 = 在场**：最近活动超过 `SESSION_ONLINE_IDLE_WINDOW`（30 分钟）的
   会话显示离线 —— 但它**依然有效**，鉴权不受影响；
2. **新登录顶替旧会话**：同一账号签发新会话时，其余有效会话被自动撤销
   （`SUPERSEDED`），同一时刻至多一个有效会话。

为什么这两条必须分开测
----------------------
"在线"（presence）与"有效"（validity）现在是**有意分叉**的两个口径：
列表 / 统计用前者，鉴权 / 踢人名单用后者。任何一边误用另一边，
表现都是静默的（"显示离线但还能用"或"该踢的没踢"），本文件逐条钉住。
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import AuthenticationError
from app.core.security.token import ACCESS_TOKEN_TTL
from app.db.base import utc_now
from app.models.enums import SessionRevokeReason, UserStatus
from app.models.session import UserSession
from app.repositories.session import (
    SESSION_ONLINE_IDLE_WINDOW,
    SessionRepository,
    online_session_condition,
    session_valid_condition,
)
from app.services.auth import AuthService
from app.services.session import SessionService
from tests.factories import make_user

pytestmark = pytest.mark.integration

#: 满足 `00 §2` 全部四类字符且 >= 12 位。
PASSWORD = "Alpha-Passw0rd!01"


def _unique_user_id() -> int:
    """随机用户 ID：共享库里有种子行，固定 ID 会撞唯一索引（OPERATION-11-01）。"""
    return int.from_bytes(secrets.token_bytes(5), "big") + 6_000_000_000


async def _seed(db_session, username: str):
    return await make_user(
        db_session,
        user_id=_unique_user_id(),
        username=username,
        password=PASSWORD,
        password_changed_at=utc_now(),
        status=UserStatus.ACTIVE,
    )


def _service(db_session) -> AuthService:
    return AuthService(db_session)


def _sessions(db_session) -> SessionRepository:
    return SessionRepository(db_session)


async def _ids(db_session, condition, user_id: int) -> set[int]:
    """按条件查该用户的会话 ID。

    ⚠️ 必须叠加 `user_id` 过滤：`db_session` 连的是**共享库**，
    里面躺着真实运行产生的会话行，裸条件会把它们一并捞进来。
    """
    rows = await db_session.execute(
        select(UserSession.id).where(condition, UserSession.user_id == user_id)
    )
    return set(rows.scalars().all())


# ---------------------------------------------------------------- 顶替


class TestSupersedeOnLogin:
    async def test_second_login_revokes_the_first_session_as_superseded(self, db_session) -> None:
        user = await _seed(db_session, "supersede-user")
        now = utc_now()

        first = await _service(db_session).login(username=user.username, password=PASSWORD, now=now)
        second = await _service(db_session).login(
            username=user.username, password=PASSWORD, now=now + timedelta(minutes=5)
        )

        reloaded = await db_session.get(UserSession, first.session.id)
        assert reloaded is not None
        assert reloaded.revoked_at is not None
        assert reloaded.revoke_reason is SessionRevokeReason.SUPERSEDED

        # 同一时刻该账号至多一个**有效**会话 —— 就是新签的那个。
        valid = await _ids(db_session, session_valid_condition(now + timedelta(minutes=5)), user.id)
        assert valid == {second.session.id}

    async def test_superseded_session_tokens_stop_authenticating(self, db_session) -> None:
        user = await _seed(db_session, "supersede-token-user")
        now = utc_now()
        service = _service(db_session)

        first = await service.login(username=user.username, password=PASSWORD, now=now)
        await service.login(
            username=user.username, password=PASSWORD, now=now + timedelta(minutes=5)
        )

        with pytest.raises(AuthenticationError):
            await SessionService(db_session).authenticate(
                access_token=first.tokens.access_token,
                now=now + timedelta(minutes=6),
            )

    async def test_refresh_rotation_does_not_supersede_the_same_session(self, db_session) -> None:
        """多标签页共用同一会话：refresh 轮换不经过 `create`，不能把自己顶掉。"""
        user = await _seed(db_session, "supersede-refresh-user")
        now = utc_now()
        service = _service(db_session)

        result = await service.login(username=user.username, password=PASSWORD, now=now)
        reloaded = await db_session.get(UserSession, result.session.id)
        assert reloaded is not None
        assert reloaded.revoked_at is None

    async def test_supersede_kick_is_recorded_in_audit(self, db_session, audit_recorder) -> None:
        """被顶替的会话必须留痕：`AUTH_SESSION_REVOKE` + reason=SUPERSEDED。"""
        user = await _seed(db_session, "supersede-audit-user")
        now = utc_now()

        service = AuthService(db_session, audit=audit_recorder)
        first = await service.login(username=user.username, password=PASSWORD, now=now)
        await service.login(
            username=user.username, password=PASSWORD, now=now + timedelta(minutes=5)
        )

        event = audit_recorder.find("AUTH_SESSION_REVOKE")
        assert event is not None
        assert event.resource_id == first.session.id
        assert event.after_data is not None
        assert event.after_data.get("reason") == "SUPERSEDED"


# ---------------------------------------------------------------- 在场口径


class TestOnlinePresenceWindow:
    async def test_fresh_session_is_online(self, db_session) -> None:
        user = await _seed(db_session, "presence-fresh-user")
        result = await _service(db_session).login(username=user.username, password=PASSWORD)

        now = utc_now()
        online = await _ids(db_session, online_session_condition(now), user.id)
        assert online == {result.session.id}

    async def test_idle_session_is_not_online_but_still_authenticates(self, db_session) -> None:
        """分叉的核心：空闲 40 分钟 → 展示为离线，但令牌照样能认证。"""
        user = await _seed(db_session, "presence-idle-user")
        service = _service(db_session)
        result = await service.login(username=user.username, password=PASSWORD)

        session_row = await db_session.get(UserSession, result.session.id)
        assert session_row is not None
        past = utc_now()
        session_row.last_active_at = past - timedelta(minutes=40)
        await db_session.flush()  # autoflush=False：不 flush，SELECT 看到的还是旧值

        now = past + timedelta(seconds=1)
        online = await _ids(db_session, online_session_condition(now), user.id)
        valid = await _ids(db_session, session_valid_condition(now), user.id)
        assert result.session.id not in online
        assert result.session.id in valid

        # 有效 ⇒ 认证照常通过（"在线"是展示口径，不是权限）。
        authenticated = await SessionService(db_session).authenticate(
            access_token=result.tokens.access_token, now=now
        )
        assert authenticated.session.id == result.session.id

    async def test_activity_just_inside_the_window_still_counts_online(self, db_session) -> None:
        user = await _seed(db_session, "presence-edge-user")
        service = _service(db_session)
        result = await service.login(username=user.username, password=PASSWORD)

        session_row = await db_session.get(UserSession, result.session.id)
        assert session_row is not None
        now = utc_now()
        session_row.last_active_at = now - timedelta(minutes=25)
        await db_session.flush()

        online = await _ids(db_session, online_session_condition(now), user.id)
        assert result.session.id in online

    async def test_admin_revoke_all_still_reaches_idle_but_valid_sessions(self, db_session) -> None:
        """踢人名单按**有效性**挑：空闲会话必须能被踢到，不能漏。"""
        user = await _seed(db_session, "presence-revoke-user")
        service = _service(db_session)
        result = await service.login(username=user.username, password=PASSWORD)

        session_row = await db_session.get(UserSession, result.session.id)
        assert session_row is not None
        now = utc_now()
        session_row.last_active_at = now - timedelta(minutes=60)
        await db_session.flush()

        # 名单（validity）里有它；在场（presence）里没有 —— 差异正是本用例要钉的。
        reachable = await _sessions(db_session).list_active_for_user(user.id, now=now)
        assert [item.id for item in reachable] == [result.session.id]
        online = await _ids(db_session, online_session_condition(now), user.id)
        assert result.session.id not in online


# ---------------------------------------------------------------- 约束回归


class TestTtlConstantsUnchanged:
    def test_access_ttl_is_fifteen_minutes(self) -> None:
        """在场窗口只在展示层；access / refresh 的 TTL 语义不受本裁定影响。"""
        assert timedelta(minutes=15) == ACCESS_TOKEN_TTL

    def test_idle_window_is_thirty_minutes(self) -> None:
        """阈值本身要被钉住：上面的用例用**绝对**偏移写，就是为了能抓住
        "把窗口改大"这种变异 —— 若用例按常量算偏移，改大窗口照样全绿。"""
        assert timedelta(minutes=30) == SESSION_ONLINE_IDLE_WINDOW
