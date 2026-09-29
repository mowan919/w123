"""TOTP Provider —— DD-01 的落地选择（`RESOLVED-29-02`）。

DD-01"具体 Provider 未冻结"到此为止：系统里现在有了一个**真实可用**的
MFA Provider。此前 `MfaProviderRegistry` 一直为空，`MfaManagementService`
按 fail-closed 原则对所有 MFA 动作抛
`ConfigurationError("当前没有可用的 MFA Provider")` —— 于是
`GET /auth/mfa` 报"未启用"、`POST /auth/mfa/setup` 直接失败，
用户界面上的 MFA 功能整体不可用。

为什么选 TOTP（是取舍，不是默认值）
---------------------------------
- **无外部依赖**：不依赖短信网关、邮件服务或推送通道，离线也能出码，
  不把登录可用性押在第三方身上；
- **无第三方账号绑定**：不收集手机号 / 邮箱，不引入新的个人信息处理；
- **标准化**：二维码与 Secret 都是公开格式，用户换 App / 换手机不锁死；
- 代价是需要"用户装一个 App"，以及_SECRET 丢了就恢复不了_ ——
  后者由"禁用需再校验一次动态码"与管理端重置路径共同承担。

`enable` / `disable` 为什么是空实现
----------------------------------
协议把它们设计成"生命周期通知"，目的是让**有算法侧副作用**的 Provider
（例如 WebAuthn 要作废已注册的凭据、短信 Provider 要作废未用验证码）
能在状态切换时清理。TOTP 没有这类副作用 —— 密钥本身就是全部状态，
且它由服务层加密保管。所以这里不是"忘了实现"，而是**明确无事可做**；
留空比放一个没意义的 log 更诚实。
"""

from __future__ import annotations

from typing import Final

from app.core.security.totp import (
    DEFAULT_DIGITS,
    DEFAULT_PERIOD_SECONDS,
    generate_secret,
    provisioning_uri,
    verify_code,
)
from app.services.mfa import MfaProviderRegistry, MfaSetupMaterial, get_mfa_provider_registry

__all__ = [
    "TOTP_PROVIDER_NAME",
    "TotpMfaProvider",
    "install_totp_provider",
]

#: Provider 名称。会写进 `user_mfa.provider` 列，因此它一旦上线就是**数据**，
#: 将来换 Provider 时靠它判断"这行密钥是哪个算法签的"；改名等于数据迁移。
TOTP_PROVIDER_NAME: Final[str] = "TOTP"


class TotpMfaProvider:
    """TOTP Provider（RFC 6238，SHA-1 / 6 位 / 30 秒）。

    刻意**不实现**任何持久化：密钥由调用方（服务层）加密后入库，
    Provider 拿到的 plaintext secret 只存在于一次调用的生命周期里。
    这样"密文有没有被加密保存"的风险不在 Provider 这边。
    """

    #: `MfaProvider` 协议把 `name` 声明为**属性**；这里必须是**类变量**
    #: 而不是 `@property` —— 协议成员是可写的，只读属性过不了结构化类型检查。
    name = TOTP_PROVIDER_NAME

    #: 验证码位数，供上层做输入提示（例如前端的 input 长度限制）。
    digits: Final[int] = DEFAULT_DIGITS
    #: 单个动态码的有效秒数。
    period_seconds: Final[int] = DEFAULT_PERIOD_SECONDS

    def setup(self, *, user_id: int, account_name: str) -> MfaSetupMaterial:
        """生成新的密钥材料。

        `user_id` 不参与密钥生成 —— 密钥必须是纯随机的，把 ID 混进去只会
        让人以为"猜到 ID 就有了一半密钥"。它在签名里是为了让将来的
        Provider（例如手机号 / 邮件）能按用户取已有联系方式。
        """
        secret = generate_secret()
        return MfaSetupMaterial(
            secret=secret,
            provisioning_uri=provisioning_uri(secret=secret, account_name=account_name),
        )

    def verify(self, *, secret: str, code: str) -> bool:
        """校验动态码。任何失败都返回 False —— 契约见 `MfaProvider.verify`。"""
        return verify_code(secret=secret, code=code)

    def enable(self, *, user_id: int) -> None:
        """生命周期钩子：TOTP 无算法侧副作用（理由见模块文档）。"""

    def disable(self, *, user_id: int) -> None:
        """生命周期钩子：TOTP 无算法侧副作用（理由见模块文档）。"""


def install_totp_provider(registry: MfaProviderRegistry | None = None) -> str:
    """把 TOTP Provider 装进登记处并激活；返回当前生效的 Provider 名。

    幂等与否很重要：`create_app()` 在测试里会被调用几十次，而登记处是
    **进程级**单例。重复注册同一个实现本身无害（后者覆盖前者），但会掩盖
    "有人在别处也注册了一个"的事实。因此这里只在"当前没有生效 Provider"
    时才装，且保留已存在的那个 —— 显式注入优先于默认装配。
    """
    target = registry if registry is not None else get_mfa_provider_registry()
    if target.active() is None:
        target.register(TotpMfaProvider(), activate=True)
    return target.active_name or TOTP_PROVIDER_NAME
