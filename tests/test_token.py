"""令牌原语测试（Phase 4 / DD-02 方案 A）。

这些是**安全原语级**用例：它们钉住的是"令牌如何生成与哈希"这一层性质。
业务行为（登录 / 刷新 / 撤销）在 `tests/test_session_service.py` 与
`tests/test_auth_service.py` 覆盖。
"""

from __future__ import annotations

import hashlib

import pytest

from app.core.security.token import (
    ACCESS_TOKEN_TTL,
    BEARER_SCHEME,
    REFRESH_TOKEN_TTL,
    TOKEN_ENTROPY_BYTES,
    TOKEN_HASH_LENGTH,
    TOKEN_MAX_LENGTH,
    extract_bearer_token,
    generate_token,
    hash_token,
    is_well_formed_token,
)

pytestmark = pytest.mark.unit


class TestTtlPolicy:
    """DD-02 P1 / P2 冻结的 TTL 取值。"""

    def test_access_token_ttl_is_15_minutes(self) -> None:
        assert ACCESS_TOKEN_TTL.total_seconds() == 15 * 60

    def test_refresh_token_ttl_is_7_days(self) -> None:
        assert REFRESH_TOKEN_TTL.total_seconds() == 7 * 24 * 60 * 60

    def test_refresh_outlives_access_by_a_large_margin(self) -> None:
        """refresh 必须显著长于 access —— 否则"刷新"没有意义。

        若两者相同，access 过期时 refresh 也过期，
        `/auth/refresh` 永远拿不到可用结果（功能死掉），
        而这类错误在"只看单个常量"的评审里看不出来。
        """
        assert REFRESH_TOKEN_TTL >= ACCESS_TOKEN_TTL * 100

    def test_bearer_scheme(self) -> None:
        assert BEARER_SCHEME == "Bearer"


class TestGenerateToken:
    def test_entropy_bytes_is_32(self) -> None:
        """256 bit：足以让在线枚举不可行（DD-02 的核心前提）。"""
        assert TOKEN_ENTROPY_BYTES == 32

    def test_generated_token_is_url_safe_and_long_enough(self) -> None:
        token = generate_token()
        assert is_well_formed_token(token)
        # token_urlsafe(32) → 43 字符（32 字节 base64url 无填充）
        assert len(token) >= 43

    def test_tokens_are_unique_across_calls(self) -> None:
        """1000 次生成不得出现重复（若重复说明随机源坏了）。"""
        tokens = {generate_token() for _ in range(1000)}
        assert len(tokens) == 1000

    def test_token_does_not_carry_claims(self) -> None:
        """不透明令牌：不得包含 '.' 分隔的声明段（否则会被误当作 JWT 使用）。

        这是防止"实现漂移"的护栏：DD-02 明确否决了 JWT，
        而 JWT 的特征就是 `header.payload.signature`。
        """
        assert "." not in generate_token()


class TestHashToken:
    def test_hash_is_sha256_hex(self) -> None:
        token = generate_token()
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert hash_token(token) == expected
        assert len(hash_token(token)) == TOKEN_HASH_LENGTH == 64

    def test_hash_is_deterministic(self) -> None:
        """必须确定 —— 否则无法按哈希索引查询（方案的成立前提）。"""
        token = generate_token()
        assert hash_token(token) == hash_token(token)

    def test_hash_is_unsalted_so_same_token_same_hash(self) -> None:
        """同一令牌两次哈希相同；不同令牌哈希不同。"""
        a, b = generate_token(), generate_token()
        assert hash_token(a) != hash_token(b)

    def test_hash_never_returns_the_plaintext(self) -> None:
        token = generate_token()
        assert token not in hash_token(token)


class TestIsWellFormedToken:
    def test_accepts_generated_tokens(self) -> None:
        assert is_well_formed_token(generate_token())

    @pytest.mark.parametrize(
        "candidate",
        [
            "",
            "short",
            "x" * (TOKEN_MAX_LENGTH + 1),
            "has space inside-token-value",
            "line\nbreak-in-token",
            "emoji-token-\u2764\ufe0f-value",
        ],
    )
    def test_rejects_malformed(self, candidate: str) -> None:
        """形状校验只为挡掉明显非令牌的输入，不为安全。

        但它必须挡住**换行** —— 否则日志注入（把 token 写进日志时伪造新行）
        与请求 smuggler 类问题会从认证入口进来。
        """
        assert is_well_formed_token(candidate) is False


class TestExtractBearerToken:
    def test_extracts_token(self) -> None:
        token = generate_token()
        assert extract_bearer_token(f"Bearer {token}") == token

    def test_scheme_is_case_insensitive(self) -> None:
        """RFC 9110：认证方案名大小写不敏感。"""
        token = generate_token()
        assert extract_bearer_token(f"bearer {token}") == token
        assert extract_bearer_token(f"BEARER {token}") == token

    def test_tolerates_extra_whitespace(self) -> None:
        token = generate_token()
        assert extract_bearer_token(f"Bearer    {token}  ") == token

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "",
            "Bearer",
            "Bearer ",
            "Basic dXNlcjpwYXNz",
            "Token abcdefghijklmnopqrst",
            "Bearer token-one Bearer token-two",
        ],
    )
    def test_rejects_missing_or_foreign_scheme(self, header: str | None) -> None:
        assert extract_bearer_token(header) is None

    def test_token_case_is_preserved(self) -> None:
        """令牌本身大小写**敏感**（只对方案名大小写不敏感）。

        若实现顺手对整串做了 lower()，令牌就会永远校验失败 ——
        这是"看起来只是规范化了一下"造成的整站登录故障。
        """
        token = "AbCdEfGhIjKlMnOpQrStUvWx"
        assert extract_bearer_token(f"Bearer {token}") == token
