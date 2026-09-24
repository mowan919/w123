"""密码策略与哈希测试（unit）。

对应 Spec `00 §2`（= `15 D-009`）：
    最少 12 位；须含大写 / 小写 / 数字 / 特殊字符；
    argon2id 哈希；哈希不可逆、不可重复使用同一盐。

并覆盖 Spec `10 §4`：verify 在任何非法输入下**返回 False**，
不向调用方泄漏内部异常细节。
"""

from __future__ import annotations

import pytest

from app.core.security.password import (
    PASSWORD_HISTORY_SIZE,
    PASSWORD_MAX_AGE_DAYS,
    PASSWORD_MIN_LENGTH,
    PasswordHasher,
    get_password_hasher,
    validate_password_policy,
)

pytestmark = pytest.mark.unit

#: 一个满足全部四类字符且长度合规的强口令。
STRONG_PASSWORD = "Str0ng-Passw0rd!x"


def _codes(password: str) -> set[str]:
    return {violation.code for violation in validate_password_policy(password)}


class TestPasswordPolicy:
    def test_strong_password_passes(self) -> None:
        assert validate_password_policy(STRONG_PASSWORD) == []

    def test_exactly_min_length_boundary_passes(self) -> None:
        # 12 位、四类字符齐全 → 通过
        assert len("Abcdefgh1!xy") == PASSWORD_MIN_LENGTH
        assert validate_password_policy("Abcdefgh1!xy") == []

    def test_one_below_min_length_is_rejected(self) -> None:
        assert "PASSWORD_TOO_SHORT" in _codes("Abcdefg1!xy")  # 11 位

    def test_missing_uppercase(self) -> None:
        assert "PASSWORD_MISSING_UPPERCASE" in _codes("abcdefgh1!xyz")

    def test_missing_lowercase(self) -> None:
        assert "PASSWORD_MISSING_LOWERCASE" in _codes("ABCDEFGH1!XYZ")

    def test_missing_digit(self) -> None:
        assert "PASSWORD_MISSING_DIGIT" in _codes("Abcdefgh!!xyz")

    def test_missing_special_character(self) -> None:
        assert "PASSWORD_MISSING_SPECIAL" in _codes("Abcdefgh12xyz")

    def test_multiple_violations_reported_together(self) -> None:
        codes = _codes("abc")  # 短 + 缺大写 + 缺数字 + 缺特殊
        assert codes == {
            "PASSWORD_TOO_SHORT",
            "PASSWORD_MISSING_UPPERCASE",
            "PASSWORD_MISSING_DIGIT",
            "PASSWORD_MISSING_SPECIAL",
        }

    def test_policy_constants_match_frozen_spec(self) -> None:
        assert PASSWORD_MIN_LENGTH == 12
        assert PASSWORD_HISTORY_SIZE == 5
        assert PASSWORD_MAX_AGE_DAYS == 90


class TestPasswordHasher:
    def test_hash_is_not_plaintext(self) -> None:
        hasher = PasswordHasher()
        hashed = hasher.hash(STRONG_PASSWORD)
        assert hashed != STRONG_PASSWORD
        assert STRONG_PASSWORD not in hashed

    def test_uses_argon2id(self) -> None:
        hashed = PasswordHasher().hash(STRONG_PASSWORD)
        assert hashed.startswith("$argon2id$")

    def test_same_password_hashes_differently(self) -> None:
        """同一口令两次哈希必须不同（随机盐）。"""
        hasher = PasswordHasher()
        assert hasher.hash(STRONG_PASSWORD) != hasher.hash(STRONG_PASSWORD)

    def test_verify_accepts_correct_password(self) -> None:
        hasher = PasswordHasher()
        hashed = hasher.hash(STRONG_PASSWORD)
        assert hasher.verify(STRONG_PASSWORD, hashed) is True

    def test_verify_rejects_wrong_password(self) -> None:
        hasher = PasswordHasher()
        hashed = hasher.hash(STRONG_PASSWORD)
        assert hasher.verify("Wr0ng-Passw0rd!x", hashed) is False

    def test_verify_returns_false_on_malformed_hash(self) -> None:
        """非法哈希不得抛异常、不得泄漏细节（Spec 10 §9）。"""
        hasher = PasswordHasher()
        assert hasher.verify(STRONG_PASSWORD, "not-a-valid-hash") is False
        assert hasher.verify(STRONG_PASSWORD, "") is False

    def test_needs_rehash_false_for_current_params(self) -> None:
        hasher = PasswordHasher()
        assert hasher.needs_rehash(hasher.hash(STRONG_PASSWORD)) is False

    def test_needs_rehash_true_for_malformed_hash(self) -> None:
        assert PasswordHasher().needs_rehash("garbage") is True

    def test_get_password_hasher_is_singleton(self) -> None:
        assert get_password_hasher() is get_password_hasher()
