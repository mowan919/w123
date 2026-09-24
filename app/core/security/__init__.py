"""安全原语。

Phase 2 交付密码策略与 argon2id 哈希。
Token 签发 / 校验属后续 Phase（`16 §34#2` Token 生命周期未冻结）。
"""

from __future__ import annotations

from app.core.security.password import (
    PASSWORD_HISTORY_SIZE,
    PASSWORD_MAX_AGE_DAYS,
    PASSWORD_MIN_LENGTH,
    PasswordHasher,
    PasswordPolicyViolation,
    get_password_hasher,
    validate_password_policy,
)

__all__ = [
    "PASSWORD_HISTORY_SIZE",
    "PASSWORD_MAX_AGE_DAYS",
    "PASSWORD_MIN_LENGTH",
    "PasswordHasher",
    "PasswordPolicyViolation",
    "get_password_hasher",
    "validate_password_policy",
]
