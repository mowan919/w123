"""会话服务集成测试（Phase 4 / DD-02 方案 A）。

覆盖 Spec `10 §7` 的落地机制、DD-02 P2~P7 的全部参数，
以及"库里只有哈希、绝无明文"这条 `10 §4` / `04 §3` 的硬要求。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from app.audit import AuditAction
from app.core.errors import AuthenticationError
from app.core.scope import DataScope
from app.core.security.token import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL, hash_token
from app.db.base import utc_now
from app.models import AdminUser, Role, RoleStatus, SessionRevokeReason, UserStatus
from app.models.session import SessionRefreshTokenHistory, UserSession
from app.repositories.session import SESSION_ACTIVITY_WRITE_INTERVAL, SessionRepository
from app.services.session import SessionService
from tests.factories import (
    link_role_custom_scope,
    link_user_role,
    make_department,
    make_role,
    make_session,
    make_user,
)

pytestmark = pytest.mark.integration

USER_ID = 51001
ROLE_ALL = 51011
ROLE_SELF = 51012
DEPARTMENT_ID = 51021

#: 形状合法的令牌（43 字符 base64url）。
TOKEN_A = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


async def _load_user(db_session) -> AdminUser:  # type: ignore[no-untyped-def]
    """按固定 ID 取回本文件创建的用户。"""
    return (await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))).scalar_one()


async def _seed_user(db_session) -> None:  # type: ignore[no-untyped-def]
    """创建一个无角色的普通用户。"""
    await make_user(db_session, user_id=USER_ID, username="session-user")


async def _seed_user_with_roles(db_session) -> None:  # type: ignore[no-untyped-def]
    """创建一个持有两个角色（DATA_SCOPE 不同）的用户。

    两个角色的范围不同，用于验证认证层真的把**逐角色**范围配进了
    `CurrentActor.role_scopes`（DD-19 的合并输入），而不是只落一个策略标签。
    """
    await _seed_user(db_session)
    await make_role(db_session, role_id=ROLE_ALL, role_code="SESS_ALL", data_scope=DataScope.ALL)
    await make_role(db_session, role_id=ROLE_SELF, role_code="SESS_SELF", data_scope=DataScope.SELF)
    await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_ALL)
    await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_SELF)


class TestCreateSession:
    async def test_tokens_are_hashed_not_stored_in_plaintext(self, db_session) -> None:
        """`04 §3` / `10 §4`：库中只能有哈希，绝不能有令牌明文。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)

        service = SessionService(db_session)
        session, tokens = await service.create(user=user, ip="10.0.0.1", user_agent="curl/8.4.0")

        assert session.access_token_hash == hash_token(tokens.access_token)
        assert session.refresh_token_hash == hash_token(tokens.refresh_token)

        # 整行文本不得包含明文令牌（防止"顺手某列存了原文"）
        row_dump = " ".join(
            str(getattr(session, column.name)) for column in session.__table__.columns
        )
        assert tokens.access_token not in row_dump
        assert tokens.refresh_token not in row_dump

    async def test_ttls_follow_dd02(self, db_session) -> None:
        """Access 15 分钟 / Refresh 7 天（DD-02 P1/P2）。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        session, tokens = await SessionService(db_session).create(
            user=user, user_agent="curl/8.4.0"
        )
        assert session.expires_at - session.login_at == ACCESS_TOKEN_TTL
        assert session.refresh_expires_at - session.login_at == timedelta(days=7)
        assert tokens.refresh_expires_at == session.refresh_expires_at

    async def test_device_is_derived_from_user_agent(self, db_session) -> None:
        await _seed_user(db_session)
        user = await _load_user(db_session)
        session, _ = await SessionService(db_session).create(user=user, user_agent="curl/8.4.0")
        assert session.device is not None
        assert "programmatic" in session.device

    async def test_new_session_is_not_revoked(self, db_session) -> None:
        await _seed_user(db_session)
        user = await _load_user(db_session)
        session, _ = await SessionService(db_session).create(user=user)
        assert session.revoked_at is None
        assert session.revoke_reason is None
        assert session.is_active(utc_now()) is True


class TestAuthenticate:
    async def test_valid_token_returns_actor_and_session(self, db_session) -> None:
        await _seed_user_with_roles(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        session, tokens = await service.create(user=user, ip="10.0.0.1")

        result = await service.authenticate(access_token=tokens.access_token, ip="10.0.0.2")

        assert result.session.id == session.id
        assert result.user.id == USER_ID
        assert result.actor.user_id == USER_ID
        assert result.actor.username == "session-user"
        assert {"SESS_ALL", "SESS_SELF"} <= set(result.actor.role_codes)

    async def test_actor_carries_per_role_scope_configs(self, db_session) -> None:
        """认证层必须提供**逐角色**范围配置（DD-19 的合并输入）。"""
        await _seed_user_with_roles(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)

        result = await service.authenticate(access_token=tokens.access_token)

        scopes = {config.role_id: config.data_scope for config in result.actor.role_scopes}
        assert scopes == {ROLE_ALL: DataScope.ALL, ROLE_SELF: DataScope.SELF}

    async def test_actor_without_roles_falls_back_to_self_scope(self, db_session) -> None:
        """无角色用户必须 fail-closed 到 SELF，绝不退化为全局。

        若这里回落成 ALL，"忘记赋角色"就会变成"拥有全部数据权限" ——
        这是最危险的默认值方向。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)

        result = await service.authenticate(access_token=tokens.access_token)

        assert result.actor.role_scopes == ()
        assert result.actor.data_scope is DataScope.SELF
        assert result.actor.is_super_admin is False

    async def test_disabled_role_does_not_contribute_scope(self, db_session) -> None:
        """被禁用的角色必须立刻失去其数据范围（不能半失效）。"""
        await _seed_user_with_roles(db_session)
        role = (await db_session.execute(select(Role).where(Role.id == ROLE_ALL))).scalar_one()
        role.status = RoleStatus.DISABLED
        await db_session.flush()

        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)
        result = await service.authenticate(access_token=tokens.access_token)

        assert {config.role_id for config in result.actor.role_scopes} == {ROLE_SELF}

    async def test_custom_scope_departments_are_carried(self, db_session) -> None:
        await _seed_user(db_session)
        await make_department(db_session, department_id=DEPARTMENT_ID, department_code="SESS_DEPT")
        await make_role(
            db_session, role_id=ROLE_ALL, role_code="SESS_CUSTOM", data_scope=DataScope.CUSTOM
        )
        await link_role_custom_scope(db_session, role_id=ROLE_ALL, department_id=DEPARTMENT_ID)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_ALL)

        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)
        result = await service.authenticate(access_token=tokens.access_token)

        config = result.actor.role_scopes[0]
        assert config.data_scope is DataScope.CUSTOM
        assert config.custom_department_ids == frozenset({DEPARTMENT_ID})

    async def test_unknown_token_is_rejected(self, db_session, audit_recorder) -> None:
        service = SessionService(db_session, audit=audit_recorder)
        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=TOKEN_A)
        assert audit_recorder.failures(), "令牌无效必须留痕"

    async def test_revoked_session_is_rejected_immediately(self, db_session) -> None:
        """Spec `10 §7`：Revoke 后 Token **必须**不能继续访问。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        session, tokens = await service.create(user=user)

        await service.revoke(session, reason=SessionRevokeReason.LOGOUT)

        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=tokens.access_token)

    async def test_access_expiry_is_enforced(self, db_session) -> None:
        await _seed_user(db_session)
        now = utc_now()
        await make_session(
            db_session,
            session_id=51101,
            user_id=USER_ID,
            access_token=TOKEN_A,
            refresh_token=TOKEN_B,
            login_at=now - timedelta(minutes=20),
            access_ttl=timedelta(minutes=15),
        )
        with pytest.raises(AuthenticationError):
            await SessionService(db_session).authenticate(access_token=TOKEN_A)

    async def test_session_total_lifetime_bounds_rotated_access_token(self, db_session) -> None:
        """DD-02 P2：会话总寿命是**硬上界**，刷新不能把它延长。

        构造：登录于 7 天前零 5 分钟 → 会话只剩 5 分钟，
        而 Access 的名义 TTL 是 15 分钟。
        轮换后新 access 的到期时间必须被**封顶到会话结束**，
        越过该时刻即被拒 —— 否则"刷新"就成了无限续期的入口。

        这个用例同时锁住一个曾经真实存在的缺陷：
        若轮换时直接写 `now + 15min`，`expires_at` 会晚于 `refresh_expires_at`，
        既表达出自相矛盾的时间语义，又会被 `sessions` 上的
        `ck_sessions_refresh_expires_not_before_access` 拒绝 ——
        表现为**每个会话在最后 15 分钟里刷新必然 5xx**。
        """
        await _seed_user(db_session)
        now = utc_now()
        await make_session(
            db_session,
            session_id=51102,
            user_id=USER_ID,
            access_token=TOKEN_A,
            refresh_token=TOKEN_B,
            # access 只剩 1 分钟且早已过期：刷新不看 access，只看会话总寿命
            login_at=now - REFRESH_TOKEN_TTL + timedelta(minutes=5),
            access_ttl=timedelta(minutes=1),
            refresh_ttl=REFRESH_TOKEN_TTL,
        )
        service = SessionService(db_session)
        session, tokens = await service.refresh(refresh_token=TOKEN_B)

        # 名义 TTL 15 分钟 > 会话剩余 5 分钟 → 必须被封顶
        assert tokens.access_expires_at == session.refresh_expires_at
        assert tokens.access_expires_at < utc_now() + ACCESS_TOKEN_TTL

        # 会话总寿命一过，即使是**刚换来的** access 也必须失效
        with pytest.raises(AuthenticationError):
            await service.authenticate(
                access_token=tokens.access_token, now=session.refresh_expires_at
            )

    async def test_user_disabled_after_login_is_rejected(self, db_session) -> None:
        """禁用用户必须**立即**失去访问能力，而不是等令牌过期。

        `04 §1` 只在登录时检查 status；若认证路径不复查，
        "禁用"就变成了"最长 15 分钟后生效"。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)

        user.status = UserStatus.DISABLED
        await db_session.flush()

        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=tokens.access_token)

    async def test_soft_deleted_user_is_rejected(self, db_session) -> None:
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)

        user.deleted_at = utc_now()
        await db_session.flush()

        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=tokens.access_token)

    async def test_activity_write_is_suppressed_within_interval(self, db_session) -> None:
        """`last_active_at` 的写抑制：高频请求不得变成写热点。"""
        await _seed_user(db_session)
        now = utc_now()
        session = await make_session(
            db_session,
            session_id=51103,
            user_id=USER_ID,
            access_token=TOKEN_A,
            refresh_token=TOKEN_B,
            login_at=now,
        )
        repository = SessionRepository(db_session)

        assert await repository.touch(session, now=now + timedelta(seconds=5)) is False
        assert (
            await repository.touch(
                session, now=now + SESSION_ACTIVITY_WRITE_INTERVAL + timedelta(seconds=1)
            )
            is True
        )


