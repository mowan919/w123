"""Rate Limit 测试（Phase 9 / `009`）。

分两层：

1. **限流器本身**（`TestLimiter`）—— 纯逻辑，不碰 HTTP；
2. **接线**（`TestLoginEndpointLimit` / `TestMfaEndpointLimit`）——
   证明端点真的在**校验凭据之前**消耗配额，且超限返回 429。

为什么第 2 层不可省：限流器写得再对，只要端点把它放在
"校验失败之后"，它对攻击者就**零成本** —— 那不叫限流，叫统计。
这类接线错误在单元测试里完全看不到。

`TestRedisBackend` 打真实 Redis：内存后端再正确也不能证明
`INCR` + `EXPIRE` 的 pipeline 与 TTL 语义在生产后端上成立。
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.rate_limit import (
    KEY_PREFIX,
    InMemoryRateLimitBackend,
    RateLimiter,
    build_key,
    rate_limit_headers,
)
from app.db.base import utc_now
from app.db.session import get_db
from tests.factories import make_user

pytestmark = pytest.mark.integration

PASSWORD = "Rate-Limit-Passw0rd!09"
USER_ID = 64001
AUTH_PREFIX = "/api/v1/auth"


# ===========================================================================
# 1. 限流器本身
# ===========================================================================
class TestKeyBuilding:
    def test_key_never_carries_the_raw_subject(self) -> None:
        """键里只放哈希 —— 否则 Redis 变成一份"谁正被撞库"的清单。"""
        key = build_key(scope="login", subject="admin@corp.example", window_seconds=60)
        assert "admin@corp.example" not in key
        # 哈希可复现：同一主体同一窗口必须落到同一个键，否则限流不生效。
        digest = hashlib.sha256(b"admin@corp.example").hexdigest()[:32]
        assert digest in key

    def test_different_windows_land_on_different_keys(self) -> None:
        """窗口推进后键必须变化，否则计数永不归零 = 永久封禁。"""
        first = build_key(scope="login", subject="u", window_seconds=60, now=0.0)
        second = build_key(scope="login", subject="u", window_seconds=60, now=120.0)
        assert first != second

    def test_scopes_do_not_collide(self) -> None:
        a = build_key(scope="login", subject="x", window_seconds=60, now=0.0)
        b = build_key(scope="mfa", subject="x", window_seconds=60, now=0.0)
        assert a != b
        assert a.startswith(f"{KEY_PREFIX}:login:")
        assert b.startswith(f"{KEY_PREFIX}:mfa:")


class TestLimiter:
    async def test_under_limit_is_allowed_and_decrements(self) -> None:
        limiter = RateLimiter(InMemoryRateLimitBackend())
        for expected_remaining in (2, 1):
            decision = await limiter.check(scope="login", subject="u", limit=3, window_seconds=60)
            assert decision.allowed
            assert decision.remaining == expected_remaining

    async def test_over_limit_is_denied_with_retry_after(self) -> None:
        limiter = RateLimiter(InMemoryRateLimitBackend())
        for _ in range(3):
            assert (
                await limiter.check(scope="login", subject="u", limit=3, window_seconds=60)
            ).allowed
        blocked = await limiter.check(scope="login", subject="u", limit=3, window_seconds=60)
        assert not blocked.allowed
        assert blocked.remaining == 0
        assert 0 < blocked.retry_after <= 60

    async def test_unknown_client_ip_has_its_own_bucket(self) -> None:
        """IP 缺失不能变成"不限流"，否则就是一条现成的绕行通道。"""
        backend = InMemoryRateLimitBackend()
        limiter = RateLimiter(backend)
        for _ in range(5):
            assert (
                await limiter.check(scope="login", subject="unknown", limit=5, window_seconds=60)
            ).allowed
        assert not (
            await limiter.check(scope="login", subject="unknown", limit=5, window_seconds=60)
        ).allowed

    async def test_subjects_are_isolated(self) -> None:
        backend = InMemoryRateLimitBackend()
        limiter = RateLimiter(backend)
        for _ in range(2):
            await limiter.check(scope="login", subject="a", limit=2, window_seconds=60)
        assert not (
            await limiter.check(scope="login", subject="a", limit=2, window_seconds=60)
        ).allowed
        # 另一个主体不受影响 —— 否则一次超限会连坐所有人
        assert (await limiter.check(scope="login", subject="b", limit=2, window_seconds=60)).allowed


class _BrokenBackend:
    """永远抛错的后端，用于钉住 Redis 故障时的取向。"""

    async def hit(self, key: str, *, ttl_seconds: int) -> int:
        raise RuntimeError("redis is down")

    async def ttl(self, key: str) -> int:
        raise RuntimeError("redis is down")


class TestFailOpen:
    async def test_fail_open_allows_but_does_not_crash(self) -> None:
        """默认 fail-open：Redis 挂掉时退回"账号锁定"这一层，不是无保护。

        论证见 `app/core/rate_limit.py`（JUDGMENT-9-01）。
        """
        limiter = RateLimiter(_BrokenBackend(), fail_open=True)
        decision = await limiter.check(scope="login", subject="u", limit=3, window_seconds=60)
        assert decision.allowed
        assert decision.remaining == decision.limit

    async def test_fail_closed_propagates(self) -> None:
        """`fail_open=False` 时必须真的把错误抛出去（而不是静默放行）。"""
        limiter = RateLimiter(_BrokenBackend(), fail_open=False)
        with pytest.raises(RuntimeError):
            await limiter.check(scope="login", subject="u", limit=3, window_seconds=60)


class TestHeaders:
    def test_headers_carry_only_numbers(self) -> None:
        """响应头不得回显主体信息 —— 端点在未认证路径上被调用。"""
        allowed = RateLimiter(InMemoryRateLimitBackend())
        decision: Any = allowed
        # 直接用数据类构造，避免为了拿一个 decision 去跑 asyncio
        from app.core.rate_limit import RateLimitDecision

        ok = RateLimitDecision(allowed=True, limit=10, remaining=7, retry_after=0)
        headers = dict(rate_limit_headers(ok))
        assert headers == {"RateLimit-Limit": "10", "RateLimit-Remaining": "7"}
        assert "Retry-After" not in headers

        denied = RateLimitDecision(allowed=False, limit=10, remaining=0, retry_after=42)
        denied_headers = dict(rate_limit_headers(denied))
        assert denied_headers["Retry-After"] == "42"
        assert decision is not None


# ===========================================================================
# 2. 端点接线
# ===========================================================================
@pytest_asyncio.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """把端点的事务会话指向用例事务。"""

    async def _override_get_db() -> AsyncIterator[object]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _seed(db_session, *, username: str = "rl-user", user_id: int = USER_ID):
    return await make_user(
        db_session,
        user_id=user_id,
        username=username,
        password=PASSWORD,
        password_changed_at=utc_now(),
    )


class TestLoginEndpointLimit:
    async def test_successful_login_also_consumes_quota(
        self, api: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """限流必须在校验凭据**之前** —— 成功的登录也要计数。"""
        await _seed(db_session)
        monkeypatch.setattr(settings, "rate_limit_login_per_subject", 2)
        monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 600)

        for _ in range(2):
            response = await api.post(
                f"{AUTH_PREFIX}/login",
                json={"username": "rl-user", "password": PASSWORD},
            )
            assert response.status_code == 200, response.text
            assert response.headers["RateLimit-Limit"] == "2"

        blocked = await api.post(
            f"{AUTH_PREFIX}/login", json={"username": "rl-user", "password": PASSWORD}
        )
        assert blocked.status_code == 429
        assert blocked.json()["code"] == 429001
        assert blocked.json()["data"] is None
        # 文案不带任何主体信息
        assert "rl-user" not in blocked.text

    async def test_wrong_password_is_also_limited(
        self, api: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """口令错误同样消耗配额（否则限流挡不住任何攻击）。"""
        await _seed(db_session)
        monkeypatch.setattr(settings, "rate_limit_login_per_subject", 3)
        monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 600)

        for _ in range(3):
            response = await api.post(
                f"{AUTH_PREFIX}/login", json={"username": "rl-user", "password": "nope"}
            )
            assert response.status_code == 401

        blocked = await api.post(
            f"{AUTH_PREFIX}/login", json={"username": "rl-user", "password": "nope"}
        )
        assert blocked.status_code == 429
        assert blocked.json()["code"] == 429001

    async def test_ip_dimension_is_independent(
        self, api: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """用户名维度没超、IP 维度超了，也必须拦住（挡撞库）。"""
        await _seed(db_session, username="rl-a", user_id=64011)
        await _seed(db_session, username="rl-b", user_id=64012)
        monkeypatch.setattr(settings, "rate_limit_login_per_subject", 50)
        monkeypatch.setattr(settings, "rate_limit_login_per_ip", 2)
        monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 600)

        assert (
            await api.post(f"{AUTH_PREFIX}/login", json={"username": "rl-a", "password": PASSWORD})
        ).status_code == 200
        assert (
            await api.post(f"{AUTH_PREFIX}/login", json={"username": "rl-b", "password": PASSWORD})
        ).status_code == 200

        # 换了个账号，但来源 IP 还是同一个 → 应当被拦
        blocked = await api.post(
            f"{AUTH_PREFIX}/login", json={"username": "rl-a", "password": PASSWORD}
        )
        assert blocked.status_code == 429
        assert "rl-a" not in blocked.text

    async def test_disabling_rate_limit_disables_both_dimensions(
        self, api: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed(db_session)
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        monkeypatch.setattr(settings, "rate_limit_login_per_subject", 1)
        for _ in range(3):
            response = await api.post(
                f"{AUTH_PREFIX}/login",
                json={"username": "rl-user", "password": PASSWORD},
            )
            assert response.status_code == 200


class TestMfaEndpointLimit:
    async def test_verify_is_rate_limited(
        self, api: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "rate_limit_mfa_per_ip", 2)
        monkeypatch.setattr(settings, "rate_limit_mfa_window_seconds", 600)

        for _ in range(2):
            response = await api.post(
                f"{AUTH_PREFIX}/mfa/verify",
                json={"mfa_token": "not-a-real-token", "code": "123456"},
            )
            # 挑战令牌不存在 → 401；限流未介入
            assert response.status_code == 401, response.text

        blocked = await api.post(
            f"{AUTH_PREFIX}/mfa/verify",
            json={"mfa_token": "not-a-real-token", "code": "123456"},
        )
        assert blocked.status_code == 429
        assert blocked.json()["code"] == 429001


# ===========================================================================
# 3. 真实 Redis 后端
# ===========================================================================
class TestRedisBackend:
    """打真实 Redis。

    内存后端再正确，也不能证明 `INCR` + `EXPIRE` 的 pipeline 与 TTL
    语义在生产后端上成立 —— 而"TTL 没设上"的后果是永久封禁。
    """

    async def test_real_redis_counts_and_sets_ttl(self, real_redis_client) -> None:
        from app.core.rate_limit import RedisRateLimitBackend

        try:
            await real_redis_client.ping()  # type: ignore[attr-defined]
        except Exception as exc:
            pytest.skip(f"Redis 不可达（{type(exc).__name__}），跳过真后端用例")

        # 作用域带固定后缀：既与真实业务键隔离，又便于运维在 Redis 里
        # 一眼认出"这是测试留下的键"（TTL 到点自动消失）。
        scope = "pytest-" + hashlib.sha256(b"vctn-rl-test").hexdigest()[:8]
        limiter = RateLimiter(RedisRateLimitBackend(real_redis_client), fail_open=False)

        for _ in range(3):
            assert (
                await limiter.check(scope=scope, subject="probe", limit=3, window_seconds=60)
            ).allowed
        denied = await limiter.check(scope=scope, subject="probe", limit=3, window_seconds=60)
        assert not denied.allowed
        # TTL 必须真的被设上（否则这个键永不过期 = 永久封禁）
        assert 0 < denied.retry_after <= 60

    async def test_real_redis_keys_do_not_contain_the_subject(self, real_redis_client) -> None:
        from app.core.rate_limit import RedisRateLimitBackend

        try:
            await real_redis_client.ping()  # type: ignore[attr-defined]
        except Exception as exc:
            pytest.skip(f"Redis 不可达（{type(exc).__name__}），跳过真后端用例")

        subject = "secret-username-should-not-appear"
        scope = "pytest-" + hashlib.sha256(b"vctn-rl-keys").hexdigest()[:8]
        limiter = RateLimiter(RedisRateLimitBackend(real_redis_client), fail_open=False)
        await limiter.check(scope=scope, subject=subject, limit=99, window_seconds=60)

        key = build_key(scope=scope, subject=subject, window_seconds=60)
        assert subject not in key

        # 真键必须**真的存在于 Redis 里**（否则上面只是断言了一个字符串形状）
        assert await real_redis_client.exists(key) == 1  # type: ignore[attr-defined]
        # 且必须带 TTL —— 没有 TTL 的限流键 = 永久封禁
        assert await real_redis_client.ttl(key) > 0  # type: ignore[attr-defined]
        # 顺手清理，避免测试键残留到窗口结束
        await real_redis_client.delete(key)  # type: ignore[attr-defined]
