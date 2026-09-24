"""密码策略与哈希。

Frozen 依据
-----------
Spec `00 §2`（= `15 D-009`）密码策略：
    最少 12 个字符；必须包含大写、小写、数字、特殊字符；
    最近 5 个密码不可重复；90 天必须更换；
    连续 5 次失败锁定 30 分钟；管理员重置后首次登录必须改密。

Spec `10 §4`：不得记录 password / password hash / MFA secret / token 明文。
Spec `07 §6`：Refresh Token 不保存明文（同理，密码只保存哈希）。

技术决策（人类已裁定）
--------------------
哈希算法 = **argon2id**（`16 §34` 未列此项，经人类明确指定）。
参数为 argon2-cffi 的默认安全档位，可由环境变量覆盖以便日后调优。

本模块是密码相关的**唯一**实现点；业务代码不得自行 hash 或校验策略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# ---- 策略常量（Frozen，来自 Spec 00 §2） ----
PASSWORD_MIN_LENGTH = 12
PASSWORD_HISTORY_SIZE = 5
PASSWORD_MAX_AGE_DAYS = 90
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 30

#: 口令最长寿命（与 `PASSWORD_MAX_AGE_DAYS` 同源的 timedelta 形式，
#: 供各调用方复用，避免各处 `timedelta(days=...)` 重复出现）。
PASSWORD_MAX_AGE = timedelta(days=PASSWORD_MAX_AGE_DAYS)

#: 连续失败达到阈值后的锁定时长。
LOCKOUT_DURATION = timedelta(minutes=LOCKOUT_MINUTES)

_UPPERCASE = re.compile(r"[A-Z]")
_LOWERCASE = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")


@dataclass(frozen=True, slots=True)
class PasswordPolicyViolation:
    """一条策略违规。`code` 用于前端映射文案，`message` 为英文默认文案。"""

    code: str
    message: str


class PasswordHasher:
    """argon2id 密码哈希器。

    只暴露 `hash` / `verify` / `needs_rehash`，不暴露底层参数细节，
    以免调用方依赖具体算法（便于日后替换）。
    """

    def __init__(self) -> None:
        self._hasher = _Argon2Hasher()

    def hash(self, password: str) -> str:
        """生成密码哈希（含随机盐）。"""
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        """校验密码是否正确。

        任何校验异常（哈希格式非法、算法不匹配等）一律返回 False，
        不向调用方泄漏内部细节（Spec `10 §9`）。
        """
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False
        except Exception:  # pragma: no cover - 防御性
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """是否需要按当前参数重新哈希（参数升级后使用）。"""
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError, VerificationError:
            return True


#: 进程级单例（argon2 的 PasswordHasher 无状态且线程安全）
_password_hasher = PasswordHasher()


def get_password_hasher() -> PasswordHasher:
    """返回进程级密码哈希器。"""
    return _password_hasher


def is_password_expired(password_changed_at: datetime | None, *, now: datetime) -> bool:
    """口令是否已超过 90 天必须更换的期限（Spec `00 §2`）。

    `password_changed_at` 为 None 时返回 **True**（视为已过期）：
    我们无法证明该口令在 90 天内被设置过。按本项目一贯的 fail-closed 取向
    （`11 §5`"宁可拒绝，也不放行"），此时应要求用户改密，
    而不是假定它是新的 —— 后者会让"从未记录改密时间的账号"永久免于轮换。

    到期后的处理**不是**拒绝登录，而是强制改密（DD-02 P8 已裁定），
    因此本函数只回答"是否到期"，不决定登录是否放行。
    """
    if password_changed_at is None:
        return True
    return now - password_changed_at >= PASSWORD_MAX_AGE


def validate_password_policy(password: str) -> list[PasswordPolicyViolation]:
    """按 Spec `00 §2` 校验密码复杂度。

    Returns:
        违规列表；为空表示通过。

    注意：本函数**不**校验"最近 5 个密码不可重复"（需要历史哈希），
    该部分由 `UserService` 调用 `PasswordHasher.verify` 完成。
    """
    violations: list[PasswordPolicyViolation] = []

    if len(password) < PASSWORD_MIN_LENGTH:
        violations.append(
            PasswordPolicyViolation(
                code="PASSWORD_TOO_SHORT",
                message=f"password must be at least {PASSWORD_MIN_LENGTH} characters",
            )
        )
    if not _UPPERCASE.search(password):
        violations.append(
            PasswordPolicyViolation(
                code="PASSWORD_MISSING_UPPERCASE",
                message="password must contain an uppercase letter",
            )
        )
    if not _LOWERCASE.search(password):
        violations.append(
            PasswordPolicyViolation(
                code="PASSWORD_MISSING_LOWERCASE",
                message="password must contain a lowercase letter",
            )
        )
    if not _DIGIT.search(password):
        violations.append(
            PasswordPolicyViolation(
                code="PASSWORD_MISSING_DIGIT",
                message="password must contain a digit",
            )
        )
    # 特殊字符 = 非字母数字字符（Spec 00 §2 未进一步限定字符集）
    if not any(not char.isalnum() for char in password):
        violations.append(
            PasswordPolicyViolation(
                code="PASSWORD_MISSING_SPECIAL",
                message="password must contain a special character",
            )
        )

    return violations


__all__ = [
    "LOCKOUT_DURATION",
    "LOCKOUT_MINUTES",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "PASSWORD_HISTORY_SIZE",
    "PASSWORD_MAX_AGE",
    "PASSWORD_MAX_AGE_DAYS",
    "PASSWORD_MIN_LENGTH",
    "PasswordHasher",
    "PasswordPolicyViolation",
    "get_password_hasher",
    "is_password_expired",
    "validate_password_policy",
]
