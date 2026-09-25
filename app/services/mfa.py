"""MFA 策略解析、Provider 抽象与登录流程的 MFA 步骤（DD-01 **方案 A**）。

范围边界（人类已裁定，2026-09-24）
-------------------------------
DD-01 方案 A 的落地口径：

| 内容 | Phase 4（本模块） | Phase 5（MFA） |
|---|---|---|
| 登录流程中的 **MFA check 步骤** | ✅ 落地（`04 §1` 第 6 步） | — |
| `MfaProvider` **抽象**（`04 §6`） | ✅ 落地（Protocol，无具体实现） | 注册具体 Provider |
| 生命周期 `DISABLED → SETUP → ENABLED`（`04 §6`） | ✅ 落地为枚举 | 持久化与状态迁移 |
| 策略优先级 `user > role > system`（`04 §7`） | ✅ 落地（系统级取配置） | user / role 两级的存储 |
| Secret 加密保存（`04 §6`） | ❌ 属 Phase 5 | ✅ |
| `/auth/mfa/*` 端点（`08 §3`） | ❌ 属 Phase 5 | ✅ |

**具体 Provider 不得由实现者自行选定**（`16 §技术设计待冻结项 #1`、
用户指令"不得自行宣布具体 Provider 为需求事实"）。
因此本模块**不包含** TOTP / WebAuthn / SMS 中任何一者的实现。

fail-closed 的关键设计
--------------------
"未配置 Provider" 与 "策略要求 MFA" 同时成立时，**绝不能静默放行** ——
那会把 `04 §7` 的策略配置变成装饰品（用户以为有二次验证，实际没有）。
本模块的处理是显式抛 `ConfigurationError`：

- 默认配置 `MFA_REQUIRED_DEFAULT=false` → 无人要求 MFA → 登录正常通过；
- 一旦有人把策略配成"要求"而系统还没有 Provider → **登录明确失败**，
  运维立刻看到配置缺失，而不是得到一个静默降级的系统。

这比"回落为不要求"安全，也比"假装通过"诚实。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.config import settings
from app.core.errors import ConfigurationError

#: Provider 名称长度上界（与 Phase 5 的持久化列宽对齐）。
MFA_PROVIDER_NAME_MAX_LENGTH = 32


class MfaPolicySource(StrEnum):
    """最终生效的 MFA 策略来自哪一层（供审计与诊断）。

    取值对应 Spec `04 §7` 的层级，外加 `NONE` 表示"所有层都未表态"。
    """

    USER = "USER"
    ROLE = "ROLE"
    SYSTEM = "SYSTEM"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class MfaRequirement:
    """一次登录需要满足的 MFA 要求。"""

    required: bool
    source: MfaPolicySource

    @classmethod
    def not_required(cls, source: MfaPolicySource = MfaPolicySource.NONE) -> MfaRequirement:
        """构造"不要求 MFA"的结果。"""
        return cls(required=False, source=source)


@dataclass(frozen=True, slots=True)
class MfaSetupMaterial:
    """Provider 在 `setup` 阶段返回的凭据材料。

    `secret` 是**明文**秘密，调用方（Phase 5 的服务层）必须用
    `MFA_ENCRYPTION_KEY` 加密后再落库（Spec `04 §6`"Secret 必须加密保存"）。
    Provider 不接触持久化，因此不承担"忘记加密"的风险。
    """

    secret: str
    provisioning_uri: str


class MfaProvider(Protocol):
    """MFA 算法侧抽象（Spec `04 §6`：`setup` / `verify` / `enable` / `disable`）。

    分层说明
    -------
    `04 §6` 列出四个动作，本实现按"**谁拥有状态**"把它们分成两组，
    动作集合本身**没有减少**：

    - `setup` / `verify` 与**具体算法**相关 → 由 Provider 实现；
    - `enable` / `disable` 只改变**生命周期状态**（落库），
      由服务层执行；Provider 通过这两个钩子获得通知，
      以便做算法侧副作用（例如失效已签发的恢复码）。

    这样 Provider 不需要知道数据库，也不需要知道 `MfaStatus` 如何持久化，
    Phase 5 换 Provider 时无需改服务层，反之亦然。

    属性 `name`：Provider 标识，写入用户 MFA 记录，
    用于将来"同一用户从 TOTP 迁移到 WebAuthn"的兼容判断。
    """

    name: str

    def setup(self, *, user_id: int, account_name: str) -> MfaSetupMaterial:
        """生成新的凭据材料（明文 secret + 配网 URI）。"""
        ...

    def verify(self, *, secret: str, code: str) -> bool:
        """校验用户提交的动态码。任何失败都返回 False，不抛异常。"""
        ...

    def enable(self, *, user_id: int) -> None:
        """生命周期钩子：该用户的 MFA 即将被置为 ENABLED。"""
        ...

    def disable(self, *, user_id: int) -> None:
        """生命周期钩子：该用户的 MFA 即将被置为 DISABLED。"""
        ...


class MfaProviderRegistry:
    """已注册 Provider 的登记处。

    Phase 4 的默认实例**为空**（没有任何具体 Provider 被冻结），
    因此 `has_active()` 恒为 False —— 这正是 DD-01 方案 A 描述的
    "未配置任何具体 Provider 时，所有用户 MFA 状态视为 DISABLED"。

    Phase 5 在此注册具体 Provider；本类的接口无需改动。
    """

    __slots__ = ("_active_name", "_providers")

    def __init__(
        self,
        providers: dict[str, MfaProvider] | None = None,
        *,
        active_name: str | None = None,
    ) -> None:
        self._providers: dict[str, MfaProvider] = dict(providers or {})
        self._active_name = active_name

    def get(self, name: str) -> MfaProvider | None:
        """按名称取 Provider。"""
        return self._providers.get(name)

    @property
    def active_name(self) -> str | None:
        """当前生效的 Provider 名称；None 表示尚无可用 Provider。"""
        return self._active_name

    def active(self) -> MfaProvider | None:
        """返回当前生效的 Provider（Phase 4 恒为 None）。"""
        if self._active_name is None:
            return None
        return self._providers.get(self._active_name)

    def has_active(self) -> bool:
        """是否存在可用的 Provider。"""
        return self.active() is not None

    def register(self, provider: MfaProvider, *, activate: bool = False) -> None:
        """注册 Provider（Phase 5 使用）。"""
        if len(provider.name) > MFA_PROVIDER_NAME_MAX_LENGTH:
            raise ValueError(
                f"Provider 名称超过 {MFA_PROVIDER_NAME_MAX_LENGTH} 字符：{provider.name}"
            )
        self._providers[provider.name] = provider
        if activate or self._active_name is None:
            self._active_name = provider.name


#: 进程级默认登记处（Phase 4：空）。
#:
#: 刻意不使用 FastAPI 依赖注入：MFA Provider 是**进程级不可变配置**，
#: 与请求无关；放进依赖树只会让每个读它的服务都多一个参数。
_default_registry = MfaProviderRegistry()


def get_mfa_provider_registry() -> MfaProviderRegistry:
    """返回进程级 Provider 登记处。"""
    return _default_registry


class UserMfaPolicySource(Protocol):
    """用户级 MFA 策略来源（Spec `04 §7` 最高优先级）。"""

    async def mfa_required_for_user(self, user_id: int) -> bool | None:
        """返回该用户的策略；`None` 表示**该层未表态**，交由下一层决定。"""
        ...


class RoleMfaPolicySource(Protocol):
    """角色级 MFA 策略来源（Spec `04 §7` 中间优先级）。"""

    async def mfa_required_for_roles(self, user_id: int) -> bool | None:
        """返回该用户角色集合的策略；`None` 表示未表态。"""
        ...


class UnsetUserMfaPolicySource:
    """Phase 4 的用户级策略来源：恒为"未表态"。

    为什么不是"返回 False"：`None`（未表态）与 `False`（明确不要求）
    在 `04 §7` 的优先级链上语义完全不同 ——
    前者应继续向下询问角色级，后者应**终止**解析。
    把"实现尚不存在"表达为 `False` 会让角色级策略永久失效。
    """

    async def mfa_required_for_user(self, user_id: int) -> bool | None:
        return None


class UnsetRoleMfaPolicySource:
    """Phase 4 的角色级策略来源：恒为"未表态"（存储属 Phase 5）。"""

    async def mfa_required_for_roles(self, user_id: int) -> bool | None:
        return None


class MfaPolicyResolver:
    """按 `user > role > system` 解析 MFA 要求（Spec `04 §7` 冻结的优先级）。

    解析规则（逐层向下，遇到第一个"已表态"的层即返回）：

    ```text
    user 有策略？ → 用它（source = USER）
    role 有策略？ → 用它（source = ROLE）
    system 默认   → 用它（source = SYSTEM）
    全部未表态    → 不要求（source = NONE）
    ```

    为什么"未表态"必须与"明确不要求"区分：若把未表态当成 False，
    用户级实现一旦上线就会**永久屏蔽**角色级策略，
    而这种"策略静默失效"在运行时完全看不出来。
    """

    __slots__ = ("_role_policy", "_system_default", "_user_policy")

    def __init__(
        self,
        *,
        user_policy: UserMfaPolicySource | None = None,
        role_policy: RoleMfaPolicySource | None = None,
        system_default: bool | None = None,
    ) -> None:
        self._user_policy: UserMfaPolicySource = user_policy or UnsetUserMfaPolicySource()
        self._role_policy: RoleMfaPolicySource = role_policy or UnsetRoleMfaPolicySource()
        self._system_default = (
            settings.mfa_required_default if system_default is None else system_default
        )

    async def resolve(self, *, user_id: int) -> MfaRequirement:
        """解析该用户登录时的 MFA 要求。"""
        user_level = await self._user_policy.mfa_required_for_user(user_id)
        if user_level is not None:
            return MfaRequirement(required=user_level, source=MfaPolicySource.USER)

        role_level = await self._role_policy.mfa_required_for_roles(user_id)
        if role_level is not None:
            return MfaRequirement(required=role_level, source=MfaPolicySource.ROLE)

        return MfaRequirement(
            required=self._system_default,
            source=MfaPolicySource.SYSTEM if self._system_default else MfaPolicySource.NONE,
        )


class MfaService:
    """登录流程中的 MFA 步骤（Spec `04 §1` 第 6 步）。

    本类只回答一个问题：**当前配置下，这次登录是否必须经过二次验证。**

    它**不**签发挑战、**不**校验动态码、**不**触碰 MFA 状态存储 ——
    那些属 Phase 5（`/auth/mfa/*`）。Phase 4 的职责是让这一步**存在、
    可观测、且不会静默降级**，从而让 Phase 5 只需替换实现、
    不必改动登录流程本身。
    """

    __slots__ = ("_registry", "_resolver")

    def __init__(
        self,
        *,
        resolver: MfaPolicyResolver | None = None,
        registry: MfaProviderRegistry | None = None,
    ) -> None:
        self._resolver = resolver or MfaPolicyResolver()
        self._registry = registry or get_mfa_provider_registry()

    async def check_login(self, *, user_id: int) -> MfaRequirement:
        """执行登录流程的 MFA 检查步骤（`04 §1` 第 6 步）。

        Returns:
            解析出的 MFA 要求。`required=True` 表示这次登录**必须**经过
            二次验证；具体走"签发挑战"还是"引导去绑定"，由调用方
            （`AuthService.login` 第 6b / 6c 步）依据"用户是否已启用凭据"决定。
            本方法刻意**不**替调用方做那个判断：那需要读凭据表，
            而本类持有的是**策略与 Provider 能力**，不持有持久化。

        Raises:
            ConfigurationError: 策略**要求**二次验证，但没有任何可用 Provider。
                这是刻意的 fail-closed：宁可让登录明确失败（配置问题立刻可见），
                也不能放行一个"号称有 MFA 实际没有"的系统。

        Phase 4 → Phase 5 的行为变更
        ---------------------------
        Phase 4 时本方法在"要求 + Provider 可用"时也抛 `ConfigurationError`
        （文案为"尚未实现"），因为当时挑战签发与校验并不存在，放行即等于
        "要求了二次验证却没验证"。Phase 5 已落地 `/auth/mfa/verify`，
        该占位分支因此**不再成立**，改为如实返回 `required=True`。
        这是"占位实现随真实实现到位而删除"，不是验收标准的放宽 ——
        "策略要求 + 无 Provider"这条 fail-closed 分支**一字未改**。
        """
        requirement = await self._resolver.resolve(user_id=user_id)
        if not requirement.required:
            return requirement

        if not self._registry.has_active():
            raise ConfigurationError(
                "MFA 策略要求二次验证，但当前没有可用的 MFA Provider"
                f"（策略来源={requirement.source.value}）。"
                "请配置 Provider，或将策略改回不要求二次验证。"
            )

        return requirement


__all__ = [
    "MFA_PROVIDER_NAME_MAX_LENGTH",
    "MfaPolicyResolver",
    "MfaPolicySource",
    "MfaProvider",
    "MfaProviderRegistry",
    "MfaRequirement",
    "MfaService",
    "MfaSetupMaterial",
    "RoleMfaPolicySource",
    "UnsetRoleMfaPolicySource",
    "UnsetUserMfaPolicySource",
    "UserMfaPolicySource",
    "get_mfa_provider_registry",
]