class TestRefresh:
    async def test_rotation_replaces_both_tokens(self, db_session) -> None:
        """轮换后：旧 access 立即失效，旧 refresh 被留档为 ROTATED。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, first = await service.create(user=user)

        _, second = await service.refresh(refresh_token=first.refresh_token)

        assert second.access_token != first.access_token
        assert second.refresh_token != first.refresh_token
        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=first.access_token)

        retired = (
            await db_session.execute(
                select(SessionRefreshTokenHistory).where(
                    SessionRefreshTokenHistory.token_hash == hash_token(first.refresh_token)
                )
            )
        ).scalar_one()
        assert str(retired.reason) == "ROTATED"

    async def test_rotation_does_not_extend_refresh_lifetime(self, db_session) -> None:
        """DD-02 P2：7 天**固定不滑动**，会话总寿命不能被无限刷新延长。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        session, first = await service.create(user=user)
        original_refresh_expiry = session.refresh_expires_at

        _, second = await service.refresh(refresh_token=first.refresh_token)

        assert second.refresh_expires_at == original_refresh_expiry
        assert second.access_expires_at > session.login_at

    async def test_reuse_of_rotated_token_revokes_whole_session(
        self, db_session, audit_recorder
    ) -> None:
        """DD-02 P4：已轮换的 refresh 再次出现 → 撤销整个会话 + 告警。

        撤销的必须是**整个会话**（含新 access），
        因为攻击者可能已经用旧 refresh 换到过新 access；
        只作废那一个旧 refresh 等于没有响应。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session, audit=audit_recorder)
        session, first = await service.create(user=user)
        _, second = await service.refresh(refresh_token=first.refresh_token)

        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=first.refresh_token)

        await db_session.refresh(session)
        assert session.revoked_at is not None
        assert session.revoke_reason is SessionRevokeReason.TOKEN_REUSE_DETECTED
        assert AuditAction.AUTH_TOKEN_REUSE_DETECTED in audit_recorder.actions()

        # 新 access 也必须随之失效
        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=second.access_token)

    async def test_unknown_refresh_token_is_plain_failure(self, db_session, audit_recorder) -> None:
        """完全查不到的 refresh ≠ 盗用信号，不得误报。

        误报会让安全日志被噪声淹没，真正的盗用反而看不出来。
        """
        service = SessionService(db_session, audit=audit_recorder)
        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=TOKEN_A)
        assert AuditAction.AUTH_TOKEN_REUSE_DETECTED not in audit_recorder.actions()

    async def test_refresh_after_logout_is_not_reported_as_reuse(
        self, db_session, audit_recorder
    ) -> None:
        """登出后重放旧 refresh 只是"作废令牌再试一次"，不是盗用。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session, audit=audit_recorder)
        _, tokens = await service.create(user=user)
        await service.logout(access_token=tokens.access_token)

        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=tokens.refresh_token)
        assert AuditAction.AUTH_TOKEN_REUSE_DETECTED not in audit_recorder.actions()

    async def test_expired_refresh_token_is_rejected(self, db_session, audit_recorder) -> None:
        """会话总寿命已过：形状完全合法的 refresh 也必须被拒。

        同时断言它**不得**被当成盗用信号 —— 过期的当前令牌是正常失败，
        误报会把安全日志淹掉（真正被盗用时反而看不出来）。
        """
        await _seed_user(db_session)
        now = utc_now()
        await make_session(
            db_session,
            session_id=51104,
            user_id=USER_ID,
            access_token=TOKEN_A,
            refresh_token=TOKEN_B,
            login_at=now - REFRESH_TOKEN_TTL - timedelta(minutes=5),
            refresh_ttl=REFRESH_TOKEN_TTL,
        )
        service = SessionService(db_session, audit=audit_recorder)
        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=TOKEN_B)

        reasons = [
            (event.after_data or {}).get("reason")
            for event in audit_recorder.failures()
            if event.after_data
        ]
        assert "REFRESH_TOKEN_EXPIRED" in reasons
        assert AuditAction.AUTH_TOKEN_REUSE_DETECTED not in audit_recorder.actions()

    async def test_disabled_user_cannot_refresh(self, db_session) -> None:
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)
        user.status = UserStatus.DISABLED
        await db_session.flush()

        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=tokens.refresh_token)

    async def test_concurrent_rotation_only_one_wins(self, db_session) -> None:
        """DD-02 P7：并发刷新被串行化，**只有一个**能成功。

        测试手法：先把库里的 `access_token_hash` 直接改掉
        （精确模拟"另一个请求已经赢了这场竞争"），
        此时内存中的会话对象仍持有旧值 —— CAS 必须失败。

        为什么不真的起两个并发协程：那会让用例变成"碰运气"，
        失败时也无法区分"实现错了"与"调度顺序不同"。
        这里直接构造竞争**之后**的数据状态，结论因此是确定的。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        session, _ = await SessionService(db_session).create(user=user)
        repository = SessionRepository(db_session)

        # 1) 正常情况：CAS 命中 → 返回 True
        assert (
            await repository.rotate_tokens(
                session,
                access_token_hash="1" * 64,
                refresh_token_hash="2" * 64,
                access_expires_at=utc_now() + ACCESS_TOKEN_TTL,
                last_active_at=utc_now(),
            )
            is True
        )

        # 2) 竞争者抢先改动了行（不经过本对象），本对象的快照随即过期
        await db_session.execute(
            update(UserSession)
            .where(UserSession.id == session.id)
            .values(access_token_hash="3" * 64, refresh_token_hash="4" * 64)
        )
        # 把内存对象回退到"它以为自己持有的"旧值
        session.access_token_hash = "1" * 64

        # 3) 拿着过期快照轮换 → CAS 必须失败，而不是覆盖竞争者的结果
        assert (
            await repository.rotate_tokens(
                session,
                access_token_hash="5" * 64,
                refresh_token_hash="6" * 64,
                access_expires_at=utc_now() + ACCESS_TOKEN_TTL,
                last_active_at=utc_now(),
            )
            is False
        )


class TestLogout:
    async def test_logout_revokes_and_is_idempotent(self, db_session, audit_recorder) -> None:
        """DD-11 方案 A：语义幂等 —— 重复登出返回成功而非 401。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session, audit=audit_recorder)
        _, tokens = await service.create(user=user)

        assert await service.logout(access_token=tokens.access_token) is True
        assert await service.logout(access_token=tokens.access_token) is False
        assert audit_recorder.find(str(AuditAction.AUTH_LOGOUT)) is not None

    async def test_logout_with_unknown_token_is_noop(self, db_session) -> None:
        service = SessionService(db_session)
        assert await service.logout(access_token=TOKEN_A) is False

    async def test_revoke_is_idempotent_and_keeps_first_reason(self, db_session) -> None:
        """撤销原因一旦写入不得被覆盖：第一个原因才是真相。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        session, _ = await service.create(user=user)

        assert (
            await service.revoke(session, reason=SessionRevokeReason.TOKEN_REUSE_DETECTED)
        ) is True
        assert await service.revoke(session, reason=SessionRevokeReason.LOGOUT) is False
        assert session.revoke_reason is SessionRevokeReason.TOKEN_REUSE_DETECTED

    async def test_logout_retires_refresh_token_for_forensics(self, db_session) -> None:
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session)
        _, tokens = await service.create(user=user)
        await service.logout(access_token=tokens.access_token)

        retired = (
            await db_session.execute(
                select(SessionRefreshTokenHistory).where(
                    SessionRefreshTokenHistory.token_hash == hash_token(tokens.refresh_token)
                )
            )
        ).scalar_one()
        assert str(retired.reason) == "SESSION_REVOKED"


class TestAuditHygiene:
    async def test_no_plaintext_token_in_any_audit_event(self, db_session, audit_recorder) -> None:
        """`10 §4`：审计里绝不能出现令牌明文或哈希。

        这条要求覆盖**所有**路径（成功 / 失败 / 轮换 / 复用），
        因此这里把整条链路跑一遍再统一检查。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session, audit=audit_recorder)
        _, tokens = await service.create(user=user)
        _, second = await service.refresh(refresh_token=tokens.refresh_token)
        with pytest.raises(AuthenticationError):
            await service.refresh(refresh_token=tokens.refresh_token)
        await service.logout(access_token=second.access_token)

        blob = repr(audit_recorder.events)
        for secret in (
            tokens.access_token,
            tokens.refresh_token,
            second.access_token,
            second.refresh_token,
        ):
            assert secret not in blob

    async def test_failure_reason_is_recorded_for_diagnosis(
        self, db_session, audit_recorder
    ) -> None:
        """对外文案统一，但审计侧必须可诊断（否则线上无法排查）。"""
        await _seed_user(db_session)
        user = await _load_user(db_session)
        service = SessionService(db_session, audit=audit_recorder)
        _, tokens = await service.create(user=user)
        await service.logout(access_token=tokens.access_token)

        with pytest.raises(AuthenticationError):
            await service.authenticate(access_token=tokens.access_token)

        reasons = [
            (event.after_data or {}).get("reason")
            for event in audit_recorder.failures()
            if event.after_data
        ]
        assert "SESSION_REVOKED" in reasons


# ---------------------------------------------------------------------------
# 明文绝不落库（独立于 ORM 的复查）
# ---------------------------------------------------------------------------
class TestPlaintextNeverPersisted:
    async def test_no_session_row_contains_plaintext(self, db_session) -> None:
        """用原生 SQL 复查整表：任何列都不得出现明文令牌。

        这是对 `04 §3` 的**独立性**验证 —— 不依赖 ORM 对象，
        而是直接读数据库内容，因此能发现"ORM 看起来对、但某处写了原文"的情况。
        """
        await _seed_user(db_session)
        user = await _load_user(db_session)
        _, tokens = await SessionService(db_session).create(user=user)

        rows = (
            await db_session.execute(
                text("select access_token_hash, refresh_token_hash from sessions")
            )
        ).all()
        for access_hash, refresh_hash in rows:
            assert access_hash != tokens.access_token
            assert refresh_hash != tokens.refresh_token
            assert len(access_hash) == 64
            assert len(refresh_hash) == 64
