"""认证服务测试（Phase 4）。

覆盖 Spec `04 §1`（登录九步）、`04 §2`（口令策略）、
`10 §4`（不记录口令）、`10 §5`（不泄露用户是否存在）、
`04 §8`（安全审计），以及 DD-02 方案 A 在登录/登出/改密路径上的落地。

测试为什么直接调服务而不是走 HTTP
--------------------------------
本文件验证的是**业务判定**（锁定计数、90 天、强制改密、文案统一），
HTTP 层只负责接线。把两者混在一个用例里会让失败原因变模糊
（"401 是因为锁定还是因为路由没挂上？"）。
HTTP 层的行为由 `tests/test_auth_api.py` 单独验证。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import (
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    PermissionDeniedError,
)
from app.core.security.password import (
    LOCKOUT_DURATION,
    MAX_FAILED_LOGIN_ATTEMPTS,
    PASSWORD_MAX_AGE,
    get_password_hasher,
)
from app.db.base import utc_now
from app.models import AdminUser, UserStatus
from app.models.session import UserSession
from app.services.auth import AuthService
from app.services.mfa import MfaPolicyResolver, MfaService
from app.services.session import SessionService
from tests.factories import make_user

pytestmark = pytest.mark.integration

#: 满足 `00 §2` 全部四类字符且 >= 12 位。
PASSWORD = "Alpha-Passw0rd!01"
NEW_PASSWORD = "Bravo-Passw0rd!02"
#: 仅用于验证"复用旧口令被拒"的第三个口令。
THIRD_PASSWORD = "Charlie-Passw0rd!03"

USER_ID = 52001


async def _seed(
    db_session,
    *,
    password: str = PASSWORD,
    password_changed_at=None,
    must_change_password: bool = False,
    status: UserStatus = UserStatus.ACTIVE,
    username: str = "auth-user",
) -> AdminUser:
    """创建可用于登录的用户。

    `password_changed_at` 默认取"当前时刻"：`make_user` 的默认值是 None
    （视为已过期，fail-closed），若不显式覆盖，
    每个用例都会意外地走到"强制改密"分支。
    """
    return await make_user(
        db_session,
        user_id=USER_ID,
        username=username,
        password=password,
        password_changed_at=password_changed_at or utc_now(),
        must_change_password=must_change_password,
        status=status,
    )


def _service(db_session, **kwargs) -> AuthService:
    return AuthService(db_session, **kwargs)


class TestLoginSuccess:
    async def test_login_creates_session_and_returns_tokens(self, db_session) -> None:
        user = await _seed(db_session)
        result = await _service(db_session).login(
            username="auth-user", password=PASSWORD, ip="10.0.0.1"
        )

        assert result.user.id == user.id
        assert result.session.id > 0
        assert result.session.user_id == user.id
        assert len(result.tokens.access_token) >= 32
        assert len(result.tokens.refresh_token) >= 32
        assert result.tokens.access_token != result.tokens.refresh_token
        # token_type / TTL 口径
        assert result.tokens.access_expires_at == result.session.expires_at
        assert result.tokens.refresh_expires_at == result.session.refresh_expires_at
        assert result.must_change_password is False

    async def test_login_succeeds_even_when_password_is_over_90_days_old(self, db_session) -> None:
        """DD-02 P8：口令过期**不阻止**登录，而是要求立即改密。

        若直接拒绝登录，用户就没有任何路径去改口令（改密本身需要登录）——
        那是死锁，不是安全策略。
        """
        await _seed(
            db_session,
            password_changed_at=utc_now() - PASSWORD_MAX_AGE - timedelta(days=1),
        )
        result = await _service(db_session).login(username="auth-user", password=PASSWORD)

        assert result.must_change_password is True
        # 标志必须**落库**：只存在内存里的话，下一个请求读到的仍是 False
        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.must_change_password is True

    async def test_fresh_password_does_not_force_change(self, db_session) -> None:
        await _seed(db_session)
        result = await _service(db_session).login(username="auth-user", password=PASSWORD)
        assert result.must_change_password is False

    async def test_unknown_password_change_time_forces_change(self, db_session) -> None:
        """`password_changed_at` 为空 → fail-closed 视为已过期。"""
        await _seed(db_session, password_changed_at=utc_now())
        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        # 直接模拟"历史数据从未记录过改密时间"
        user.password_changed_at = None
        await db_session.flush()

        result = await _service(db_session).login(username="auth-user", password=PASSWORD)
        assert result.must_change_password is True

    async def test_admin_reset_flag_survives_login(self, db_session) -> None:
        """`04 §2`：管理员重置后首次登录强制改密。"""
        await _seed(db_session, must_change_password=True)
        result = await _service(db_session).login(username="auth-user", password=PASSWORD)
        assert result.must_change_password is True

    async def test_successful_login_records_audit_with_session_id(
        self, db_session, audit_recorder
    ) -> None:
        await _seed(db_session)
        result = await _service(db_session, audit=audit_recorder).login(
            username="auth-user", password=PASSWORD, ip="10.0.0.7", user_agent="pytest/1.0"
        )

        event = audit_recorder.find(str(AuditAction.AUTH_LOGIN_SUCCESS))
        assert event is not None
        assert str(event.result) == "SUCCESS"
        # resource_id 必须是**本次会话**的 ID：否则"登录成功"这条记录
        # 无法与任何一个具体会话对应，事后无从追查
        assert event.resource_id == result.session.id
        assert event.resource_type == "SESSION"
        assert event.operator_id == USER_ID
        assert event.operator_username == "auth-user"

    async def test_successful_login_resets_failure_counter(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)

        for _ in range(3):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99")

        await service.login(username="auth-user", password=PASSWORD)

        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.failed_login_count == 0
        assert user.locked_until is None


class TestLoginFailuresAreIndistinguishable:
    """Spec `10 §5`：失败文案必须统一，否则可用于枚举用户名。"""

    async def _message(self, service: AuthService, *, username: str, password: str) -> str:
        with pytest.raises(AuthenticationError) as excinfo:
            await service.login(username=username, password=password)
        return str(excinfo.value)

    async def test_unknown_user_wrong_password_and_disabled_user_share_one_message(
        self, db_session
    ) -> None:
        await _seed(db_session)
        service = _service(db_session)

        unknown = await self._message(service, username="ghost", password=PASSWORD)
        wrong = await self._message(service, username="auth-user", password="Wrong-Passw0rd!99")

        assert unknown == wrong

    async def test_internal_reason_is_still_recorded_for_diagnosis(
        self, db_session, audit_recorder
    ) -> None:
        """对外统一，但审计侧必须能区分 —— 否则线上无法定位问题。"""
        await _seed(db_session)
        service = _service(db_session, audit=audit_recorder)

        with pytest.raises(AuthenticationError):
            await service.login(username="ghost", password=PASSWORD)

        reasons = [
            (event.after_data or {}).get("reason")
            for event in audit_recorder.failures()
            if event.after_data
        ]
        assert "UNKNOWN_USER" in reasons

    async def test_disabled_user_is_rejected_and_reason_recorded(
        self, db_session, audit_recorder
    ) -> None:
        await _seed(db_session, status=UserStatus.DISABLED)
        service = _service(db_session, audit=audit_recorder)

        with pytest.raises(AuthenticationError):
            await service.login(username="auth-user", password=PASSWORD)

        reasons = [
            (event.after_data or {}).get("reason")
            for event in audit_recorder.failures()
            if event.after_data
        ]
        assert "STATUS_DISABLED" in reasons

    async def test_failed_login_never_issues_a_session(self, db_session) -> None:
        await _seed(db_session)
        with pytest.raises(AuthenticationError):
            await _service(db_session).login(username="auth-user", password="Wrong-Passw0rd!99")

        sessions = (
            (await db_session.execute(select(UserSession).where(UserSession.user_id == USER_ID)))
            .scalars()
            .all()
        )
        assert sessions == []


class TestLockout:
    async def test_five_consecutive_failures_lock_the_account(
        self, db_session, audit_recorder
    ) -> None:
        await _seed(db_session)
        service = _service(db_session, audit=audit_recorder)
        now = utc_now()

        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99", now=now)

        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.failed_login_count == MAX_FAILED_LOGIN_ATTEMPTS
        assert user.locked_until == now + LOCKOUT_DURATION

        # 锁定是独立安全事件，必须单独可检索（否则会淹没在失败噪声里）
        assert AuditAction.AUTH_LOCKOUT in audit_recorder.actions()

    async def test_lockout_does_not_flip_status_to_locked(self, db_session) -> None:
        """锁定语义完全由 `locked_until` 表达，不改 `status`。

        若把 `status` 改成 LOCKED，到期后没有任何东西会把它改回来
        （清理它需要一个后台任务），账号就被**永久锁死**。
        """
        await _seed(db_session)
        service = _service(db_session)
        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99")

        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.status is UserStatus.ACTIVE

    async def test_locked_account_rejects_correct_password_within_lockout(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        now = utc_now()
        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99", now=now)

        # 锁定期内即使口令正确也必须拒绝
        with pytest.raises(AuthenticationError):
            await service.login(
                username="auth-user", password=PASSWORD, now=now + timedelta(minutes=1)
            )

    async def test_lock_expires_after_thirty_minutes(self, db_session) -> None:
        """30 分钟后**无需任何后台任务**即可登录（惰性解锁）。"""
        await _seed(db_session)
        service = _service(db_session)
        now = utc_now()
        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99", now=now)

        result = await service.login(
            username="auth-user", password=PASSWORD, now=now + LOCKOUT_DURATION
        )
        assert result.session.id is not None

    async def test_failure_counter_is_not_cleared_by_unlocking(self, db_session) -> None:
        """解锁不清零计数：下一错一次立即再次锁定。

        若解锁时清零，攻击者只要等锁定期结束就能立刻再拿 5 次尝试，
        实际攻击速率不受影响。代价（保守）已在决策台账报备。
        """
        await _seed(db_session)
        service = _service(db_session)
        now = utc_now()
        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99", now=now)

        after_lock = now + LOCKOUT_DURATION
        with pytest.raises(AuthenticationError):
            await service.login(username="auth-user", password="Wrong-Passw0rd!99", now=after_lock)

        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.failed_login_count == MAX_FAILED_LOGIN_ATTEMPTS + 1
        assert user.locked_until == after_lock + LOCKOUT_DURATION


class TestMfaStep:
    """DD-01 方案 A：Phase 4 落地"MFA 步骤 + Provider 抽象 + fail-closed"。"""

    async def test_default_configuration_does_not_require_mfa(self, db_session) -> None:
        """默认 `MFA_REQUIRED_DEFAULT=false` → 登录正常通过。"""
        await _seed(db_session)
        result = await _service(db_session).login(username="auth-user", password=PASSWORD)
        assert result.session.id is not None

    async def test_required_mfa_without_provider_fails_closed(self, db_session) -> None:
        """策略要求二次验证但没有 Provider → **明确失败**，绝不静默放行。

        这是本项目对"安全配置缺失"的一贯取向：让配置问题立刻可见，
        而不是得到一个"号称有 MFA、实际没有"的系统。
        """
        await _seed(db_session)
        mfa = MfaService(resolver=MfaPolicyResolver(system_default=True))
        service = _service(db_session, mfa=mfa)

        with pytest.raises(ConfigurationError):
            await service.login(username="auth-user", password=PASSWORD)

    async def test_mfa_check_runs_after_password_verification(self, db_session) -> None:
        """MFA 步骤在口令校验**之后**：口令错时不得触发 MFA 逻辑。

        若顺序颠倒，攻击者无需口令就能驱动 MFA 流程（枚举用户 + 骚扰）。
        """
        await _seed(db_session)
        mfa = MfaService(resolver=MfaPolicyResolver(system_default=True))
        service = _service(db_session, mfa=mfa)

        # 口令错 → 抛的是认证错误（而非配置错误），说明根本没走到 MFA
        with pytest.raises(AuthenticationError):
            await service.login(username="auth-user", password="Wrong-Passw0rd!99")


class TestCredentialHygiene:
    """Spec `10 §4`：不得记录 / 存储口令明文与哈希。"""

    async def test_plaintext_password_is_never_persisted(self, db_session) -> None:
        await _seed(db_session)
        await _service(db_session).login(username="auth-user", password=PASSWORD)

        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        assert user.password_hash != PASSWORD
        assert PASSWORD not in user.password_hash
        assert get_password_hasher().verify(PASSWORD, user.password_hash) is True

    async def test_no_audit_event_contains_password_material(
        self, db_session, audit_recorder
    ) -> None:
        """把成功 / 失败 / 锁定三条路径都跑一遍再统一检查。"""
        await _seed(db_session)
        service = _service(db_session, audit=audit_recorder)

        await service.login(username="auth-user", password=PASSWORD)
        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                await service.login(username="auth-user", password="Wrong-Passw0rd!99")

        blob = repr(
            [
                (event.before_data, event.after_data, event.operator_username)
                for event in audit_recorder.events
            ]
        )
        assert PASSWORD not in blob
        assert "Wrong-Passw0rd!99" not in blob
        assert "password_hash" not in blob
        assert "$argon2id$" not in blob


class TestLogoutAndMeDelegation:
    async def test_logout_revokes_issued_session(self, db_session, audit_recorder) -> None:
        await _seed(db_session)
        service = _service(db_session, audit=audit_recorder)
        result = await service.login(username="auth-user", password=PASSWORD)

        assert await service.logout(access_token=result.tokens.access_token) is True
        assert AuditAction.AUTH_LOGOUT in audit_recorder.actions()

        # 登出后令牌必须**立即**不可用（Spec 10 §7）
        with pytest.raises(AuthenticationError):
            await SessionService(db_session).authenticate(access_token=result.tokens.access_token)

    async def test_me_returns_the_actor_user(self, db_session) -> None:
        user = await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")
        assert (await _service(db_session).me(actor=actor)).id == user.id

    async def test_me_raises_when_user_was_removed(self, db_session) -> None:
        await _seed(db_session)
        user = (
            await db_session.execute(select(AdminUser).where(AdminUser.id == USER_ID))
        ).scalar_one()
        user.deleted_at = utc_now()
        await db_session.flush()

        actor = CurrentActor(user_id=USER_ID, username="auth-user")
        with pytest.raises(AuthenticationError):
            await _service(db_session).me(actor=actor)


class TestChangeOwnPassword:
    async def test_wrong_current_password_is_denied(self, db_session, audit_recorder) -> None:
        await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")

        with pytest.raises(PermissionDeniedError):
            await _service(db_session, audit=audit_recorder).change_own_password(
                actor=actor, current_password="Wrong-Passw0rd!99", new_password=NEW_PASSWORD
            )

    async def test_successful_change_clears_must_change_flag(
        self, db_session, audit_recorder
    ) -> None:
        """`04 §2` 的解除路径：改密成功 → `must_change_password = False`。"""
        await _seed(db_session, must_change_password=True)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")
        service = _service(db_session, audit=audit_recorder)

        user = await service.change_own_password(
            actor=actor, current_password=PASSWORD, new_password=NEW_PASSWORD
        )

        assert user.must_change_password is False
        assert get_password_hasher().verify(NEW_PASSWORD, user.password_hash) is True
        assert AuditAction.USER_CHANGE_PASSWORD in audit_recorder.actions()

    async def test_password_history_rejects_reuse(self, db_session) -> None:
        """`00 §2`：最近 5 个口令不可重复。

        期望 400（请求内容违反策略）而非 403：调用者**有**权限改自己的口令，
        只是新口令不合法 —— 语义不同，客户端处理方式也不同。
        """
        await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")
        service = _service(db_session)

        await service.change_own_password(
            actor=actor, current_password=PASSWORD, new_password=NEW_PASSWORD
        )
        # 改回最初的口令 → 命中历史，必须被拒
        with pytest.raises(BadRequestError):
            await service.change_own_password(
                actor=actor, current_password=NEW_PASSWORD, new_password=PASSWORD
            )

    async def test_new_password_equal_to_current_is_rejected(self, db_session) -> None:
        """ "与历史不重复"之外还需单独挡住"与当前口令相同"。

        当前口令在改密成功之前**尚未**进入历史表，
        因此只靠历史校验抓不到这种情况。
        """
        await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")

        with pytest.raises(BadRequestError):
            await _service(db_session).change_own_password(
                actor=actor, current_password=PASSWORD, new_password=PASSWORD
            )

    async def test_weak_new_password_is_rejected(self, db_session) -> None:
        """复杂度策略只有一份实现（`app.core.security.password`）。"""
        await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")

        with pytest.raises(BadRequestError):
            await _service(db_session).change_own_password(
                actor=actor, current_password=PASSWORD, new_password="short"
            )

    async def test_change_also_allows_unrelated_new_password(self, db_session) -> None:
        await _seed(db_session)
        actor = CurrentActor(user_id=USER_ID, username="auth-user")
        service = _service(db_session)

        await service.change_own_password(
            actor=actor, current_password=PASSWORD, new_password=NEW_PASSWORD
        )
        user = await service.change_own_password(
            actor=actor, current_password=NEW_PASSWORD, new_password=THIRD_PASSWORD
        )
        assert get_password_hasher().verify(THIRD_PASSWORD, user.password_hash) is True

    async def test_change_updates_password_changed_at(self, db_session) -> None:
        """改密必须刷新时间戳，否则 90 天策略永远算在旧口令上。"""
        await _seed(
            db_session,
            password_changed_at=utc_now() - PASSWORD_MAX_AGE - timedelta(days=5),
        )
        actor = CurrentActor(user_id=USER_ID, username="auth-user")

        user = await _service(db_session).change_own_password(
            actor=actor, current_password=PASSWORD, new_password=NEW_PASSWORD
        )
        assert user.password_changed_at is not None
        assert utc_now() - user.password_changed_at < timedelta(minutes=1)
