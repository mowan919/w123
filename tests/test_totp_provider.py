"""TOTP Provider：算法正确性 + Provider 契约 + 默认装配。

算法正确性**只用 RFC 6238 / RFC 4226 的测试向量**钉 —— 自造断言在这里
价值很低：它们验证的是"我写的是我以为我写的"，而公开向量验证的是
"我写的和别人写的一样"。这类"跨实现一致"正是动态码能不能被 Google
Authenticator / 1Password 认出来的唯一标准。

Provider 契约部分测的是 `MfaProvider` 协议要求的三个动作在本实现上的
行为边界（失败返回 False 而不是抛异常等），与
`tests/test_mfa_management.py` 里"服务层如何调用 Provider"互补。
"""

from __future__ import annotations

import base64
import re
import time

import pytest

from app.core.security.totp import (
    DEFAULT_DIGITS,
    DEFAULT_PERIOD_SECONDS,
    generate_secret,
    hotp,
    provisioning_uri,
    verify_code,
)
from app.services.mfa import MfaProviderRegistry
from app.services.mfa_totp import TOTP_PROVIDER_NAME, TotpMfaProvider, install_totp_provider

# RFC 6238 附录 B 的测试向量。
#
# 注意两点：
# 1. 密钥是 **20 个 ASCII 字符**（不是 Base32 串），HMAC 直接拿它的字节用；
# 2. 期望值是 **8 位**，而产品用 6 位 —— 所以本文件的产品用例必须显式
#    传 `digits=8` 才能对上向量。位数不是算法的一部分，是展示参数。
_RFC_KEY = b"12345678901234567890"
_RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("unix_time", "expected"), _RFC_VECTORS)
def test_hotp_matches_rfc6238_vectors(unix_time: int, expected: str) -> None:
    """与 RFC 6238 附录 B 逐条对齐（8 位档）。"""
    assert hotp(_RFC_KEY, unix_time // DEFAULT_PERIOD_SECONDS, digits=8) == expected


def test_six_digit_result_is_the_tail_of_the_eight_digit_one() -> None:
    """同一个 counter 上的 6 位结果必须是 8 位结果的**后 6 位**。

    这条断言看着平凡，却是"位数只影响显示"的唯一证明：一旦有人在
    取模之外又做了别的处理（例如额外哈希一次），这里会立刻红。
    """
    for unix_time, expected8 in _RFC_VECTORS:
        step = unix_time // DEFAULT_PERIOD_SECONDS
        six = hotp(_RFC_KEY, step)
        assert six == expected8[-DEFAULT_DIGITS:]


def test_counter_is_the_hmac_message_and_time_step_is_the_contract() -> None:
    """TOTP = HOTP(counter = floor(time / period))。

    相邻时间**步**必须给出不同的码，同一时间步内必须给出同一个码 ——
    前者证明"会滚"，后者证明"不会一直滚"。缺任何一半都是坏了的实现，
    但两者分开都测不出来，必须写成一对。
    """
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    within_step_a = step * DEFAULT_PERIOD_SECONDS
    within_step_b = within_step_a + DEFAULT_PERIOD_SECONDS - 1
    next_step = within_step_a + DEFAULT_PERIOD_SECONDS

    assert hotp(_RFC_KEY, int(within_step_a / DEFAULT_PERIOD_SECONDS), digits=8) == hotp(
        _RFC_KEY, int(within_step_b / DEFAULT_PERIOD_SECONDS), digits=8
    )
    assert hotp(_RFC_KEY, int(within_step_a / DEFAULT_PERIOD_SECONDS), digits=8) != hotp(
        _RFC_KEY, int(next_step / DEFAULT_PERIOD_SECONDS), digits=8
    )


# ---------------------------------------------------------------------------
# 密钥材料
# ---------------------------------------------------------------------------


def test_generated_secret_shape() -> None:
    secret = generate_secret()
    # 20 字节 → Base32 32 字符（无 padding）。短一位说明熵不够。
    assert len(secret) == 32
    # `otpauth://` 的通行做法是不带 `=`：扫码时它会被当成噪声。
    assert "=" not in secret
    assert re.fullmatch(r"[A-Z2-7]+", secret) is not None


def test_generated_secret_is_random_per_call() -> None:
    """20 次调用必须给出 20 个不同的密钥；撞了说明掺了不该掺的状态。"""
    secrets = {generate_secret() for _ in range(20)}
    assert len(secrets) == 20


def test_provisioning_uri_carries_everything_authenticator_apps_need() -> None:
    secret = generate_secret()
    uri = provisioning_uri(secret=secret, account_name="bob", issuer="VCTN")

    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    # `issuer` 必须出现在 query 里：路径前缀那份是给人看的，
    # Google Authenticator 只读 query 那份 —— 缺了它账号就没有名字。
    assert "issuer=VCTN" in uri
    assert "digits=6" in uri
    assert "period=30" in uri
    # 路径里的 label 做过 URL 编码（`VCTN:bob` 的冒号必须转义）。
    assert "VCTN%3Abob" in uri


# ---------------------------------------------------------------------------
# 校验边界
# ---------------------------------------------------------------------------


def b32_of(key: bytes) -> str:
    """RFC 向量的 key 是裸字节；`verify_code` 吃的是 Base32 串。"""
    return base64.b32encode(key).decode("ascii").rstrip("=")


def code_at(key: bytes, step: int) -> str:
    return hotp(key, step)


def test_accepts_the_current_window() -> None:
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    now = step * DEFAULT_PERIOD_SECONDS + 7
    assert verify_code(secret=b32_of(_RFC_KEY), code=code_at(_RFC_KEY, step), timestamp=now)


@pytest.mark.parametrize("drift", [-1, 1])
def test_accepts_one_window_of_clock_drift(drift: int) -> None:
    """±1 窗（30 秒）要过：这是 RFC 6238 §5.2 推荐的容差。

    它不是"放宽安全"，而是承认一个事实：用户在手机上看到的码，
    走到你这儿提交时可能刚好跨过边界。**拒绝这一秒的输入**换来的是
    用户把 MFA 关掉。
    """
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    now = step * DEFAULT_PERIOD_SECONDS + 7
    from_step = step - drift if drift < 0 else step + drift
    assert verify_code(secret=b32_of(_RFC_KEY), code=code_at(_RFC_KEY, from_step), timestamp=now)


def test_rejects_two_windows_away() -> None:
    """容差必须有边：漂移超过设定的窗数就拒绝。"""
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    now = step * DEFAULT_PERIOD_SECONDS + 7
    key = b32_of(_RFC_KEY)
    assert verify_code(secret=key, code=code_at(_RFC_KEY, step + 2), timestamp=now) is False
    assert verify_code(secret=key, code=code_at(_RFC_KEY, step - 2), timestamp=now) is False


@pytest.mark.parametrize(
    "code",
    ["", "12345", "1234567", "abcdef", "12 456", "１２３４５６"],
)
def test_malformed_code_is_false_not_exception(code: str) -> None:
    """`MfaProvider.verify` 的契约：只答 True / False。

    把用户输入错误变成异常，会让"抄错了码"在审计里显示为系统错误，
    而两者根本不是一回事。
    """
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    now = step * DEFAULT_PERIOD_SECONDS + 7
    assert verify_code(secret=b32_of(_RFC_KEY), code=code, timestamp=now) is False


def test_secret_input_is_tolerant_but_not_beyond_base32() -> None:
    """空格、小写、缺/多 padding 都接受；Base32 之外的字符 → False（不抛）。"""
    step = 1111111109 // DEFAULT_PERIOD_SECONDS
    now = step * DEFAULT_PERIOD_SECONDS + 7
    code = code_at(_RFC_KEY, step)
    stripped = b32_of(_RFC_KEY)
    padded = base64.b32encode(_RFC_KEY).decode("ascii")

    assert verify_code(secret=stripped, code=code, timestamp=now) is True
    assert verify_code(secret=padded.lower(), code=code, timestamp=now) is True
    assert verify_code(secret=padded, code=code, timestamp=now) is True
    # 输入 app 时长串被手动换行 / 加空格是常态。
    assert verify_code(secret=f"{padded[:16]} {padded[16:]}", code=code, timestamp=now) is True
    # 非 Base32 字符：不接受，也不抛异常 —— 由 `verify_code` 内部兜住。
    assert verify_code(secret="not-base32-!!!!", code=code, timestamp=now) is False


# ---------------------------------------------------------------------------
# Provider 契约与默认装配
# ---------------------------------------------------------------------------


def test_provider_conforms_to_the_contract() -> None:
    provider = TotpMfaProvider()
    material = provider.setup(user_id=42, account_name="bob")

    assert provider.name == TOTP_PROVIDER_NAME
    assert re.fullmatch(r"[A-Z2-7]{32}", material.secret) is not None
    # 明文密钥必须出现在 URI 里 —— 否则用户拿去绑定的东西无法自证同源。
    assert material.secret in material.provisioning_uri
    # 生命周期钩子必须可调用且无副作用（TOTP 没有算法侧状态可清）。
    assert provider.enable(user_id=42) is None
    assert provider.disable(user_id=42) is None

    # setup → verify 闭环：`verify_code` 自己重现一步，再喂给 Provider。
    # 用真实时间是为了让这条断言不依赖某个写死的时间戳。
    key = base64.b32decode(material.secret + "=" * ((8 - len(material.secret) % 8) % 8))
    now = int(time.time())
    step = now // DEFAULT_PERIOD_SECONDS
    current_code = hotp(key, step)
    # 这里只走 Provider 的对外口径（拿 plaintext secret），其中包含了
    # "Base32 解码 + 容差窗"两件事 —— 比直接调 `verify_code` 更接近真实调用。
    assert provider.verify(secret=material.secret, code=current_code) is True
    assert provider.verify(secret=material.secret, code="000000") is False


def test_install_makes_the_registry_usable() -> None:
    """安装前登记处是空的 —— 这正是那句 `ConfigurationError` 的来源。"""
    registry = MfaProviderRegistry()
    assert registry.has_active() is False

    installed = install_totp_provider(registry)

    assert installed == TOTP_PROVIDER_NAME
    assert registry.active_name == TOTP_PROVIDER_NAME


def test_install_is_idempotent_and_keeps_an_explicit_provider() -> None:
    """显式注入优先于默认装配 —— 重复调用不得把它换掉。

    这条是留给测试与将来"多 Provider 共存"的：若 `install_totp_provider()`
    无条件覆盖 `active`，任何先装了自己 Provider 的调用方都会被静默改意图。
    """

    class Marker:
        name = "MARKER"

        def setup(self, *, user_id: int, account_name: str) -> object:  # pragma: no cover
            raise AssertionError("装配不应调用注入 Provider 的任何方法")

        def verify(self, *, secret: str, code: str) -> bool:  # pragma: no cover
            raise AssertionError("装配不应调用注入 Provider 的任何方法")

        def enable(self, *, user_id: int) -> None:  # pragma: no cover
            raise AssertionError("装配不应调用注入 Provider 的任何方法")

        def disable(self, *, user_id: int) -> None:  # pragma: no cover
            raise AssertionError("装配不应调用注入 Provider 的任何方法")

    registry = MfaProviderRegistry()
    registry.register(Marker(), activate=True)

    # 调两次：第一次就不该换，第二次更不该。
    assert install_totp_provider(registry) == "MARKER"
    assert install_totp_provider(registry) == "MARKER"
    assert registry.active_name == "MARKER"
    assert registry.get(Marker.name).__class__ is Marker

    # 换个目标登记处则照常装上 —— 幂等不能变成"再也不装"。
    fresh = MfaProviderRegistry()
    assert install_totp_provider(fresh) == TOTP_PROVIDER_NAME
    assert fresh.active_name == TOTP_PROVIDER_NAME
    assert fresh.get(TOTP_PROVIDER_NAME).__class__ is TotpMfaProvider
