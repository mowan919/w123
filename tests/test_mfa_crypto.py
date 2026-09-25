"""MFA Secret 的 AEAD 加解密测试（DD-22 方案 A / 验收裁判 `005-mfa.md` 第 3、4 项）。

本文件钉住的性质
---------------
| 性质 | 依据 | 为什么必须是硬约束 |
|---|---|---|
| 可逆（能还原出原 secret） | `04 §6` | 动态码校验必须用原始 secret 重算，单向哈希结构性不可用 |
| 密文带版本前缀 | DD-22 P1 | 换算法/换密钥时可逐行迁移，不需停机全量重加密 |
| 每次加密 nonce 不同 | AES-GCM 的安全前提 | 同 key 复用 nonce 直接泄漏明文异或 |
| AAD 绑定身份 | DD-22 P3 | 否则 A 的密文搬到 B 的行上会**用 A 的 secret 验证 B 的登录**且无迹可循 |
| 篡改被拒 | AEAD 定义 | 任何一位改动都必须被发现，不能静默降级 |
| 密钥缺失/非法一律失败 | `04 §6` + `13 §2` | 回落为明文或"当作未启用"都会变成认证绕过 |
"""

from __future__ import annotations

import base64
import hashlib
import os

import pytest

from app.core.errors import ConfigurationError
from app.core.security.aead import (
    CIPHERTEXT_VERSION,
    KEY_BYTES,
    NONCE_BYTES,
    MfaSecretBox,
    SecretBoxError,
    build_secret_box,
)

pytestmark = pytest.mark.unit

#: 一条固定的 32 字节测试密钥（与 conftest 注入的**不同**，
#: 用于验证"换一把密钥就解不开"这一方向，而不依赖全局配置）。
KEY_A = base64.b64encode(hashlib.sha256(b"test-key-a").digest()).decode()
KEY_B = base64.b64encode(hashlib.sha256(b"test-key-b").digest()).decode()

SECRET = "JBSWY3DPEHPK3PXP"
AAD = "52101:TOTP"


def _box(key: str = KEY_A) -> MfaSecretBox:
    return MfaSecretBox.from_configured_key(key)


class TestRoundTrip:
    """加密 → 解密必须还原出完全相同的明文。"""

    def test_roundtrip_ascii(self) -> None:
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad=AAD)
        assert box.decrypt(ciphertext=ciphertext, aad=AAD) == SECRET

    def test_roundtrip_unicode(self) -> None:
        """secret 的字符集由 Provider 决定，本层不得假设它一定是 ASCII。"""
        box = _box()
        plaintext = "密钥·测试-🔐"
        ciphertext = box.encrypt(plaintext=plaintext, aad=AAD)
        assert box.decrypt(ciphertext=ciphertext, aad=AAD) == plaintext

    def test_ciphertext_has_version_prefix(self) -> None:
        """版本前缀是"将来能渐进迁移"的唯一依据，必须真的写进密文。"""
        ciphertext = _box().encrypt(plaintext=SECRET, aad=AAD)
        head, separator, payload = ciphertext.partition(".")
        assert head == CIPHERTEXT_VERSION == "v1"
        assert separator == "."
        assert payload

    def test_ciphertext_does_not_contain_plaintext(self) -> None:
        """密文里不得出现明文 —— base64 前先做一次原始字节检查。"""
        ciphertext = _box().encrypt(plaintext=SECRET, aad=AAD)
        raw = base64.urlsafe_b64decode(ciphertext.partition(".")[2])
        assert SECRET.encode("utf-8") not in raw
        assert SECRET not in ciphertext

    def test_nonce_differs_per_call(self) -> None:
        """同一 key + 同一 nonce 复用会直接泄漏明文异或，因此必须每次重取。"""
        box = _box()
        first = box.encrypt(plaintext=SECRET, aad=AAD)
        second = box.encrypt(plaintext=SECRET, aad=AAD)
        assert first != second
        # nonce 位于 blob 头部，两次的前 NONCE_BYTES 字节必须不同。
        raw_a = base64.urlsafe_b64decode(first.partition(".")[2])
        raw_b = base64.urlsafe_b64decode(second.partition(".")[2])
        assert raw_a[:NONCE_BYTES] != raw_b[:NONCE_BYTES]

    def test_blob_is_nonce_plus_sealed(self) -> None:
        """布局必须是 `nonce ‖ ct ‖ tag`：解密端按同一偏移切片，错位即全盘失败。"""
        ciphertext = _box().encrypt(plaintext=SECRET, aad=AAD)
        raw = base64.urlsafe_b64decode(ciphertext.partition(".")[2])
        # 12 字节 nonce + 密文（含 16 字节 GCM tag），因此至少 12 + 长度 + 16。
        assert len(raw) >= NONCE_BYTES + len(SECRET) + 16


class TestAadBinding:
    """DD-22 P3：AAD 必须绑定 `(user_id, provider)`。"""

    def test_wrong_aad_is_rejected(self) -> None:
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad="52101:TOTP")
        with pytest.raises(SecretBoxError):
            box.decrypt(ciphertext=ciphertext, aad="52102:TOTP")

    def test_provider_swap_is_rejected(self) -> None:
        """同一用户的密文换到另一个 Provider 名下同样必须失败。"""
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad="52101:TOTP")
        with pytest.raises(SecretBoxError):
            box.decrypt(ciphertext=ciphertext, aad="52101:WEBAUTHN")

    def test_plaintext_is_not_recoverable_under_wrong_aad(self) -> None:
        """错 AAD 不能"部分成功"—— 必须是异常，不能返回残缺明文。"""
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad="52101:TOTP")
        try:
            box.decrypt(ciphertext=ciphertext, aad="52102:TOTP")
        except SecretBoxError:
            return
        pytest.fail("错 AAD 竟然解密成功：AAD 绑定失效，密文可被搬行复用")


