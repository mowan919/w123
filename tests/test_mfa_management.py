"""MFA 管理服务测试（`PHASES.md` Phase 5 / 验收裁判 `005-mfa.md`）。

裁判条目与本文件的对应关系
--------------------------
| 裁判条目 | 用例 |
|---|---|
| Provider 使用可扩展接口（1） | `TestProviderAbstraction` |
| DISABLED / SETUP / ENABLED 生命周期（2） | `TestLifecycle` |
| Secret 加密保存（3） | `TestSecretEncryption` |
| Secret 不进入日志（4） | `TestSecretNeverLeavesAudit` |
| 按角色配置 MFA（5） | `TestRolePolicy` |
| 按用户配置 MFA（6） | `TestUserPolicy` |
| 用户级优先于角色级（7） | `TestPolicyPriority` |
| 角色级优先于系统默认（8） | `TestPolicyPriority` |
| 登录流程正确触发 MFA（9） | `TestChallengeLifecycle` |
| enable/disable 有安全日志（10） | `TestSecurityAudit` |
| MFA failure 有安全日志（11） | `TestSecurityAudit` |
| 恢复流程不会泄漏 Secret（12） | `TestNoSecretOnReadSurfaces` |
| 不得擅自定义 V1 Provider（13） | `TestNoConcreteProviderInProduct` |

测试专用 Provider
----------------
`_TestProvider` **只存在于 `tests/`**，绝不进 `app/`。
`00 §4` / `16 §1` / `PHASES.md Phase 5` 一致禁止实现者把某个具体
Provider 宣布为需求事实；本文件用"可替换的测试替身"来验证抽象是否真的可用，
而不是拿它冒充产品需求。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text

from app.auth.actor import CurrentActor
from app.core.errors import (
    BadRequestError,
    ConfigurationError,
    MfaChallengeInvalidError,
    MfaCodeRejectedError,
)
from app.core.security.aead import build_secret_box
from app.core.security.token import hash_token
from app.db.base import utc_now
from app.models import AdminUser, UserMfa
from app.models.enums import MfaPolicySubject, MfaStatus
from app.models.mfa import MfaChallenge, MfaPolicy
from app.repositories.mfa import MfaRepository
from app.repositories.role import RoleRepository
from app.services.mfa import MfaProviderRegistry, MfaSetupMaterial
from app.services.mfa_management import (
    CHALLENGE_TTL_SECONDS,
    MAX_CHALLENGE_ATTEMPTS,
    MfaManagementService,
    build_policy_resolver,
)
from tests.conftest import RecordingAuditRecorder
from tests.factories import link_user_role, make_department, make_role, make_user

pytestmark = pytest.mark.integration

# ---- 部门 / 角色 ----
DEPT_MAIN = 53001
ROLE_REQUIRED = 53011
ROLE_FREE = 53012
ROLE_SILENT = 53013

# ---- 用户 ----
U_PLAIN = 53101  # 无任何角色策略、无凭据
U_ROLE_REQUIRED = 53102  # 角色要求 MFA
U_MULTI_ROLE = 53103  # ROLE_REQUIRED + ROLE_FREE → 合并取 OR → 要求
U_USER_OVERRIDE_OFF = 53104  # 用户级明确不要求，压过角色级要求
U_USER_OVERRIDE_ON = 53105  # 用户级要求，角色级未表态
U_SILENT_ROLE = 53106  # 角色级存在行但未表态 → 落到 system


class _TestProvider:
    """可替换的测试 Provider（仅 `tests/`）。

    刻意**不做**任何真实算法：`verify` 只是把一个由 secret 推导出的
    伪码与输入比对。这样既能完整跑通"绑定 → 启用 → 二次验证"的
    生命周期，又不会让任何真实算法混进产品代码。
    """

    name = "test"

    def __init__(self) -> None:
        #: 记录生命周期钩子被调用的用户，供"钩子确实被调用"的断言使用。
        self.enabled_for: list[int] = []
        self.disabled_for: list[int] = []
        self.setup_calls: list[int] = []

    @staticmethod
    def code_for(secret: str) -> str:
        """由 secret 推导出的"正确动态码"（伪算法，仅测试用）。"""
        return f"{sum(ord(char) for char in secret) % 1_000_000:06d}"

    def setup(self, *, user_id: int, account_name: str) -> MfaSetupMaterial:
        self.setup_calls.append(user_id)
        secret = f"TESTSECRET-{user_id}"
        return MfaSetupMaterial(
            secret=secret, provisioning_uri=f"test://enroll/{account_name}/{user_id}"
        )

    def verify(self, *, secret: str, code: str) -> bool:
        return code == self.code_for(secret)

    def enable(self, *, user_id: int) -> None:
        self.enabled_for.append(user_id)

    def disable(self, *, user_id: int) -> None:
        self.disabled_for.append(user_id)


def _registry(provider: _TestProvider | None = None) -> tuple[MfaProviderRegistry, _TestProvider]:
    resolved = provider or _TestProvider()
    return MfaProviderRegistry({resolved.name: resolved}, active_name=resolved.name), resolved


def _service(
    session,
    *,
    registry: MfaProviderRegistry,
    audit: RecordingAuditRecorder | None = None,
) -> MfaManagementService:
    return MfaManagementService(session, audit=audit, registry=registry)


def _actor(user_id: int, username: str) -> CurrentActor:
    return CurrentActor(user_id=user_id, username=username, ip="10.0.0.7", user_agent="pytest/1.0")


def _encrypt_for(*, user_id: int, provider: str, secret: str) -> str:
    """按服务层同样的 AAD 口径加密（供播种"已绑定"状态使用）。"""
    return build_secret_box().encrypt(plaintext=secret, aad=f"{user_id}:{provider}")


def _all_schema_models() -> dict[str, type[BaseModel]]:
    """收集 `app/schemas/` 下**定义于本包**的全部 Pydantic 模型。

    用于"Secret 只能出现在一个响应 DTO 里"这类字段级护栏：
    只认 `obj.__module__` 与所在模块一致的类，避免把导入进来的
    第三方模型误当成自家 DTO。
    """
    import importlib
    import inspect
    import pkgutil

    import app.schemas as schemas_package

    discovered: dict[str, type[BaseModel]] = {}
    for module_info in pkgutil.iter_modules(schemas_package.__path__):
        module = importlib.import_module(f"{schemas_package.__name__}.{module_info.name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                discovered[name] = obj
    return discovered


@dataclass(frozen=True, slots=True)
class Fixture:
    """播种结果：部门、角色、用户与各自的凭据材料。"""

    secrets: dict[int, str]


async def _seed(session) -> Fixture:
    """播种部门 / 角色 / 用户 / 角色策略 / 凭据。"""
    await make_department(session, department_id=DEPT_MAIN, department_code="MFA_MAIN")

    await make_role(session, role_id=ROLE_REQUIRED, role_code="MFA_REQUIRED")
    await make_role(session, role_id=ROLE_FREE, role_code="MFA_FREE")
    await make_role(session, role_id=ROLE_SILENT, role_code="MFA_SILENT")

    await make_user(session, user_id=U_PLAIN, username="mfa-plain", department_id=DEPT_MAIN)
    await make_user(
        session, user_id=U_ROLE_REQUIRED, username="mfa-role-req", department_id=DEPT_MAIN
    )
    await make_user(session, user_id=U_MULTI_ROLE, username="mfa-multi", department_id=DEPT_MAIN)
    await make_user(
        session, user_id=U_USER_OVERRIDE_OFF, username="mfa-user-off", department_id=DEPT_MAIN
    )
    await make_user(
        session, user_id=U_USER_OVERRIDE_ON, username="mfa-user-on", department_id=DEPT_MAIN
    )
    await make_user(session, user_id=U_SILENT_ROLE, username="mfa-silent", department_id=DEPT_MAIN)

    await link_user_role(session, user_id=U_ROLE_REQUIRED, role_id=ROLE_REQUIRED)
    await link_user_role(session, user_id=U_MULTI_ROLE, role_id=ROLE_REQUIRED)
    await link_user_role(session, user_id=U_MULTI_ROLE, role_id=ROLE_FREE)
    await link_user_role(session, user_id=U_USER_OVERRIDE_OFF, role_id=ROLE_REQUIRED)
    await link_user_role(session, user_id=U_USER_OVERRIDE_ON, role_id=ROLE_REQUIRED)
    await link_user_role(session, user_id=U_SILENT_ROLE, role_id=ROLE_SILENT)

    mfa = MfaRepository(session)
    # 角色级：REQUIRED 明确要求；FREE 明确不要求；SILENT 存在但未表态。
    await mfa.set_policy(
        subject_type=MfaPolicySubject.ROLE, subject_id=ROLE_REQUIRED, required=True
    )
    await mfa.set_policy(subject_type=MfaPolicySubject.ROLE, subject_id=ROLE_FREE, required=False)
    await mfa.set_policy(subject_type=MfaPolicySubject.ROLE, subject_id=ROLE_SILENT, required=None)
    # 用户级：OFF 明确不要求（应终止解析链）；ON 明确要求。
    await mfa.set_policy(
        subject_type=MfaPolicySubject.USER, subject_id=U_USER_OVERRIDE_OFF, required=False
    )
    await mfa.set_policy(
        subject_type=MfaPolicySubject.USER, subject_id=U_USER_OVERRIDE_ON, required=True
    )
    return Fixture(secrets={})


async def _bind(
    session, *, user_id: int, provider: str = "test", secret: str | None = None
) -> tuple[UserMfa, str]:
    """直接把用户置于"已启用"状态，返回凭据行与明文 secret。"""
    resolved = secret or f"TESTSECRET-{user_id}"
    row = await MfaRepository(session).ensure_credential(user_id=user_id, provider=provider)
    await MfaRepository(session).put_secret(
        row, encrypted_secret=_encrypt_for(user_id=user_id, provider=provider, secret=resolved)
    )
    await MfaRepository(session).apply_status(row, MfaStatus.ENABLED, now=utc_now())
    return row, resolved


# ---------------------------------------------------------------------------
# 裁判 1：Provider 使用可扩展接口
# ---------------------------------------------------------------------------
class TestProviderAbstraction:
    """`04 §6`：Provider 必须抽象，实现可替换。"""

    async def test_registry_without_provider_fails_closed(self, db_session) -> None:
        """没有 Provider 时**不降级**：绑定必须明确失败。

        若这里返回一个"空 secret"，用户会以为绑定成功了。
        """
        await _seed(db_session)
        service = _service(db_session, registry=MfaProviderRegistry())
        with pytest.raises(ConfigurationError, match="没有可用的 MFA Provider"):
            await service.start_setup(actor=_actor(U_PLAIN, "mfa-plain"))

    async def test_any_protocol_conforming_provider_is_accepted(self, db_session) -> None:
        """换一个 Provider 实现，服务层代码无需改动。"""

        class _OtherProvider(_TestProvider):
            name = "other"

            @staticmethod
            def code_for(secret: str) -> str:
                return "999999"

        await _seed(db_session)
        registry, provider = _registry(_OtherProvider())
        service = _service(db_session, registry=registry)

        view = await service.start_setup(actor=_actor(U_PLAIN, "mfa-plain"))
        assert view.provider == "other"
        assert provider.setup_calls == [U_PLAIN]

        # 用"另一个 Provider 的码"必须被拒绝 → 证明生效的确实是新 Provider。
        with pytest.raises(MfaCodeRejectedError):
            await service.enable(actor=_actor(U_PLAIN, "mfa-plain"), code="000000")
        await service.enable(actor=_actor(U_PLAIN, "mfa-plain"), code="999999")

    async def test_credential_is_scoped_by_provider_name(self, db_session) -> None:
        """凭据按 `(user_id, provider)` 隔离，为"迁移 Provider 时新旧并存"留路。"""
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        await _bind(db_session, user_id=U_PLAIN, provider="test")

        # 同一用户、另一个 Provider 名下应视为"未绑定"。
        other = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="other")
        assert other is None
        view = await service.describe_status(actor=_actor(U_PLAIN, "mfa-plain"))
        assert view.has_credential is True
        assert view.status is MfaStatus.ENABLED


# ---------------------------------------------------------------------------
# 裁判 2：DISABLED / SETUP / ENABLED 生命周期
# ---------------------------------------------------------------------------
class TestLifecycle:
    """`04 §6` 冻结的三态：`DISABLED → SETUP → ENABLED`。"""

    async def test_initial_status_is_disabled_without_credential(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_PLAIN, "mfa-plain")
        )
        assert view.status is MfaStatus.DISABLED
        assert view.has_credential is False
        assert view.provider is None
        assert view.setup_at is None
        assert view.enabled_at is None

    async def test_setup_moves_to_setup_state(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        actor = _actor(U_PLAIN, "mfa-plain")

        view = await service.start_setup(actor=actor)
        assert view.provider == "test"
        assert view.secret == f"TESTSECRET-{U_PLAIN}"
        assert view.provisioning_uri.startswith("test://")

        status = await service.describe_status(actor=actor)
        assert status.status is MfaStatus.SETUP
        assert status.has_credential is True
        assert status.setup_at is not None
        assert status.enabled_at is None

    async def test_enable_requires_a_first_successful_verification(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        actor = _actor(U_PLAIN, "mfa-plain")

        view = await service.start_setup(actor=actor)
        with pytest.raises(MfaCodeRejectedError):
            await service.enable(actor=actor, code="111111")
        # 失败的 enable 不得把状态推进到 ENABLED。
        assert (await service.describe_status(actor=actor)).status is MfaStatus.SETUP

        await service.enable(actor=actor, code=provider.code_for(view.secret))
        status = await service.describe_status(actor=actor)
        assert status.status is MfaStatus.ENABLED
        assert status.enabled_at is not None
        assert status.verified_at is not None
        assert provider.enabled_for == [U_PLAIN]

    async def test_repeated_setup_from_enabled_returns_to_setup(self, db_session) -> None:
        """重新配网必须把 `enabled_at` 清掉 —— 否则"已启用"这一事实会失真。"""
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        actor = _actor(U_PLAIN, "mfa-plain")

        first = await service.start_setup(actor=actor)
        await service.enable(actor=actor, code=provider.code_for(first.secret))
        assert (await service.describe_status(actor=actor)).status is MfaStatus.ENABLED

        await service.start_setup(actor=actor)
        status = await service.describe_status(actor=actor)
        assert status.status is MfaStatus.SETUP
        assert status.enabled_at is None

    async def test_disable_requires_verification_and_returns_to_disabled(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        actor = _actor(U_PLAIN, "mfa-plain")
        _, secret = await _bind(db_session, user_id=U_PLAIN)

        with pytest.raises(MfaCodeRejectedError):
            await service.disable(actor=actor, code="000001")
        assert (await service.describe_status(actor=actor)).status is MfaStatus.ENABLED

        await service.disable(actor=actor, code=provider.code_for(secret))
        status = await service.describe_status(actor=actor)
        assert status.status is MfaStatus.DISABLED
        assert status.enabled_at is None
        assert provider.disabled_for == [U_PLAIN]

    async def test_enable_without_setup_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        with pytest.raises(BadRequestError, match="请先执行 setup"):
            await service.enable(
                actor=_actor(U_PLAIN, "mfa-plain"), code=provider.code_for("TESTSECRET-53101")
            )

    async def test_disable_when_not_enabled_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        with pytest.raises(BadRequestError, match="没有已启用的 MFA 凭据"):
            await service.disable(
                actor=_actor(U_PLAIN, "mfa-plain"), code=provider.code_for("TESTSECRET-53101")
            )


# ---------------------------------------------------------------------------
# 裁判 3：Secret 加密保存
# ---------------------------------------------------------------------------
class TestSecretEncryption:
    """`04 §6`：Secret 必须加密保存；`10 §4`：不得出现明文。"""

    async def test_setup_stores_ciphertext_not_plaintext(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).start_setup(
            actor=_actor(U_PLAIN, "mfa-plain")
        )
        row = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="test")
        assert row is not None and row.encrypted_secret is not None

        assert row.encrypted_secret != view.secret
        assert view.secret not in row.encrypted_secret
        assert row.encrypted_secret.startswith("v1.")
        # 必须真的能解回来（否则只是"存了个没用的串"）。
        assert (
            build_secret_box().decrypt(ciphertext=row.encrypted_secret, aad=f"{U_PLAIN}:test")
            == view.secret
        )

    async def test_raw_sql_finds_no_plaintext_secret_anywhere(self, db_session) -> None:
        """**关键用例**：绕开 ORM 直接读库，任何列都不得出现明文 secret。

        ORM 层的断言可能被"某个字段其实没映射"放过，因此这里用原始 SQL
        扫 `user_mfa` 的全部文本列。
        """
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).start_setup(
            actor=_actor(U_PLAIN, "mfa-plain")
        )
        rows = (
            await db_session.execute(
                text(
                    "select provider, status, encrypted_secret from user_mfa where user_id = :uid"
                ),
                {"uid": U_PLAIN},
            )
        ).all()
        assert rows, "应当存在一条 user_mfa 行"
        for provider, status, ciphertext in rows:
            assert view.secret not in str(provider)
            assert view.secret not in str(status)
            assert ciphertext is not None
            assert view.secret not in ciphertext

    async def test_ciphertext_cannot_be_moved_to_another_user(self, db_session) -> None:
        """**AAD 绑定的真实价值**：把 A 的密文搬到 B 的行上必须失败。

        若没有 AAD，系统会用 A 的 secret 正常验证 B 的登录，且无迹可循。
        攻击路径取最现实的一条：搬运密文后，**受害者本人**来登录。
        """
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)

        # U_PLAIN 的密文被整行复制到 U_ROLE_REQUIRED 名下，两行都是 ENABLED。
        repo = MfaRepository(db_session)
        source = await repo.ensure_credential(user_id=U_PLAIN, provider="test")
        await repo.put_secret(
            source,
            encrypted_secret=_encrypt_for(user_id=U_PLAIN, provider="test", secret="PLAINSECRET"),
        )
        await repo.apply_status(source, MfaStatus.ENABLED, now=utc_now())

        victim = await repo.ensure_credential(user_id=U_ROLE_REQUIRED, provider="test")
        await repo.put_secret(victim, encrypted_secret=source.encrypted_secret)
        await repo.apply_status(victim, MfaStatus.ENABLED, now=utc_now())

        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")
        with pytest.raises(ConfigurationError, match="无法解密"):
            await service.redeem_challenge(
                token=issued.token, code=provider.code_for("PLAINSECRET")
            )

    async def test_disable_clears_the_stored_ciphertext(self, db_session) -> None:
        """禁用后不得继续留着一份可还原的 Secret —— 那是零收益的泄漏面。"""
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        await _bind(db_session, user_id=U_PLAIN)

        await service.disable(
            actor=_actor(U_PLAIN, "mfa-plain"),
            code=provider.code_for(f"TESTSECRET-{U_PLAIN}"),
        )
        row = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="test")
        assert row is not None
        assert row.status is MfaStatus.DISABLED
        assert row.encrypted_secret is None

    async def test_no_row_anywhere_holds_a_plaintext_looking_secret(self, db_session) -> None:
        """全域兜底：整个 `user_mfa` 表里不应出现测试 secret 的字面量。"""
        await _seed(db_session)
        registry, _ = _registry()
        await _service(db_session, registry=registry).start_setup(
            actor=_actor(U_PLAIN, "mfa-plain")
        )
        matches = (
            await db_session.execute(
                text("select count(*) from user_mfa where encrypted_secret like '%TESTSECRET%'")
            )
        ).scalar_one()
        assert matches == 0


# ---------------------------------------------------------------------------
# 裁判 4：Secret 不进入日志
# ---------------------------------------------------------------------------
class TestSecretNeverLeavesAudit:
    """`00 §8` / `04 §8`：审计与日志不得出现 MFA Secret。"""

    async def test_setup_audit_carries_no_secret(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        recorder = RecordingAuditRecorder()
        view = await _service(db_session, registry=registry, audit=recorder).start_setup(
            actor=_actor(U_PLAIN, "mfa-plain")
        )

        dumped = repr(list(recorder.events))
        assert view.secret not in dumped
        assert view.provisioning_uri not in dumped
        # 也不得出现密文（密文同样属"凭据材料"）。
        row = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="test")
        assert row is not None and row.encrypted_secret is not None
        assert row.encrypted_secret not in dumped

    async def test_enable_and_disable_audit_carry_no_secret(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        actor = _actor(U_PLAIN, "mfa-plain")

        view = await service.start_setup(actor=actor)
        await service.enable(actor=actor, code=provider.code_for(view.secret))
        await service.disable(actor=actor, code=provider.code_for(view.secret))

        dumped = repr(list(recorder.events))
        assert view.secret not in dumped
        for event in recorder.events:
            assert "encrypted_secret" not in repr(event.after_data or {})

    async def test_masking_covers_mfa_secret_keys(self) -> None:
        """脱敏清单必须认识 MFA 相关的键名（Phase 4 已就绪，此处复核未退化）。"""
        from app.core.masking import NEVER_LOG_KEYS, mask_value

        for key in ("mfa_secret", "totp_secret", "otp_secret", "mfa_encryption_key", "secret"):
            assert key in NEVER_LOG_KEYS
            assert mask_value(key, "TESTSECRET-53101") != "TESTSECRET-53101"


# ---------------------------------------------------------------------------
# 裁判 5 / 6：按角色、按用户配置
# ---------------------------------------------------------------------------
class TestRolePolicy:
    """`04 §7`：角色级策略。"""

    async def test_role_requirement_is_reported(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_ROLE_REQUIRED, "mfa-role-req")
        )
        assert view.required is True
        assert view.source == "ROLE"

    async def test_role_explicit_false_is_reported_as_not_required(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        await MfaRepository(db_session).set_policy(
            subject_type=MfaPolicySubject.ROLE, subject_id=ROLE_SILENT, required=False
        )
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_SILENT_ROLE, "mfa-silent")
        )
        assert view.required is False
        assert view.source == "ROLE"

    async def test_multi_role_merges_with_or(self, db_session) -> None:
        """多角色合并取 OR：任一角色要求即要求。

        取 AND（或"宽松者胜"）会让持有高敏角色的用户因另一个宽松角色
        **静默地**失去二次验证 —— 那是未经授权的安全弱化。
        """
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_MULTI_ROLE, "mfa-multi")
        )
        assert view.required is True
        assert view.source == "ROLE"

    async def test_role_rows_saying_nothing_fall_through(self, db_session) -> None:
        """角色行存在但 `required=NULL`（未表态）→ 交由 system，不算"已表态"。"""
        await _seed(db_session)
        resolver = build_policy_resolver(
            MfaRepository(db_session), RoleRepository(db_session), system_default=False
        )
        requirement = await resolver.resolve(user_id=U_SILENT_ROLE)
        assert requirement.source.value == "NONE"

    async def test_no_role_at_all_falls_through_to_system(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_PLAIN, "mfa-plain")
        )
        assert view.required is False
        assert view.source == "NONE"


class TestUserPolicy:
    """`04 §7`：用户级策略。"""

    async def test_user_requirement_is_reported(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        view = await _service(db_session, registry=registry).describe_status(
            actor=_actor(U_USER_OVERRIDE_ON, "mfa-user-on")
        )
        assert view.required is True
        assert view.source == "USER"

    async def test_user_policy_can_be_removed(self, db_session) -> None:
        """删掉用户级行后应回落到角色级 —— 证明 `None` 与 `False` 未被混淆。"""
        await _seed(db_session)
        repo = MfaRepository(db_session)
        assert await repo.delete_policy(
            subject_type=MfaPolicySubject.USER, subject_id=U_USER_OVERRIDE_OFF
        )

        resolver = build_policy_resolver(repo, RoleRepository(db_session), system_default=False)
        requirement = await resolver.resolve(user_id=U_USER_OVERRIDE_OFF)
        assert requirement.required is True
        assert requirement.source.value == "ROLE"

    async def test_delete_policy_reports_whether_it_deleted_anything(self, db_session) -> None:
        await _seed(db_session)
        repo = MfaRepository(db_session)
        assert (
            await repo.delete_policy(subject_type=MfaPolicySubject.USER, subject_id=U_PLAIN)
        ) is False
        assert await repo.delete_policy(
            subject_type=MfaPolicySubject.USER, subject_id=U_USER_OVERRIDE_ON
        )

    async def test_user_policy_row_is_unique_per_subject(self, db_session) -> None:
        """同一主体反复写入必须**覆盖**而不是堆积 —— 否则"哪一行说了算"会变成第二真相。"""
        await _seed(db_session)
        repo = MfaRepository(db_session)
        for value in (True, False, True):
            await repo.set_policy(
                subject_type=MfaPolicySubject.USER, subject_id=U_PLAIN, required=value
            )
        rows = list(
            (
                await db_session.execute(
                    select(MfaPolicy).where(
                        MfaPolicy.subject_type == MfaPolicySubject.USER,
                        MfaPolicy.subject_id == U_PLAIN,
                    )
                )
            ).scalars()
        )
        assert len(rows) == 1
        assert rows[0].required is True


# ---------------------------------------------------------------------------
# 裁判 7 / 8：优先级链
# ---------------------------------------------------------------------------
class TestPolicyPriority:
    """`04 §7`：`user > role > system`。"""

    async def test_user_overrides_role(self, db_session) -> None:
        await _seed(db_session)
        resolver = build_policy_resolver(
            MfaRepository(db_session), RoleRepository(db_session), system_default=False
        )
        requirement = await resolver.resolve(user_id=U_USER_OVERRIDE_OFF)
        assert requirement.required is False
        assert requirement.source.value == "USER"

    async def test_role_overrides_system(self, db_session) -> None:
        await _seed(db_session)
        resolver = build_policy_resolver(
            MfaRepository(db_session), RoleRepository(db_session), system_default=False
        )
        requirement = await resolver.resolve(user_id=U_ROLE_REQUIRED)
        assert requirement.required is True
        assert requirement.source.value == "ROLE"

    async def test_system_is_used_only_when_both_layers_say_nothing(self, db_session) -> None:
        await _seed(db_session)
        resolver = build_policy_resolver(
            MfaRepository(db_session), RoleRepository(db_session), system_default=True
        )
        requirement = await resolver.resolve(user_id=U_PLAIN)
        assert requirement.required is True
        assert requirement.source.value == "SYSTEM"

    async def test_status_endpoint_reports_the_effective_source(self, db_session) -> None:
        """`GET /auth/mfa` 必须告诉用户"这个要求是谁提的"，否则运维无从排查。"""
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        cases = {
            U_PLAIN: "NONE",
            U_ROLE_REQUIRED: "ROLE",
            U_USER_OVERRIDE_OFF: "USER",
            U_USER_OVERRIDE_ON: "USER",
            U_MULTI_ROLE: "ROLE",
        }
        for user_id, expected in cases.items():
            actor = _actor(user_id, f"u{user_id}")
            view = await service.describe_status(actor=actor)
            assert view.source == expected, f"user {user_id} 的策略来源应为 {expected}"


# ---------------------------------------------------------------------------
# 裁判 9：登录流程正确触发 MFA（挑战生命周期）
# ---------------------------------------------------------------------------
class TestChallengeLifecycle:
    """DD-23 方案 A：挑战一次性、限次、不建 Session。"""

    async def test_issue_then_redeem_returns_user_id(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        _, secret = await _bind(db_session, user_id=U_ROLE_REQUIRED)

        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")
        assert issued.token
        assert issued.expires_at > utc_now()
        user_id = await service.redeem_challenge(token=issued.token, code=provider.code_for(secret))
        assert user_id == U_ROLE_REQUIRED

    async def test_issue_creates_no_session(self, db_session) -> None:
        """**关键用例**（DD-23 方案 A）：签发挑战**不得**创建任何 Session。

        若提前建会话，"只输对密码的人"会出现在在线用户列表里；
        更严重的是"认证是否完成"会退化成 `sessions` 上的可选列。
        """
        await _seed(db_session)
        registry, _ = _registry()
        before = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        await _service(db_session, registry=registry).issue_challenge(
            user_id=U_ROLE_REQUIRED, provider_name="test"
        )
        after = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        assert after == before

    async def test_challenge_token_is_only_stored_as_hash(self, db_session) -> None:
        """库内只有哈希：DB 泄漏时攻击者无法用它续完任何一次登录。"""
        await _seed(db_session)
        registry, _ = _registry()
        issued = await _service(db_session, registry=registry).issue_challenge(
            user_id=U_ROLE_REQUIRED, provider_name="test"
        )
        row = (
            await db_session.execute(
                select(MfaChallenge).where(MfaChallenge.token_hash == hash_token(issued.token))
            )
        ).scalar_one()
        assert row.token_hash == hash_token(issued.token)
        assert issued.token != row.token_hash
        # 明文令牌不得出现在库内任何处。
        matches = (
            await db_session.execute(
                text("select count(*) from mfa_challenges where token_hash = :token"),
                {"token": issued.token},
            )
        ).scalar_one()
        assert matches == 0

    async def test_challenge_is_single_use(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        _, secret = await _bind(db_session, user_id=U_ROLE_REQUIRED)

        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")
        await service.redeem_challenge(token=issued.token, code=provider.code_for(secret))
        with pytest.raises(MfaChallengeInvalidError):
            await service.redeem_challenge(token=issued.token, code=provider.code_for(secret))

    async def test_unknown_token_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        with pytest.raises(MfaChallengeInvalidError):
            await _service(db_session, registry=registry).redeem_challenge(
                token="not-a-real-token", code=provider.code_for("TESTSECRET-53102")
            )

    async def test_expired_challenge_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        _, secret = await _bind(db_session, user_id=U_ROLE_REQUIRED)

        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")
        expired_at = utc_now() + timedelta(seconds=CHALLENGE_TTL_SECONDS + 1)
        with pytest.raises(MfaChallengeInvalidError):
            await service.redeem_challenge(
                token=issued.token, code=provider.code_for(secret), now=expired_at
            )

    async def test_wrong_code_keeps_challenge_alive_until_the_cap(self, db_session) -> None:
        """限次而非一次作废：偶发输错不必重走整个登录。"""
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        _, secret = await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")

        for _ in range(MAX_CHALLENGE_ATTEMPTS - 1):
            with pytest.raises(MfaCodeRejectedError):
                await service.redeem_challenge(token=issued.token, code="000000")

        # 仍可用正确码完成（证明前几次失败没有作废挑战）。
        assert (
            await service.redeem_challenge(token=issued.token, code=provider.code_for(secret))
            == U_ROLE_REQUIRED
        )

    async def test_challenge_is_burned_after_reaching_the_attempt_cap(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        service = _service(db_session, registry=registry)
        _, secret = await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")

        for _ in range(MAX_CHALLENGE_ATTEMPTS):
            with pytest.raises(MfaCodeRejectedError):
                await service.redeem_challenge(token=issued.token, code="000000")

        # 达到上限后挑战作废：**即使给出正确码也不放行**。
        with pytest.raises(MfaChallengeInvalidError):
            await service.redeem_challenge(token=issued.token, code=provider.code_for(secret))

    async def test_mfa_failure_does_not_lock_the_account(self, db_session) -> None:
        """DD-23 方案 A：MFA 失败**不锁定账号**（锁定归口令失败路径）。"""
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")

        for _ in range(MAX_CHALLENGE_ATTEMPTS + 2):
            with pytest.raises((MfaCodeRejectedError, MfaChallengeInvalidError)):
                await service.redeem_challenge(token=issued.token, code="000000")

        user = await db_session.get(AdminUser, U_ROLE_REQUIRED)
        assert user is not None
        assert user.failed_login_count == 0
        assert user.locked_until is None

    async def test_redeeming_after_unbind_is_rejected(self, db_session) -> None:
        """用户在挑战签发后解绑 → 必须作废这次登录尝试，而不是放行。"""
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")

        await MfaRepository(db_session).apply_status(
            await MfaRepository(db_session).get_credential(
                user_id=U_ROLE_REQUIRED, provider="test"
            ),
            MfaStatus.DISABLED,
            now=utc_now(),
        )
        with pytest.raises(MfaChallengeInvalidError):
            await service.redeem_challenge(token=issued.token, code="000000")

    async def test_redeem_when_provider_gone_fails_closed(self, db_session) -> None:
        """挑战所属 Provider 不可用 → 明确失败，**不得**放行。"""
        await _seed(db_session)
        registry, _ = _registry()
        await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await _service(db_session, registry=registry).issue_challenge(
            user_id=U_ROLE_REQUIRED, provider_name="test"
        )

        empty = _service(db_session, registry=MfaProviderRegistry())
        with pytest.raises(ConfigurationError, match="当前不可用"):
            await empty.redeem_challenge(token=issued.token, code="000000")

    async def test_enabled_credential_lookup(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        assert await service.enabled_credential(user_id=U_PLAIN) is None
        await _bind(db_session, user_id=U_PLAIN)
        assert await service.enabled_credential(user_id=U_PLAIN) is not None


# ---------------------------------------------------------------------------
# 裁判 10 / 11：enable / disable / failure 的安全日志
# ---------------------------------------------------------------------------
class TestSecurityAudit:
    """`04 §8` 的四类 MFA 事件：setup / enable / disable / failure。"""

    async def test_setup_enable_disable_produce_success_events(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        actor = _actor(U_PLAIN, "mfa-plain")

        view = await service.start_setup(actor=actor)
        await service.enable(actor=actor, code=provider.code_for(view.secret))
        await service.disable(actor=actor, code=provider.code_for(view.secret))

        assert recorder.actions()[:3] == ["MFA_SETUP", "MFA_ENABLE", "MFA_DISABLE"]
        assert recorder.results()[:3] == ["SUCCESS", "SUCCESS", "SUCCESS"]

    async def test_enable_failure_is_logged_with_reason(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        await service.start_setup(actor=_actor(U_PLAIN, "mfa-plain"))

        with pytest.raises(MfaCodeRejectedError):
            await service.enable(actor=_actor(U_PLAIN, "mfa-plain"), code="000000")

        failure = recorder.find("MFA_FAILURE")
        assert failure is not None
        assert str(failure.result) == "FAILURE"
        assert "WRONG_CODE_ON_ENABLE" in repr(failure)

    async def test_disable_failure_is_logged(self, db_session) -> None:
        await _seed(db_session)
        registry, _ = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        await _bind(db_session, user_id=U_PLAIN)

        with pytest.raises(MfaCodeRejectedError):
            await service.disable(actor=_actor(U_PLAIN, "mfa-plain"), code="000000")

        failure = recorder.find("MFA_FAILURE")
        assert failure is not None
        assert "WRONG_CODE_ON_DISABLE" in repr(failure)

    async def test_login_failure_is_logged_with_actor_from_challenge(self, db_session) -> None:
        """登录途中的失败没有已认证身份，审计仍须记到对的用户上。"""
        await _seed(db_session)
        registry, _ = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        await _bind(db_session, user_id=U_ROLE_REQUIRED)
        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")

        with pytest.raises(MfaCodeRejectedError):
            await service.redeem_challenge(token=issued.token, code="000000")

        failure = recorder.find("MFA_FAILURE")
        assert failure is not None
        assert "WRONG_CODE_ON_LOGIN" in repr(failure)

    async def test_secret_decryption_failure_is_logged(self, db_session) -> None:
        """密文被搬行是一次真实的完整性违规，必须留痕而不是静默当作数据缺失。"""
        await _seed(db_session)
        registry, provider = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)

        repo = MfaRepository(db_session)
        source = await repo.ensure_credential(user_id=U_PLAIN, provider="test")
        await repo.put_secret(
            source,
            encrypted_secret=_encrypt_for(user_id=U_PLAIN, provider="test", secret="PLAINSECRET"),
        )
        await repo.apply_status(source, MfaStatus.ENABLED, now=utc_now())
        victim = await repo.ensure_credential(user_id=U_ROLE_REQUIRED, provider="test")
        await repo.put_secret(victim, encrypted_secret=source.encrypted_secret)
        await repo.apply_status(victim, MfaStatus.ENABLED, now=utc_now())

        issued = await service.issue_challenge(user_id=U_ROLE_REQUIRED, provider_name="test")
        with pytest.raises(ConfigurationError):
            await service.redeem_challenge(
                token=issued.token, code=provider.code_for("PLAINSECRET")
            )
        assert "SECRET_UNAVAILABLE" in repr(recorder.events)
        # 审计中不得出现密文本身。
        assert source.encrypted_secret not in repr(recorder.events)

    async def test_audit_never_contains_the_ciphertext(self, db_session) -> None:
        await _seed(db_session)
        registry, provider = _registry()
        recorder = RecordingAuditRecorder()
        service = _service(db_session, registry=registry, audit=recorder)
        actor = _actor(U_PLAIN, "mfa-plain")
        view = await service.start_setup(actor=actor)
        await service.enable(actor=actor, code=provider.code_for(view.secret))
        row = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="test")
        assert row is not None and row.encrypted_secret is not None
        assert row.encrypted_secret not in repr(recorder.events)


# ---------------------------------------------------------------------------
# 裁判 12：恢复流程不会泄漏 Secret
# ---------------------------------------------------------------------------
class TestNoSecretOnReadSurfaces:
    """本次裁定取"不新增恢复流程"的读法（见 `docs/DECISION-REQUEST-PHASE-5.md` §5）。

    因此本条要证明的是**反向命题**：除 `setup` 外不存在任何让 Secret 流出的路径。
    """

    async def test_status_view_has_no_secret_field(self) -> None:
        from app.services.mfa_management import MfaStatusView

        assert "secret" not in set(MfaStatusView.__dataclass_fields__)
        assert "encrypted_secret" not in set(MfaStatusView.__dataclass_fields__)

    async def test_only_setup_response_model_exposes_secret(self) -> None:
        """**自动化护栏**：全部响应 DTO 中，只有 `MfaSetupResponse` 带 `secret` 字段。

        将来任何人"顺手"把 secret 加进别的响应 DTO，这条断言会立刻失败。
        之所以不查 OpenAPI：本项目端点统一返回 `JSONResponse`（统一信封），
        OpenAPI 里因此没有响应模型，查它反而什么都查不到。
        """
        models = _all_schema_models()
        assert models, "未能发现任何响应 DTO，测试本身失效"
        exposing = {name for name, model in models.items() if "secret" in model.model_fields}
        assert exposing == {"MfaSetupResponse"}, f"Secret 泄漏面超出预期：{exposing}"

    async def test_setup_response_model_is_constructed_in_exactly_one_place(self) -> None:
        """`MfaSetupResponse` 只能被构造一次，且必须在 setup 端点里。

        这比"字段名相同"更强：即使有人新造一个别的 DTO 带 secret，
        下面的 AST 扫描也会因为它不是 `MfaSetupResponse` 而漏掉 ——
        因此本文件同时保留上一条字段级断言，两条互为补充。
        """
        root = Path(__file__).resolve().parents[1] / "app"
        sites: list[tuple[str, int]] = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                # 只看**构造点**（Name 节点）；导入语句是 ast.alias，不会被计入。
                if isinstance(node, ast.Name) and node.id == "MfaSetupResponse":
                    sites.append((str(path.relative_to(root)).replace("\\", "/"), node.lineno))
        assert len(sites) == 1, f"MfaSetupResponse 构造点数量异常：{sites}"
        assert sites[0][0] == "api/v1/endpoints/mfa.py", f"构造点位置异常：{sites}"

    async def test_no_recovery_endpoint_exists(self) -> None:
        """未新增恢复码 / 管理员重置端点（那是新增业务能力，须由人类裁定）。"""
        from app.main import create_app

        paths = set(create_app().openapi()["paths"])
        assert not [path for path in paths if "recovery" in path or "backup" in path]

    async def test_no_recovery_code_table_exists(self, db_session) -> None:
        tables = set(
            (
                await db_session.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema = 'public'"
                    )
                )
            ).scalars()
        )
        assert not [name for name in tables if "recovery" in name or "backup_code" in name]

    async def test_api_never_returns_the_ciphertext(self, db_session) -> None:
        """服务层返回值里不得含密文 —— 密文同样是凭据材料。"""
        await _seed(db_session)
        registry, _ = _registry()
        service = _service(db_session, registry=registry)
        view = await service.start_setup(actor=_actor(U_PLAIN, "mfa-plain"))
        row = await MfaRepository(db_session).get_credential(user_id=U_PLAIN, provider="test")
        assert row is not None and row.encrypted_secret is not None
        assert row.encrypted_secret not in repr(view)


# ---------------------------------------------------------------------------
# 裁判 13：不得擅自定义 V1 Provider
# ---------------------------------------------------------------------------
class TestNoConcreteProviderInProduct:
    """`00 §4` / `16 §1` / `PHASES.md` Phase 5：不得把具体 Provider 宣布为需求事实。"""

    #: 任何一类具体 MFA 算法库都不允许出现在产品代码里。
    _FORBIDDEN_IMPORTS = frozenset(
        {
            "pyotp",
            "onetimepass",
            "fido2",
            "webauthn",
            "yubico_client",
            "twilio",
            "qrcode",
        }
    )

    @staticmethod
    def _product_modules() -> list[Path]:
        root = Path(__file__).resolve().parents[1] / "app"
        return sorted(root.rglob("*.py"))

    def test_product_code_imports_no_concrete_mfa_library(self) -> None:
        offenders: dict[str, set[str]] = {}
        for module in self._product_modules():
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            hit = imported & self._FORBIDDEN_IMPORTS
            if hit:
                offenders[str(module)] = hit
        assert not offenders, f"产品代码引入了具体 MFA 算法库：{offenders}"

    def test_no_provider_is_registered_by_default(self) -> None:
        """产品出厂时**零 Provider**（DD-01 方案 A 的落地口径）。"""
        from app.services.mfa import get_mfa_provider_registry

        registry = get_mfa_provider_registry()
        assert registry.has_active() is False
        assert registry.active_name is None

    def test_no_provider_implementation_module_in_app(self) -> None:
        """`app/` 下不得出现"某个 Provider 的实现"模块。"""
        root = Path(__file__).resolve().parents[1] / "app"
        banned = ("totp", "hotp", "webauthn", "fido", "sms")
        found = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if any(token in path.name.lower() for token in banned)
        ]
        assert not found, f"发现具体 Provider 实现模块：{found}"

    async def test_service_requires_a_provider_instead_of_inventing_one(self, db_session) -> None:
        """没有 Provider 时服务抛错，而不是"内置一个"。"""
        await _seed(db_session)
        service = _service(db_session, registry=MfaProviderRegistry())
        assert service.active_provider_name() is None
        with pytest.raises(ConfigurationError):
            await service.start_setup(actor=_actor(U_PLAIN, "mfa-plain"))
