"""TOTP（RFC 6238）**纯算法**实现。

为什么单独一个文件、且不碰任何框架
----------------------------------
分层上有两种"算法"：一种是业务编排（谁要验、验几次、失败几次锁定），
另一种是数学。后者不依赖数据库、不依赖配置、不依赖请求上下文 ——
把它和前者混在一起，唯一的结果是"要验证正确性必须先准备一个会话"。

这里只提供无状态函数，因此测试可以直接用 **RFC 6238 附录 B 的测试向量**
逐条钉住；那些向量是跨实现公认的，比任何自造用例都可靠。

为什么不引第三方库：本项目确实严禁自造高风险件（自增 ID、自己写加密），
但 TOTP 是公开标准，实现只需几十行且能被公开向量验证；引 `pyotp`
这类依赖只是把一个可验证的小盒子换成另一个不透明的小盒子，还多一份
供应链与依赖锁定成本。这里的自造是刻意的、且**可**验证的。

安全性说明
----------
- 生成随机secret 走 `secrets`（CSPRNG），不用 `random`；
- 比对一律 `hmac.compare_digest`（常数时间），避免按字节提前返回
  泄露"前几位对了"；
- 允许 ±1 个时间窗（默认 30s），这是 RFC 6238 §5.2 推荐的容差：
  手机时钟与其说是"不准"，不如说是"输入瞬间刚好跨过窗口边界"；
- **不做重放保护**（记"上一次用到的 counter"）—— `verify` 的签名里没有
  用户身份与存储，它必须保持纯函数。若将来要防同码重放，
  应在服务层记录 `verified_at` 与最近用过的 counter。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Final
from urllib.parse import quote, urlencode

__all__ = [
    "DEFAULT_DIGITS",
    "DEFAULT_DRIFT_STEPS",
    "DEFAULT_PERIOD_SECONDS",
    "SECRET_BYTES",
    "TOTP_ALGORITHM",
    "generate_secret",
    "hotp",
    "provisioning_uri",
    "verify_code",
]

#: 时间步长（RFC 6238 §4.2 推荐的 X = 30 秒）。
DEFAULT_PERIOD_SECONDS: Final[int] = 30
#: 动态码位数。6 位是验证器 App 的事实标准，8 位只用于少数场景。
DEFAULT_DIGITS: Final[int] = 6
#: 允许的**前后**时区偏移（单位：时间步）。
DEFAULT_DRIFT_STEPS: Final[int] = 1
#: 密钥长度 20 字节 = 160 bit。
#:
#: RFC 4226 §4 要求 key 至少 128 bit，并建议与 HMAC 输出等长；
#: SHA-1 输出 160 bit，因此 20 字节是"刚好用满"的选择 ——
#: 更长不会更安全（HMAC 会先做 key 处理），只会让 Base32 串更长更难抄写。
SECRET_BYTES: Final[int] = 20

#: HMAC 摘要算法。
#:
#: RFC 6238 定义了 SHA-1 / SHA-256 / SHA-512 三档。选 SHA-1 **不是**因为它安全，
#: 而是因为它是所有验证器 App 的默认档：Google Authenticator 完全忽略 URI 里的
#: `algorithm` 参数、永远按 SHA-1 计算，多数客户端也不支持别的组合。
#: 在这里选"更强的 SHA-256"的实际后果是**用户绑不上**，比摘要长度本身更糟 ——
#: TOTP 的安全性来自短时效 + 一次性，不来自摘要宽度。
TOTP_ALGORITHM: Final[str] = "sha1"


def generate_secret() -> str:
    """生成一个全新的随机密钥（Base32，**不带 padding**）。

    去掉 `=` 是 `otpauth://` 的通行做法：它只会被放进 URL 与二维码，
    而 Base32 长度是 8 的倍数时生成的 padding 会被解析器视为噪声。
    """
    raw = secrets.token_bytes(SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    """把用户侧保存的 Base32 串还原成字节。

    宽容三件事（都是实践中真会遇到的）：空格、小写、`=` padding 缺失。
    三者都**不改变**语义，因此宽容是安全的；反过来，宽容不该扩展到
    "Base32 之外的字符" —— 那由 `base64.b32decode` 抛异常处理。
    """
    normalized = secret.strip().replace(" ", "").upper()
    if len(normalized) % 8 != 0:
        normalized += "=" * (8 - len(normalized) % 8)
    return base64.b32decode(normalized, casefold=True)


def hotp(key: bytes, counter: int, *, digits: int = DEFAULT_DIGITS) -> str:
    """HOTP（RFC 4226）：由密钥与计数器算出 `digits` 位动态码。

    `counter` 是**整数**而不是时间戳 —— RFC 6238 的 TOTP 就是
    "HOTP + 由时间算出的计数器"，这样分层可以让 RFC 4226 的测试向量
    （也是 HOTP 的）在本层直接复用。
    """
    message = counter.to_bytes(8, byteorder="big")
    digest = hmac.new(key, message, getattr(hashlib, TOTP_ALGORITHM)).digest()
    # RFC 4226 §5.3 的动态截断（dynamic truncation）：
    # 用摘要最后一个字节的低 4 位作偏移量，从该处取 4 字节，
    # 掐掉最高位（避免有符号整数的实现差异），最后对 10^digits 取模。
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], byteorder="big") & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def provisioning_uri(*, secret: str, account_name: str, issuer: str = "VCTN") -> str:
    """构造 `otpauth://` 配网 URI（供验证器 App 扫码/粘贴）。

    `issuer` 同时出现在路径前缀与 query 里：前者用于扫码时显示账户归属，
    后者才是 Google Authenticator 实际读取的字段（它忽略第一个）。
    少了 query 那份，用户绑出来的是一个没有名字的条目。
    """
    label = quote(f"{issuer}:{account_name}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DEFAULT_DIGITS,
            "period": DEFAULT_PERIOD_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def verify_code(
    *,
    secret: str,
    code: str,
    timestamp: int | None = None,
    period: int = DEFAULT_PERIOD_SECONDS,
    drift_steps: int = DEFAULT_DRIFT_STEPS,
) -> bool:
    """校验动态码；任何格式错误都返回 False，**不抛异常**。

    为什么不抛异常：`MfaProvider.verify` 的契约就是"只回答 True / False"。
    把 Bad Base32 这种数据错误抛出去，会让**用户的输入**变成**系统异常**，
    审计里就会出现一条本不该有的 500 级事件，而真实差别只是
    "这个人把密钥抄错了"。

    为什么不做"早 return"：先算出所有候选值再比对。
    哪怕第一个就命中也要继续算完（`compare_digest` + 累加），
    否则响应时间会随"偏差几个窗"线性变化，可被用来逐个窗爆破。
    """
    normalized = code.strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != DEFAULT_DIGITS:
        return False

    try:
        key = _decode_secret(secret)
    except Exception:
        return False

    now = int(time.time()) if timestamp is None else timestamp
    current_step = now // period

    matched = False
    candidate = normalized.encode("utf-8")
    for step in range(current_step - drift_steps, current_step + drift_steps + 1):
        # `matched |= ...` 而不是 `or`：保证每个窗都被算过，响应时间恒定。
        #
        # 用**字节**比对而不是字符串：`compare_digest` 遇到非 ASCII 字符会抛
        # `TypeError`（它按 ASCII 编码）。而全角数字 `１２３４５６` 是能
        # 通过 `str.isdigit()` 的 —— 中文输入法常态，用户在手机上粘一个
        # 全角码出来并不稀奇。那种输入必须落到"验证不通过"，
        # 绝不能变成 500。
        matched |= hmac.compare_digest(hotp(key, step).encode("ascii"), candidate)
    return matched
