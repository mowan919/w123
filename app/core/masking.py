"""敏感信息脱敏。

Frozen（Spec 00 §8 / 06 §4 / 15 D-012 / AGENTS.md §8）：
    phone       → 138****1234
    email       → abc***@example.com
    token       → 只保留前 6 个字符
    password    → 绝不记录
    MFA Secret  → 绝不记录

本模块是日志与审计链路的唯一脱敏入口。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MASKED = "***"
NEVER_LOG = "<redacted>"

#: 这些键的值**永不出现在日志中**（Spec 00 §8：password / MFA Secret 绝不记录）。
#: 同时覆盖 13 §2 定义的密钥类配置。
NEVER_LOG_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "new_password",
        "old_password",
        "confirm_password",
        "password_hash",
        "hashed_password",
        "password_digest",
        "mfa_secret",
        "totp_secret",
        "otp_secret",
        "secret",
        "client_secret",
        "signing_secret",
        "encryption_key",
        "mfa_encryption_key",
        "private_key",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "cookie",
        "set-cookie",
        "session_token",
        "secret_key",
    }
)

#: 这些键做部分脱敏后可以记录。
_PARTIAL_MASK_KEYS: frozenset[str] = frozenset({"phone", "mobile", "email", "token"})

_SENSITIVE_CONTAINER_KEYS: frozenset[str] = frozenset(
    {
        "headers",
        "request_headers",
        "response_headers",
        "cookies",
        "body",
        "request_body",
        "response_body",
        "payload",
        "data",
        "params",
        "query",
    }
)


def mask_phone(value: str) -> str:
    """手机号脱敏：138****1234。"""
    if not value:
        return MASKED
    digits = value.strip()
    if len(digits) < 7:
        return MASKED
    return f"{digits[:3]}****{digits[-4:]}"


def mask_email(value: str) -> str:
    """邮箱脱敏：abc***@example.com。"""
    if not value or "@" not in value:
        return MASKED
    local, _, domain = value.partition("@")
    return f"{local}{MASKED}@{domain}"


def mask_token(value: str) -> str:
    """Token 脱敏：只保留前 6 个字符（Spec 00 §8）。"""
    if not value:
        return MASKED
    return value[:6]


def mask_value(key: str, value: Any) -> Any:
    """按 key 语义对单个值脱敏。"""
    lowered = key.lower()
    if lowered in NEVER_LOG_KEYS:
        return NEVER_LOG
    if not isinstance(value, str):
        return value
    if lowered in {"phone", "mobile"}:
        return mask_phone(value)
    if lowered == "email":
        return mask_email(value)
    if lowered == "token":
        return mask_token(value)
    return value


def scrub_field(key: str, value: Any) -> Any:
    """按字段名脱敏单个字段值（标量或容器）。

    这是日志链路应使用的入口：`scrub()` 只能按**容器内的键名**脱敏，
    直接对裸标量调用 `scrub("plaintext")` 无法得知它属于 password 字段，
    因此必须经由本函数保留键名语义。
    """
    lowered = key.lower()
    if lowered in NEVER_LOG_KEYS:
        return NEVER_LOG
    if lowered in _SENSITIVE_CONTAINER_KEYS:
        return f"<{type(value).__name__} scrubbed>"
    if isinstance(value, (Mapping, list, tuple, set)):
        return scrub(value)
    return mask_value(key, value)


def scrub(value: Any, *, _depth: int = 0) -> Any:
    """递归脱敏任意结构，返回可安全记录的新对象。

    - 命中 NEVER_LOG_KEYS 的键 → 值替换为 `<redacted>`；
    - phone / email / token → 按 Frozen 规则部分脱敏；
    - 容器键（headers / body / payload ...）→ 整体标记，避免间接泄漏；
    - 最大递归深度 6，防止自引用结构导致无限递归。
    """
    if _depth > 6:
        return "<max-depth>"

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered in NEVER_LOG_KEYS:
                cleaned[key] = NEVER_LOG
            elif lowered in _SENSITIVE_CONTAINER_KEYS:
                # 容器整体不外泄原文，仅保留类型提示
                cleaned[key] = f"<{type(raw_value).__name__} scrubbed>"
            elif isinstance(raw_value, (Mapping, list, tuple, set)):
                cleaned[key] = scrub(raw_value, _depth=_depth + 1)
            else:
                cleaned[key] = mask_value(key, raw_value)
        return cleaned

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [scrub(item, _depth=_depth + 1) for item in value]

    return value
