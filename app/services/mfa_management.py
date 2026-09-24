"""MFA 管理：策略解析的落库实现、凭据生命周期、挑战签发与核销。

对应 DD-22 / DD-23 / DD-24 **方案 A**（`docs/DECISION-REQUEST-PHASE-5.md`）。

范围边界
--------
本模块负责"**用户自己的** MFA"：查询状态、绑定、启用、禁用、以及登录时的二次验证。
它**不包含**任何具体算法 —— V1 Provider 未冻结（`00 §4` / `16 §1`），
一切算法行为都经 `MfaProvider` 协议委托给注册进来的实现。

正因 `app/` 内没有算法，本模块仍可被完整测试：
测试里注册一个测试专用 Provider 即可跑通端到端生命周期，
而不会把某个具体 Provider 宣布成产品需求事实。

为什么用 `AuthAudit` 而不是 `AuditGuard`
---------------------------------------
`AuditGuard` 要求先有 `CurrentActor`（"操作者已确定"）。
而 MFA 有一类事件发生在**操作者尚未确定**的时刻：登录途中的挑战失败。
若为此编造一个 `CurrentActor`，审计里就会出现"看起来是某用户做的"的假记录，
比不记录更糟（理由详见 `app/services/auth_audit.py` 的模块文档）。
`AuthAudit` 接受允许身份为空的 `AuthOperator`，两种情形都能如实表达。

铁律
----
1. **明文 secret 只出现在 `start_setup` 的返回值里，且仅此一次**；
   其它任何位置（日志 / 审计 / API 响应 / 异常信息）都不得出现。
2. 入库的一律是 `MfaSecretBox` 的密文，AAD 绑定 `user_id:provider`。
3. 密钥缺失、密文损坏、密文被搬到别的用户行上 —— 全部**拒绝**；
   既不静默通过，也不当成"未启用"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import (
    BadRequestError,
    ConfigurationError,
    MfaChallengeInvalidError,
    MfaCodeRejectedError,
)
from app.core.security.aead import MfaSecretBox, SecretBoxError, build_secret_box
from app.core.security.token import generate_token
from app.db.base import utc_now
from app.models.enums import MfaStatus
from app.models.mfa import UserMfa
from app.repositories.mfa import MfaRepository
from app.repositories.role import RoleRepository
from app.services.auth_audit import AuthAudit, AuthOperator
from app.services.mfa import (
    MfaPolicyResolver,
    MfaProvider,
    MfaProviderRegistry,
    MfaRequirement,
    MfaSetupMaterial,
    RoleMfaPolicySource,
    UserMfaPolicySource,
    get_mfa_provider_registry,
)

#: 审计中的资源类型（`06 §2`）。
MFA_RESOURCE_TYPE = "MFA"

#: 挑战令牌寿命（DD-23 Q2）。
CHALLENGE_TTL_SECONDS = 300

#: 单个挑战允许的最大失败次数（DD-23 Q4）。
#:
#: 草案 Q3 写"成功或失败即作废"，Q4 又写"5 次后作废" —— 两者并存时 Q4 无意义。
#: 取 Q4（有限次重试后再作废），理由：Q3 想解决的是"用同一个挑战**无限次**试码"，
#: 有限次上限已达成同一目的；而一次性作废会让偶发的输错变成必须重走一遍登录。
#: 该取舍已登记为 INTERIM，因为它是对草案内部不一致的解释，而非新的要求。
MAX_CHALLENGE_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class MfaStatusView:
    """`GET /auth/mfa` 的响应内容。

    刻意**不含**任何凭据材料：没有 secret、没有密文、没有 provisioning_uri。
    `00 §1#12` 与 `10 §4` 要求 MFA Secret 绝不记录，而最容易失守的一环
    恰恰是"顺手把它塞进某个读接口"。
    """

    provider: str | None
    status: MfaStatus
    has_credential: bool
    setup_at: datetime | None
    enabled_at: datetime | None
    verified_at: datetime | None
    required: bool
    source: str


@dataclass(frozen=True, slots=True)
class MfaSetupView:
    """绑定阶段的返回值。

    `secret` 是**明文**，且本类只在 `start_setup` 中出现一次 ——
    用户必须靠它完成配网，这是唯一无法回避的暴露点。
    它**不会**出现在任何日志与审计事件中（请不要"为了调试方便"补上）。
    """

    provider: str
    secret: str
    provisioning_uri: str


@dataclass(frozen=True, slots=True)
class MfaChallengeIssued:
    """签发挑战的结果（明文令牌不落库，仅回给客户端一次）。"""

    token: str
    provider: str
    expires_at: datetime


class RepositoryUserMfaPolicySource(UserMfaPolicySource):
    """用户级策略来源的落库实现（Phase 4 时是恒返回 None 的 stub）。

    显式继承 `UserMfaPolicySource` 而不是仅"结构上长得像"：
    这样一旦上游 Protocol 改了签名，mypy 会在这里报错，
    而不是等到某个调用点才出现莫名其妙的行为。
    """

    __slots__ = ("_mfa",)

    def __init__(self, mfa: MfaRepository) -> None:
        self._mfa = mfa

    async def mfa_required_for_user(self, user_id: int) -> bool | None:
        return await self._mfa.get_user_policy_required(user_id=user_id)


class RepositoryRoleMfaPolicySource(RoleMfaPolicySource):
    """角色级策略来源的落库实现。

    多角色合并取 **OR**（任一角色要求 ⇒ 要求），理由见
    `app/repositories/mfa.py` 的模块文档：反向口径会让一个宽松角色
    静默覆盖掉严格角色的要求，属未经审视的安全弱化。
    """

    __slots__ = ("_mfa", "_roles")

    def __init__(self, mfa: MfaRepository, roles: RoleRepository) -> None:
        self._mfa = mfa
        self._roles = roles

    async def mfa_required_for_roles(self, user_id: int) -> bool | None:
        role_ids = sorted(await self._roles.list_active_role_ids_for_user(user_id))
        return await self._mfa.get_role_policy_required(role_ids=role_ids)


def build_policy_resolver(
    mfa: MfaRepository, roles: RoleRepository, *, system_default: bool | None = None
) -> MfaPolicyResolver:
    """装配 `user > role > system` 解析器（`04 §7` 冻结的优先级本身不再重实现）。"""
    return MfaPolicyResolver(
        user_policy=RepositoryUserMfaPolicySource(mfa),
        role_policy=RepositoryRoleMfaPolicySource(mfa, roles),
        system_default=system_default,
    )


class MfaManagementService:
    """MFA 凭据生命周期与二次验证。"""

    __slots__ = ("_audit", "_mfa", "_registry", "_roles", "_session")

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditRecorder | None = None,
        registry: MfaProviderRegistry | None = None,
    ) -> None:
        self._session = session
        self._audit = AuthAudit(audit or NullAuditRecorder())
        self._mfa = MfaRepository(session)
        self._roles = RoleRepository(session)
        self._registry = registry or get_mfa_provider_registry()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def active_provider_name(self) -> str | None:
        """当前生效 Provider 的名字；None 表示系统里还没有任何 Provider。"""
        return self._registry.active_name

    def _require_provider(self) -> tuple[str, MfaProvider]:
        """取当前生效 Provider；没有则 **fail-closed**。

        为什么不返回 `None` 让调用方"当作未启用"：一旦存在这条降级路径，
        "配置还没配好"就会伪装成"这个用户没开 MFA"，
        用户以为自己在做事，实际什么都没发生。
        """
        provider = self._registry.active()
        if provider is None:
            raise ConfigurationError("当前没有可用的 MFA Provider；请先安装并启用一个 Provider")
        return provider.name, provider

    @staticmethod
    def _aad(*, user_id: int, provider: str) -> str:
        """AEAD 的关联数据。绑定身份是为了让"密文被搬行"能被检测出来。"""
        return f"{user_id}:{provider}"

    @staticmethod
    def _operator(actor: CurrentActor) -> AuthOperator:
        return AuthOperator.of_user(
            user_id=actor.user_id,
            username=actor.username,
            ip=actor.ip,
            user_agent=actor.user_agent,
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def describe_status(self, *, actor: CurrentActor) -> MfaStatusView:
        """返回当前用户的 MFA 状态（不含任何凭据材料）。"""
        resolver = build_policy_resolver(self._mfa, self._roles)
        requirement: MfaRequirement = await resolver.resolve(user_id=actor.user_id)
        name = self.active_provider_name()
        row = await self._mfa.get_credential(user_id=actor.user_id, provider=name) if name else None
        return MfaStatusView(
            provider=row.provider if row else None,
            status=row.status if row else MfaStatus.DISABLED,
            has_credential=row is not None,
            setup_at=row.setup_at if row else None,
            enabled_at=row.enabled_at if row else None,
            verified_at=row.verified_at if row else None,
            required=requirement.required,
            source=requirement.source.value,
        )

    # ------------------------------------------------------------------
    # 生命周期（`04 §6`：DISABLED → SETUP → ENABLED）
    # ------------------------------------------------------------------

    async def start_setup(self, *, actor: CurrentActor) -> MfaSetupView:
        """进入 `SETUP`：向 Provider 索取材料，密文入库，明文只回这一次。"""
        name, provider = self._require_provider()
        material: MfaSetupMaterial = provider.setup(
            user_id=actor.user_id, account_name=actor.username
        )
        row = await self._mfa.ensure_credential(user_id=actor.user_id, provider=name)
        box = build_secret_box()
        ciphertext = box.encrypt(
            plaintext=material.secret,
            aad=self._aad(user_id=actor.user_id, provider=name),
        )
        await self._mfa.put_secret(row, encrypted_secret=ciphertext)
        now = utc_now()
        await self._mfa.apply_status(row, MfaStatus.SETUP, now=now)

        self._audit.success(
            action=AuditAction.MFA_SETUP,
            operator=self._operator(actor),
            resource_type=MFA_RESOURCE_TYPE,
            resource_id=row.id,
            # 审计里**只写"发生了什么"**，绝不写密文或明文 secret。
            after={"provider": name, "status": MfaStatus.SETUP.value},
        )
        return MfaSetupView(
            provider=name,
            secret=material.secret,
            provisioning_uri=material.provisioning_uri,
        )

    async def enable(self, *, actor: CurrentActor, code: str) -> None:
        """校验一次动态码，通过后置 `ENABLED`。"""
        name, provider = self._require_provider()
        row = await self._mfa.get_credential(user_id=actor.user_id, provider=name)
        if row is None or row.status is not MfaStatus.SETUP or not row.encrypted_secret:
            raise BadRequestError("当前没有处于绑定中的 MFA 凭据，请先执行 setup")

        secret = self._decrypt(row)
        if not provider.verify(secret=secret, code=code):
            self._audit.failure(
                action=AuditAction.MFA_FAILURE,
                operator=self._operator(actor),
                resource_type=MFA_RESOURCE_TYPE,
                resource_id=row.id,
                reason="WRONG_CODE_ON_ENABLE",
                error_code=int(MfaCodeRejectedError.code),
            )
            raise MfaCodeRejectedError()

        provider.enable(user_id=actor.user_id)
        now = utc_now()
        await self._mfa.apply_status(row, MfaStatus.ENABLED, now=now)
        await self._mfa.mark_verified(row, now=now)
        self._audit.success(
            action=AuditAction.MFA_ENABLE,
            operator=self._operator(actor),
            resource_type=MFA_RESOURCE_TYPE,
            resource_id=row.id,
            # `AuthAudit.success` 不暴露 `before_data`；状态迁移的起点是确定的
            # （ENABLE 只能从 SETUP 来），因此记迁移终点即可，不为此改共享组件。
            after={"status": MfaStatus.ENABLED.value, "provider": name},
        )

    async def disable(self, *, actor: CurrentActor, code: str) -> None:
        """关闭 MFA：清掉密文并回到 `DISABLED`。

        为什么禁用要顺带**清掉密文**：禁用后系统里若还留着一份可还原的 Secret，
        而它已不再参与任何校验 —— 那就是纯粹的、零收益的泄漏面。
        """
        name, provider = self._require_provider()
        row = await self._mfa.get_credential(user_id=actor.user_id, provider=name)
        if row is None or row.status is not MfaStatus.ENABLED or not row.encrypted_secret:
            raise BadRequestError("当前没有已启用的 MFA 凭据")

        secret = self._decrypt(row)
        if not provider.verify(secret=secret, code=code):
            self._audit.failure(
                action=AuditAction.MFA_FAILURE,
                operator=self._operator(actor),
                resource_type=MFA_RESOURCE_TYPE,
                resource_id=row.id,
                reason="WRONG_CODE_ON_DISABLE",
                error_code=int(MfaCodeRejectedError.code),
            )
            raise MfaCodeRejectedError()

        provider.disable(user_id=actor.user_id)
        await self._mfa.apply_status(row, MfaStatus.DISABLED, now=utc_now())
        self._audit.success(
            action=AuditAction.MFA_DISABLE,
            operator=self._operator(actor),
            resource_type=MFA_RESOURCE_TYPE,
            resource_id=row.id,
            after={"status": MfaStatus.DISABLED.value, "secret_cleared": True},
        )

    # ------------------------------------------------------------------
    # 登录期间的二次验证（DD-23 方案 A）
    # ------------------------------------------------------------------

    async def issue_challenge(
        self, *, user_id: int, provider_name: str, now: datetime | None = None
    ) -> MfaChallengeIssued:
        """签发一次性挑战。**不创建 Session**（理由见模块文档与 DD-23）。"""
        issued_at = now or utc_now()
        token = generate_token()
        expires_at = issued_at + timedelta(seconds=CHALLENGE_TTL_SECONDS)
        await self._mfa.create_challenge(
            user_id=user_id, provider=provider_name, token=token, expires_at=expires_at
        )
        return MfaChallengeIssued(token=token, provider=provider_name, expires_at=expires_at)

    async def redeem_challenge(self, *, token: str, code: str, now: datetime | None = None) -> int:
        """核销挑战并校验动态码。成功返回 `user_id`（交给登录流程续完登录）。

        Raises:
            MfaChallengeInvalidError: 令牌未知 / 已过期 / 已核销 / 已耗尽。
            MfaCodeRejectedError: 码不对（挑战仍存活，直到达到次数上限）。
            ConfigurationError: Provider 不可用或密文损坏 —— **一律不放行**。
        """
        checked_at = now or utc_now()
        row = await self._mfa.get_challenge_by_token(token)
        if row is None:
            raise MfaChallengeInvalidError()

        def operator() -> AuthOperator:
            return AuthOperator(user_id=row.user_id)

        if row.consumed_at is not None or row.expires_at <= checked_at:
            # 过期与已核销给出**同一个**对外结果：区分它们等于告诉调用方
            # "这个令牌曾经存在、现在已经过期"，可被用于枚举。
            raise MfaChallengeInvalidError()
        if row.attempts >= MAX_CHALLENGE_ATTEMPTS:
            await self._mfa.consume_challenge(row, now=checked_at)
            raise MfaChallengeInvalidError()

        provider = self._registry.get(row.provider)
        if provider is None:
            raise ConfigurationError(f"该挑战所属的 MFA Provider（{row.provider}）当前不可用")
        credential = await self._mfa.get_credential(user_id=row.user_id, provider=row.provider)
        if credential is None or credential.status is not MfaStatus.ENABLED:
            # 用户在挑战签发后解绑了 —— 必须作废这次登录尝试，而不是放行。
            await self._mfa.consume_challenge(row, now=checked_at)
            raise MfaChallengeInvalidError()

        secret = self._decrypt(credential, user_id=row.user_id, provider=row.provider)
        if not provider.verify(secret=secret, code=code):
            updated = await self._mfa.record_failed_attempt(row)
            if updated.attempts >= MAX_CHALLENGE_ATTEMPTS:
                await self._mfa.consume_challenge(updated, now=checked_at)
            self._audit.failure(
                action=AuditAction.MFA_FAILURE,
                operator=operator(),
                resource_type=MFA_RESOURCE_TYPE,
                resource_id=row.id,
                reason="WRONG_CODE_ON_LOGIN",
                error_code=int(MfaCodeRejectedError.code),
            )
            raise MfaCodeRejectedError()

        await self._mfa.consume_challenge(row, now=checked_at)
        await self._mfa.mark_verified(credential, now=checked_at)
        return row.user_id

    # ------------------------------------------------------------------
    # 登录流程的查询入口
    # ------------------------------------------------------------------

    async def requirement_for(self, *, user_id: int) -> MfaRequirement:
        """该用户是否被策略要求二次验证（`04 §7`）。"""
        resolver = build_policy_resolver(self._mfa, self._roles)
        return await resolver.resolve(user_id=user_id)

    async def enabled_credential(self, *, user_id: int) -> UserMfa | None:
        """取该用户当前**已启用**的凭据；没有则返回 None（表示尚未完成绑定）。"""
        row = await self._mfa.get_credential(
            user_id=user_id, provider=self.active_provider_name() or ""
        )
        if row is None or row.status is not MfaStatus.ENABLED:
            return None
        return row

    # ------------------------------------------------------------------
    # 私有：解密（明文 secret 的唯一出口）
    # ------------------------------------------------------------------

    def _decrypt(
        self, row: UserMfa, *, user_id: int | None = None, provider: str | None = None
    ) -> str:
        """把库里的密文还原成明文。**这是明文 secret 在本系统中的唯一出口**。

        失败一律按"凭据不可用"处理：既不当作"没绑定"，也绝不静默放行。
        """
        if not row.encrypted_secret:
            raise ConfigurationError("该凭据没有密文")
        box: MfaSecretBox = build_secret_box()
        try:
            return box.decrypt(
                ciphertext=row.encrypted_secret,
                aad=self._aad(
                    user_id=user_id if user_id is not None else row.user_id,
                    provider=provider if provider is not None else row.provider,
                ),
            )
        except SecretBoxError as exc:
            # 最常见的成因是"密文被复制到别的用户行上"（AAD 不匹配）。
            # 把它记成 MFA_FAILURE，让这种搬运行为在运维面上可见。
            self._audit.failure(
                action=AuditAction.MFA_FAILURE,
                operator=AuthOperator(user_id=row.user_id),
                resource_type=MFA_RESOURCE_TYPE,
                resource_id=row.id,
                reason="SECRET_UNAVAILABLE",
                error_code=int(ConfigurationError.code),
            )
            raise ConfigurationError("MFA 凭据无法解密：密文损坏或归属不匹配") from exc


__all__ = [
    "CHALLENGE_TTL_SECONDS",
    "MAX_CHALLENGE_ATTEMPTS",
    "MFA_RESOURCE_TYPE",
    "MfaChallengeIssued",
    "MfaManagementService",
    "MfaSetupView",
    "MfaStatusView",
    "RepositoryRoleMfaPolicySource",
    "RepositoryUserMfaPolicySource",
    "build_policy_resolver",
]
