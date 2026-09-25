"""Rate Limit —— 固定窗口计数（`009` 的"登录 / MFA 有必要的 rate limit"）。

为什么需要它，既然已经有账号锁定
------------------------------
`04 §2` 的账号锁定（`failed_login_count` / `locked_until`）是**每账号**的，
它挡不住两类攻击：

1. **撞库（credential stuffing）**：对每个账号只试一次，
   永远不会触发任何单账号的失败阈值；
2. **锁定拒绝服务**：攻击者反复用错口令把正常用户的账号锁死。

两者都只能靠"**按来源 IP**"的频次上限来缓解，因此本模块**同时**按
两个维度计数：**主体（用户名 / 用户 ID）** 与 **来源 IP**。

窗口的实现与为什么不用"首次写入再设 TTL"
--------------------------------------
计数键里带窗口起点：

```text
rl:v1:<scope>:<sha256(subject)>:<window_start>
```

这样每次写入都可以**无条件** `EXPIRE`：即使进程在 `INCR` 与 `EXPIRE`
之间崩溃，留下的孤儿键也会随窗口过期而消失，不会永久封禁某个主体。
反过来，如果只在"计数 == 1"时设 TTL，那次崩溃会让键**永不过期** ——
"限流组件的一次崩溃永久锁死一个账号"是不可接受的失败模式。

代价是窗口边界可能瞬间放行至多 2×limit（固定窗口的固有特性）。
相比"可能永久封禁"，这个代价可以接受，且已在测试中钉住。

为什么键里放哈希而不是原始用户名
----------------------------
Redis 会被运维查看、会被 `KEYS *` 扫、会进慢日志。
把用户名明文写进键名等于把"哪些账号正在被尝试登录"暴露给任何有 Redis
读权限的人 —— 这本身就是一份攻击目标清单。因此键里只放
`sha256(subject)` 的前 32 位十六进制。

Redis 不可用时的取向（JUDGMENT-9-01）
----------------------------------
**fail-open**：Redis 报错时不阻断请求，只记 WARNING。

理由不是"限流不重要"，而是**它在这里不是主防线**：

- 单账号暴力破解的主防线是 `04 §2` 的账号锁定，它**完全落在 PostgreSQL**，
  Redis 挂掉不影响它；
- 若选 fail-closed，Redis 故障 = **所有人无法登录**，
  等于把登录可用性交给一个缓存组件 —— 而且这与本应用"启动 fail-soft、
  可用性由 readiness 探针表达"的既有取向相反。

因此 Redis 不可用时的结果是"退回账号锁定这一层"，不是"退回无保护"。
该取向由 `settings.rate_limit_fail_open` 显式表达（默认 True），
运维可在不改代码的前提下改成 fail-closed。

DD-10 未冻结
-----------
具体阈值（每分钟多少次）属 **DD-10，Spec 未冻结**。
本模块把所有阈值做成配置项（INTERIM-9-01），默认值取"明显能挡住自动化
撞库、又不至于影响正常使用"的量级，DD-10 冻结后只改配置不改代码。
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

#: 键前缀。带版本号，便于将来换策略时与旧键天然隔离。
KEY_PREFIX = "rl:v1"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """一次限流判定的结果。

    `retry_after` 只在 `allowed=False` 时有意义（窗口剩余秒数），
    供响应头 `Retry-After` 使用。
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimitBackend(Protocol):
    """计数后端。

    只有两个原语，因此可以既用 Redis 实现，也用内存实现（测试用）。
    """

    async def hit(self, key: str, *, ttl_seconds: int) -> int:
        """计数 +1 并确保键有 TTL；返回计数后的值。"""
        ...

    async def ttl(self, key: str) -> int:
        """返回键的剩余秒数；键不存在返回 -2，无 TTL 返回 -1。"""
        ...