class TestTamperResistance:
    """AEAD 的完整性保证：任何一位改动都必须被发现。"""

    @staticmethod
    def _flip_last_byte(ciphertext: str) -> str:
        version, _, payload = ciphertext.partition(".")
        raw = bytearray(base64.urlsafe_b64decode(payload))
        raw[-1] ^= 0x01
        return f"{version}.{base64.urlsafe_b64encode(bytes(raw)).decode('ascii')}"

    def test_tag_flip_is_rejected(self) -> None:
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad=AAD)
        with pytest.raises(SecretBoxError):
            box.decrypt(ciphertext=self._flip_last_byte(ciphertext), aad=AAD)

    def test_nonce_flip_is_rejected(self) -> None:
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad=AAD)
        version, _, payload = ciphertext.partition(".")
        raw = bytearray(base64.urlsafe_b64decode(payload))
        raw[0] ^= 0x01
        tampered = f"{version}.{base64.urlsafe_b64encode(bytes(raw)).decode('ascii')}"
        with pytest.raises(SecretBoxError):
            box.decrypt(ciphertext=tampered, aad=AAD)


class TestMalformedInput:
    """格式非法一律走异常路径，绝不返回空串或半成品。"""

    def test_unknown_version_is_rejected(self) -> None:
        box = _box()
        ciphertext = box.encrypt(plaintext=SECRET, aad=AAD)
        _, _, payload = ciphertext.partition(".")
        with pytest.raises(SecretBoxError):
            box.decrypt(ciphertext=f"v9.{payload}", aad=AAD)

    def test_missing_separator_is_rejected(self) -> None:
        with pytest.raises(SecretBoxError):
            _box().decrypt(ciphertext=SECRET, aad=AAD)

    def test_bad_base64_is_rejected(self) -> None:
        with pytest.raises(SecretBoxError):
            _box().decrypt(ciphertext="v1.!!!not-base64!!!", aad=AAD)

    def test_truncated_blob_is_rejected(self) -> None:
        """长度不足连 nonce 都不完整时必须明确失败，不能切片出空 nonce。"""
        truncated = base64.urlsafe_b64encode(os.urandom(NONCE_BYTES - 1)).decode("ascii")
        with pytest.raises(SecretBoxError):
            _box().decrypt(ciphertext=f"v1.{truncated}", aad=AAD)


class TestKeyMaterial:
    """密钥来源的品质直接决定整套加密是否成立。"""

    def test_wrong_key_cannot_decrypt(self) -> None:
        """换一把密钥必须解不开 —— 否则"密钥"就不是秘密。"""
        ciphertext = _box(KEY_A).encrypt(plaintext=SECRET, aad=AAD)
        with pytest.raises(SecretBoxError):
            _box(KEY_B).decrypt(ciphertext=ciphertext, aad=AAD)

    @pytest.mark.parametrize(
        ("raw", "reason"),
        [
            ("", "空密钥"),
            ("   ", "仅空白"),
            ("not-base64!!", "非法 base64"),
            (base64.b64encode(os.urandom(16)).decode(), "16 字节（非 AES-256）"),
            (base64.b64encode(os.urandom(31)).decode(), "31 字节"),
            (base64.b64encode(os.urandom(64)).decode(), "64 字节"),
        ],
    )
    def test_bad_key_is_rejected(self, raw: str, reason: str) -> None:
        with pytest.raises(SecretBoxError):
            MfaSecretBox.from_configured_key(raw)

    def test_valid_key_has_expected_length(self) -> None:
        assert len(base64.b64decode(KEY_A)) == KEY_BYTES == 32


class TestBuildSecretBoxFailClosed:
    """`build_secret_box` 是服务层唯一的构造入口，必须 fail-closed。"""

    def test_uses_configured_key(self) -> None:
        """测试环境注入的密钥必须可用（否则所有 Secret 相关验收都无法执行）。"""
        box = build_secret_box()
        ciphertext = box.encrypt(plaintext=SECRET, aad=AAD)
        assert box.decrypt(ciphertext=ciphertext, aad=AAD) == SECRET

    def test_missing_configuration_raises_configuration_error(self, monkeypatch) -> None:
        """密钥缺失时抛的是 `ConfigurationError`（可映射为 HTTP），不是裸异常。"""
        from app.core.config import settings

        monkeypatch.setattr(settings, "mfa_encryption_key", type(settings.mfa_encryption_key)(""))
        with pytest.raises(ConfigurationError, match="MFA Secret 加密密钥不可用"):
            build_secret_box()

    def test_error_message_leaks_no_key_material(self, monkeypatch) -> None:
        """失败文案不得回显密钥内容 —— 异常会被写进日志。"""
        from app.core.config import settings

        monkeypatch.setattr(
            settings,
            "mfa_encryption_key",
            type(settings.mfa_encryption_key)("definitely-not-base64"),
        )
        with pytest.raises(ConfigurationError) as excinfo:
            build_secret_box()
        assert "definitely-not-base64" not in str(excinfo.value)

    def test_secret_box_error_is_not_app_error(self) -> None:
        """加密层的异常不继承 `AppError`：映射为 HTTP 语义由调用方决定。"""
        from app.core.errors import AppError

        assert not issubclass(SecretBoxError, AppError)
