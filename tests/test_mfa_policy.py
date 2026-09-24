"""MFA 策略解析与登录步骤的 fail-closed 行为（Phase 4 / DD-01 方案 A）。

DD-01 方案 A 裁定：Phase 4 落地"登录流程的 MFA 步骤 + Provider 抽象 +
fail-closed 默认"，具体 Provider 留 Phase 5。

因此本文件钉住两件事：

1. `user > role > system` 的优先级链（`04 §7` 冻结）**真的**按层短路；
2. "策略要求 MFA 但没有可用 Provider" 时**必须拒绝登录**，绝不静默放行 ——
   否则 `04 §7` 的策略配置会变成装饰品。
"""

from __future__ import annotations

import pytest

from app.core.errors import ConfigurationError
from app.services.mfa import (
    MfaPolicyResolver,
    MfaPolicySource,
    MfaProviderRegistry,
    MfaRequirement,
    MfaService,
    MfaSetupMaterial,
)

pytestmark = pytest.mark.unit

USER_ID = 7001


class _StubUserPolicy:
    """可控的用户级策略来源。"""

    def __init__(self, value: bool | None) -> None:
        self.value = value

    async def mfa_required_for_user(self, user_id: int) -> bool | None:
        return self.value


class _StubRolePolicy:
    """可控的角色级策略来源。"""

    def __init__(self, value: bool | None) -> None:
        self.value = value

    async def mfa_required_for_roles(self, user_id: int) -> bool | None:
        return self.value


class _StubProvider:
    """具备 `MfaProvider` 形状的测试替身（Phase 5 才会有真实实现）。"""

    name = "stub"

    def setup(self, *, user_id: int, account_name: str) -> MfaSetupMaterial:
        return MfaSetupMaterial(secret="s3cret", provisioning_uri="otpauth://stub")

    def verify(self, *, secret: str, code: str) -> bool:
        return code == "000000"

    def enable(self, *, user_id: int) -> None:
        return None

    def disable(self, *, user_id: int) -> None:
        return None


class TestPolicyPriority:
    """Spec `04 §7`：优先级 `user > role > system`。"""

    async def test_system_default_false_means_not_required(self) -> None:
        resolver = MfaPolicyResolver(system_default=False)
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is False
        assert requirement.source is MfaPolicySource.NONE

    async def test_system_default_true_is_used_when_no_higher_layer_speaks(self) -> None:
        resolver = MfaPolicyResolver(system_default=True)
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is True
        assert requirement.source is MfaPolicySource.SYSTEM

    async def test_role_overrides_system(self) -> None:
        resolver = MfaPolicyResolver(role_policy=_StubRolePolicy(True), system_default=False)
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is True
        assert requirement.source is MfaPolicySource.ROLE

    async def test_user_overrides_role(self) -> None:
        resolver = MfaPolicyResolver(
            user_policy=_StubUserPolicy(True),
            role_policy=_StubRolePolicy(False),
            system_default=False,
        )
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is True
        assert requirement.source is MfaPolicySource.USER

    async def test_explicit_user_false_terminates_the_chain(self) -> None:
        """用户级**明确**说"不要求"时，不得再去看角色级。

        这是 `None`（未表态）与 `False`（明确不要求）必须区分的理由：
        若把两者混为一谈，一旦用户级策略上线就会永久屏蔽角色级策略，
        而这种"策略静默失效"在运行时完全看不出来。
        """
        resolver = MfaPolicyResolver(
            user_policy=_StubUserPolicy(False),
            role_policy=_StubRolePolicy(True),
            system_default=True,
        )
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is False
        assert requirement.source is MfaPolicySource.USER

    async def test_unset_user_falls_through_to_role(self) -> None:
        resolver = MfaPolicyResolver(
            user_policy=_StubUserPolicy(None),
            role_policy=_StubRolePolicy(True),
            system_default=False,
        )
        requirement = await resolver.resolve(user_id=USER_ID)
        assert requirement.required is True
        assert requirement.source is MfaPolicySource.ROLE


class TestLoginStep:
    """`MfaService.check_login` 是 `04 §1` 的第 6 步。"""

    async def test_not_required_passes(self) -> None:
        service = MfaService(resolver=MfaPolicyResolver(system_default=False))
        requirement = await service.check_login(user_id=USER_ID)
        assert requirement.required is False

    async def test_required_without_provider_fails_closed(self) -> None:
        """**关键用例**：策略要求 MFA 但没有 Provider → 必须拒绝，不能放行。

        若此处放行，等于"配置了二次验证但实际没有" ——
        比不配置更危险，因为运维会以为已有保护。
        """
        service = MfaService(
            resolver=MfaPolicyResolver(system_default=True),
            registry=MfaProviderRegistry(),
        )
        with pytest.raises(ConfigurationError, match="没有可用的 MFA Provider"):
            await service.check_login(user_id=USER_ID)

    async def test_required_with_provider_still_refuses_until_phase_5(self) -> None:
        """Provider 可用但"挑战签发/校验"尚未实现时同样拒绝。

        Phase 4 尚未实现 `/auth/mfa/verify`；此时若放行，
        就等于"要求了二次验证却没验证"。宁可明确失败。
        """
        registry = MfaProviderRegistry({"stub": _StubProvider()}, active_name="stub")
        assert registry.has_active() is True
        service = MfaService(resolver=MfaPolicyResolver(system_default=True), registry=registry)
        with pytest.raises(ConfigurationError, match="尚未实现"):
            await service.check_login(user_id=USER_ID)


class TestProviderRegistry:
    def test_default_registry_has_no_active_provider(self) -> None:
        """Phase 4 不注册任何具体 Provider（DD-01：Provider 未冻结）。"""
        registry = MfaProviderRegistry()
        assert registry.has_active() is False
        assert registry.active() is None
        assert registry.active_name is None

    def test_register_activates_first_provider(self) -> None:
        registry = MfaProviderRegistry()
        provider = _StubProvider()
        registry.register(provider)
        assert registry.active_name == "stub"
        assert registry.active() is provider

    def test_register_rejects_overlong_name(self) -> None:
        """Provider 名称要落库（Phase 5），超长必须在注册时就拒绝。"""

        class _LongNameProvider(_StubProvider):
            name = "x" * 64

        registry = MfaProviderRegistry()
        with pytest.raises(ValueError, match="Provider 名称超过"):
            registry.register(_LongNameProvider())


class TestRequirementValueObject:
    def test_not_required_helper(self) -> None:
        requirement = MfaRequirement.not_required()
        assert requirement.required is False
        assert requirement.source is MfaPolicySource.NONE