class InMemoryRateLimitBackend:
    """进程内计数后端。

    用于测试与"Redis 尚未接入"的环境。**不跨进程生效** ——
    多副本部署下它不能替代 Redis，这一点在 `RateLimiter` 的日志里会说明。
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._expiry: dict[str, float] = {}

    async def hit(self, key: str, *, ttl_seconds: int) -> int:
        now = time.monotonic()
        expires_at = self._expiry.get(key)
        if expires_at is not None and expires_at <= now:
            self._counts.pop(key, None)
            self._expiry.pop(key, None)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        self._expiry[key] = now + ttl_seconds
        return count

    async def ttl(self, key: str) -> int:
        expires_at = self._expiry.get(key)
        if expires_at is None:
            return -2
        return max(0, int(expires_at - time.monotonic()))

    def reset(self) -> None:
        """清空全部计数（测试用）。"""
        self._counts.clear()
        self._expiry.clear()


class RedisRateLimitBackend:
    """Redis 计数后端。

    `INCR` 与 `EXPIRE` 放在同一个 pipeline 里，
    避免进程在两者之间崩溃留下无 TTL 的键。
    """

    def __init__(self, client: object) -> None:
        self._client = client

    async def hit(self, key: str, *, ttl_seconds: int) -> int:
        pipe = self._client.pipeline()  # type: ignore[attr-defined]
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
        return int(results[0])

    async def ttl(self, key: str) -> int:
        return int(await self._client.ttl(key))  # type: ignore[attr-defined]


def build_key(*, scope: str, subject: str, window_seconds: int, now: float | None = None) -> str:
    """构造计数键（见模块 docstring：键里只放哈希，不放原始主体）。"""
    moment = time.time() if now is None else now
    window_start = int(moment) // window_seconds
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    return f"{KEY_PREFIX}:{scope}:{digest}:{window_start}"


class RateLimiter:
    """按 `(scope, subject)` 做固定窗口限流。

    典型用法（登录）：先按用户名判一次，再按来源 IP 判一次；
    任一个超限即拒绝 —— 因为两个维度防的是**不同的**攻击。
    """

    def __init__(
        self,
        backend: RateLimitBackend,
        *,
        fail_open: bool = True,
    ) -> None:
        self._backend = backend
        self._fail_open = fail_open

    async def check(
        self,
        *,
        scope: str,
        subject: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """判定并计数。

        注意本方法**有副作用**：判定通过也会消耗一次配额。
        """
        key = build_key(scope=scope, subject=subject, window_seconds=window_seconds)
        try:
            count = await self._backend.hit(key, ttl_seconds=window_seconds)
        except Exception as exc:
            # 这里**必须**宽泛捕获：Redis 客户端的异常类型取决于
            # 连接池 / 超时 / 协议错误等，穷举会漏。漏掉的后果不是
            # "少限流一次"，而是"限流组件的任何新故障模式都会变成 500"。
            if not self._fail_open:
                logger.error("rate_limit_backend_unavailable scope=%s fail_closed", scope)
                raise
            logger.warning(
                "rate_limit_backend_unavailable scope=%s type=%s fail_open=True",
                scope,
                type(exc).__name__,
            )
            return RateLimitDecision(allowed=True, limit=limit, remaining=limit, retry_after=0)

        if count > limit:
            return RateLimitDecision(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after=await self._retry_after(key, window_seconds),
            )
        return RateLimitDecision(
            allowed=True, limit=limit, remaining=max(0, limit - count), retry_after=0
        )

    async def _retry_after(self, key: str, window_seconds: int) -> int:
        try:
            ttl = await self._backend.ttl(key)
        except Exception:
            return window_seconds
        return ttl if ttl > 0 else window_seconds


def rate_limit_headers(decision: RateLimitDecision) -> Mapping[str, str]:
    """响应头。

    刻意**不**回显主体信息（连哈希都不回）：
    这个端点在未认证场景被调用，任何回显都会给攻击者一面镜子。
    """
    headers = {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(decision.retry_after)
    return headers


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------
_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """返回进程级限流器（惰性构造，默认后端为 Redis）。

    为什么是单例而不是每次新建：限流的语义依赖**跨请求共享计数**，
    而后端（Redis 连接池）本身也应该是进程级复用的。
    """
    global _limiter
    if _limiter is None:
        from app.db.redis import get_redis

        _limiter = RateLimiter(
            RedisRateLimitBackend(get_redis()),
            fail_open=settings.rate_limit_fail_open,
        )
    return _limiter


def set_rate_limiter(limiter: RateLimiter | None) -> None:
    """替换 / 复位进程级限流器。

    存在理由：测试需要把后端换成 `InMemoryRateLimitBackend`，
    否则每个用例都会消耗真实 Redis 的配额 —— 那会让"第 N 个登录用例
    突然 429"变成一种难以复现的测试间耦合。
    """
    global _limiter
    _limiter = limiter
