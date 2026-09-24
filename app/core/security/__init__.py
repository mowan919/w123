"""安全原语。

交付记录
-------
- Phase 2：密码策略与 argon2id 哈希（`password`）。
- Phase 4：令牌生成 / 哈希 / Bearer 解析（`token`）、设备粗分类（`device`）。
  DD-02 已冻结为**不透明令牌 + 有状态 Session**，
  因此本包中**没有**签名 / 验签 / JWT 相关实现 —— 那是被明确否决的方案。

密码与令牌的哈希口径不同（刻意如此）
----------------------------------
| 对象 | 算法 | 理由 |
|---|---|---|
| 口令 | argon2id（慢、带盐） | 熵低，需抵抗字典枚举 |
| 令牌 | SHA-256（快、无盐） | 256-bit 均匀随机，枚举不可行；且必须能按哈希索引查找 |

详见 `app.core.security.token` 模块说明。
"""

from __future__ import annotations

from app.core.security.device import describe_device
from app.core.security.password import (
    LOCKOUT_DURATION,
    MAX_FAILED_LOGIN_ATTEMPTS,
    PASSWORD_HISTORY_SIZE,
    PASSWORD_MAX_AGE,
    PASSWORD_MAX_AGE_DAYS,
    PASSWORD_MIN_LENGTH,
    PasswordHasher,
    PasswordPolicyViolation,
    get_password_hasher,
    is_password_expired,
    validate_password_policy,
)
from app.core.security.token import (
    ACCESS_TOKEN_TTL,
    BEARER_SCHEME,
    REFRESH_TOKEN_TTL,
    TOKEN_ENTROPY_BYTES,
    TOKEN_HASH_LENGTH,
    extract_bearer_token,
    generate_token,
    hash_token,
    is_well_formed_token,
)

__all__ = [
    "ACCESS_TOKEN_TTL",
    "BEARER_SCHEME",
    "LOCKOUT_DURATION",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "PASSWORD_HISTORY_SIZE",
    "PASSWORD_MAX_AGE",
    "PASSWORD_MAX_AGE_DAYS",
    "PASSWORD_MIN_LENGTH",
    "REFRESH_TOKEN_TTL",
    "TOKEN_ENTROPY_BYTES",
    "TOKEN_HASH_LENGTH",
    "PasswordHasher",
    "PasswordPolicyViolation",
    "describe_device",
    "extract_bearer_token",
    "generate_token",
    "get_password_hasher",
    "hash_token",
    "is_password_expired",
    "is_well_formed_token",
    "validate_password_policy",
]
