"""MFA Secret 的 AEAD 加解密（DD-22 方案 A / Spec `04 §6`「Secret 必须加密保存」）。

为什么必须是**可逆加密**而不是哈希
----------------------------------
`04 §6` 要求 Secret 加密保存，而 MFA 的算法本质决定了密文必须能被还原：
动态码类凭据需要用原始 secret **重算** `code` 来完成校验。
`argon2id` 这类单向哈希在这里是**结构性不可用**的
（`app/core/security/password.py` 用它保护口令，口令只需比对、无需还原）。

密文格式
--------
```text
v1.<base64url(nonce ‖ ciphertext ‖ tag)>
```

带版本前缀的目的：将来更换算法 / 更换密钥时，可以**逐行渐进迁移**
（读旧格式、写新格式），而不是停机做一次全量重加密。
这是为了不与尚未冻结的 Secret Manager（DD-09）互相绑架 ——
本模块不实现密钥轮换，但保证未来加轮换是**纯增量**改动。

为什么 AAD 要绑定实体身份（这是最关键的一条）
--------------------------------------------
AEAD 保证的是"这一段密文没被改过"，但不保证"它属于这一行"。
如果没有 AAD，攻击者（或有库写权限的运维）把 **A 用户的密文复制到 B 用户的行**上时，
系统会**用 A 的 secret 正常验证 B 的登录**——并且日志里一切正常，看不出异常。

因此调用方必须把 `(user_id, provider)` 编进 AAD。这里刻意**不**在模块内部
替调用方拼装 AAD：绑定什么、绑定几个维度是由使用者决定的策略，
写死会把一个"谁拥有这段密文"的判断藏进加密原语里，反而更难审查。

为什么用 `MFA_ENCRYPTION_KEY` 而不是 `ENCRYPTION_KEY`
----------------------------------------------------
**域分离**。`13 §2` 本就把二者列为两个独立配置项；
一把密钥服务多种用途时，任一用途的密文被解出都会污染其余用途。
`ENCRYPTION_KEY` 目前没有消费者，留给后续 Phase，本模块不使用它。

fail-closed 约定
----------------
密钥缺失 / 长度不符 / 密文格式错误 / 解密失败，全部走异常路径。
**绝不**返回空字符串、**绝不**回落为明文保存、**绝不**回落为"当作未启用"。
后者尤其危险：它会把一个损坏的记录变成一次**认证绕过**。
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.errors import ConfigurationError

#: 密文版本前缀。改算法时递增，旧密文仍可读。
CIPHERTEXT_VERSION = "v1"

#: GCM 推荐 nonce 长度（12 字节 / 96 bit）。
NONCE_BYTES = 12

#: AES-256 要求 32 字节密钥。
KEY_BYTES = 32

_DECODED_KEY_CACHE_MAX = 8

#: 版本前缀与密文体之间的分隔符。选 `.` 是因为它不出现在标准 base64 字符集里，
#: 解析时不存在歧义。
_SEPARATOR = "."


class SecretBoxError(Exception):
    """AEAD 加解密失败的统一基类。

    刻意**不**继承 `AppError`：加密层的失败不应直接映射为一个 HTTP 响应，
    而应由调用方（MFA 服务）决定语义——是记为 `MFA_FAILURE`，还是配置缺失。
    """


def _decode_key(raw: str) -> bytes:
    """把配置项里的密钥字符串解成 32 字节密钥。

    只接受 **标准 base64**（含填充）。刻意不接受"裸字符串"或"十六进制"：
    多种格式并存会让一类非常隐蔽的故障成为可能——运算符换了密钥格式，
    解密结果不同但都不报错，直到某次校验才莫名其妙失败。
    单一格式是可以用一句命令生成、也可以用一句命令校验的。
    """
    candidate = raw.strip()
    if not candidate:
        raise SecretBoxError("MFA 加密密钥为空")
    try:
        key = base64.b64decode(candidate, validate=True)
    except (binascii.Error, ValueError) as exc:
        # binascii.Error 是 ValueError 的子类；两者都列出是为了不依赖这一继承关系。
        raise SecretBoxError("MFA 加密密钥不是合法的 base64") from exc
    if len(key) != KEY_BYTES:
        raise SecretBoxError(f"MFA 加密密钥解出 {len(key)} 字节，应为 {KEY_BYTES} 字节（AES-256）")
    return key


class MfaSecretBox:
    """MFA Secret 的加解密器（AES-256-GCM）。

    实例**不可变**、无状态（除已解析的密钥字节外），因此可以在进程内长期持有。
    """

    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        self._key = key

    @classmethod
    def from_configured_key(cls, raw: str | None = None) -> MfaSecretBox:
        """从配置构造。密钥缺失或非法时抛 `SecretBoxError`（fail-closed）。

        Args:
            raw: 明文密钥来源；缺省取 `settings.mfa_encryption_key`。

        """
        secret = settings.mfa_encryption_key.get_secret_value() if raw is None else raw
        return cls(_decode_key(secret))

    def encrypt(self, *, plaintext: str, aad: str) -> str:
        """加密。返回带版本前缀的密文串。

        Args:
            plaintext: 明文 Secret。
            aad: 关联数据（调用方须编入 `user_id` / `provider` 等身份维度）。

        """
        # 每次加密都重取随机 nonce（同一 key 复用 nonce 会直接泄漏明文异或）。
        # 用 os.urandom 而非某个库工具方法：这是随机性来源最没有解释余地的一种写法。
        nonce = os.urandom(NONCE_BYTES)
        box = AESGCM(self._key)
        # `AESGCM.encrypt` 只回 ct‖tag，**不含** nonce —— nonce 必须自己随文保存。
        # 这里把它拼在密文前面，与 decrypt 的切片严格对应。
        sealed = box.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        blob = nonce + sealed
        return _SEPARATOR.join((CIPHERTEXT_VERSION, base64.urlsafe_b64encode(blob).decode("ascii")))

    def decrypt(self, *, ciphertext: str, aad: str) -> str:
        """解密。任何不符（版本未知 / 格式错 / 标签校验失败）都抛 `SecretBoxError`。

        刻意**不**区分失败原因并返回给调用方：告诉对方"这次是密文被改过"
        本身就是一个可用于构造 oracle 的信息位。
        具体原因应写服务端日志，不进 API 响应。
        """
        version, _, payload = ciphertext.partition(_SEPARATOR)
        if version != CIPHERTEXT_VERSION or not payload:
            raise SecretBoxError("密文格式不匹配 or 版本不受支持")
        try:
            blob = base64.urlsafe_b64decode(payload)
        except (binascii.Error, ValueError) as exc:
            raise SecretBoxError("密文不是合法的 base64") from exc
        if len(blob) <= NONCE_BYTES:
            raise SecretBoxError("密文长度不足：连 nonce 都不完整")
        nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, sealed, aad.encode("utf-8"))
        except InvalidTag as exc:
            # 标签校验失败 = 密文被篡改，**或** AAD 与加密时不一致。
            # 后者正是"密文被搬到另一行"的确证 —— 这是一次真实的完整性违规，
            # 必须让调用方把它当事件处理，而不是当作数据缺失。
            raise SecretBoxError("密文完整性校验失败（被篡改或 AAD 不匹配）") from exc
        return plaintext.decode("utf-8")


def build_secret_box() -> MfaSecretBox:
    """构造 AES-256-GCM 加解密器；配置缺失时抛 `ConfigurationError`。

    为什么不返回 `None` 让调用方"降级"：一旦存在降级路径，
    "密钥没配好"就会表现为"系统照常运行"，而 Spec `04 §6` 要求 Secret 必须加密。
    宁可在第一次触碰 Secret 时明确失败。
    """
    try:
        return MfaSecretBox.from_configured_key()
    except SecretBoxError as exc:
        # 文案不含密钥内容与任何内部细节，可安全返回给运维。
        raise ConfigurationError(
            "MFA Secret 加密密钥不可用：请检查 MFA_ENCRYPTION_KEY 配置"
            f"（必须为 {KEY_BYTES} 字节的标准 base64 编码）。"
        ) from exc


__all__ = [
    "CIPHERTEXT_VERSION",
    "KEY_BYTES",
    "NONCE_BYTES",
    "MfaSecretBox",
    "SecretBoxError",
    "build_secret_box",
]
