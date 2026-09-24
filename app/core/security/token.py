"""访问令牌 / 刷新令牌的生成、哈希与传输解析。

已裁定的技术决策（DD-02 **方案 A**，人类批准 2026-09-24）
------------------------------------------------------
令牌形态 = **不透明随机串**（opaque token），不携带任何声明：

```text
Access Token  = 256-bit CSPRNG → secrets.token_urlsafe(32)  → 43 字符
Refresh Token = 256-bit CSPRNG → secrets.token_urlsafe(32)  → 43 字符
落库          = sessions.access_token_hash / refresh_token_hash = SHA-256(token)（64 位十六进制）
校验          = 每请求按 access_token_hash 查 sessions → 校验未过期、未撤销
```

生命周期参数（DD-02 §P1/P2/P3/P4/P6）

| 参数 | 取值 |
|---|---|
| Access TTL | 15 分钟 |
| Refresh TTL | 7 天（**固定，不滑动**：`refresh_expires_at` 在登录时确定，轮换不延长） |
| 轮换 | 每次 refresh 都轮换 access + refresh，旧 refresh 立即失效 |
| 复用检测 | 已轮换的 refresh 再次出现 → 撤销该 session 的全部令牌（family revocation） |
| 传输 | Access 走 `Authorization: Bearer`；Refresh 走 `POST /auth/refresh` 请求体 |

为什么不用 JWT
------------
Spec `10 §7` 冻结："Revoke 后 Token 必须不能继续访问。"

自证型令牌（JWT）一经签发就无法单方面作废，要满足该条就必须**每请求回查**
session 或维护 denylist（后者引入 Redis 与尚未冻结的 DD-03）。
不透明串让"每请求查 sessions"成为唯一且充分的校验方式，
**天然满足**该冻结要求，并且不需要签名密钥、不存在算法混淆类漏洞
（`alg=none` / RS↔HS 混淆都源于"存在签名"这件事本身）。

代价是每请求一次 `sessions` 主键/唯一索引查找 —— 与 Phase 3 已裁定的
"不引入缓存"取向一致，Phase 9 再引入只读缓存。

为什么用 SHA-256 而不是 argon2id
------------------------------
密码用 argon2id 是因为口令**熵低**（可被字典枚举），必须靠慢哈希抵抗。
令牌是 256-bit 均匀随机串，枚举不可行，无需慢哈希；
而校验必须能在**每个请求**上做索引查找，因此哈希必须**确定且快**。
把令牌当口令去慢哈希，等于让每个 API 请求都付一次 argon2 成本，
是把"密码学正确"用错了位置。

Spec `10 §4` 的要求（不得记录 token 明文）由本模块保证：
调用方**只把哈希写库**，明文令牌仅存在于响应体与客户端。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

#: 令牌随机字节数。32 字节 = 256 bit，远超暴力枚举可行域。
TOKEN_ENTROPY_BYTES = 32

#: Access Token 有效期（DD-02 P1）。
ACCESS_TOKEN_TTL = timedelta(minutes=15)

#: Refresh Token 有效期（DD-02 P2）。**固定不滑动**：
#: 轮换时重置的是 access 过期时间，`refresh_expires_at` 保持不变，
#: 因此一次登录的会话总寿命上界恒为 7 天。
REFRESH_TOKEN_TTL = timedelta(days=7)

#: `sessions.*_token_hash` 列宽 = SHA-256 十六进制长度。
TOKEN_HASH_LENGTH = 64

#: Authorization 头使用的认证方案（RFC 6750 / 9110）。
BEARER_SCHEME = "Bearer"

#: 令牌字符集：`secrets.token_urlsafe` 产出 URL 安全 base64。
#: 解析时用它做形状预校验，避免把明显非令牌的内容送进数据库查询。
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")

#: 长度上界，与上面正则一致；用于拒绝异常超长输入（防日志/内存放大）。
TOKEN_MAX_LENGTH = 256


def generate_token() -> str:
    """生成一个新的不透明令牌（URL 安全 base64，约 43 字符）。"""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(token: str) -> str:
    """计算令牌的 SHA-256 十六进制摘要（落库与查询的唯一形式）。

    必须使用**无盐**的确定性哈希：有盐会让每次计算结果不同，
    从而无法按哈希做索引查询 —— 而"按令牌反查 session"正是本方案的核心。
    无盐在这里不构成风险，理由见模块 docstring（令牌熵足够高）。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_well_formed_token(token: str) -> bool:
    """令牌形状预校验（长度与字符集）。

    目的**不是安全**（安全性来自 256-bit 熵与哈希查找），
    而是：把明显不是令牌的输入（空串、超长串、含换行的串）
    挡在数据库查询之外，减少无意义查询与日志噪声。
    """
    return bool(_TOKEN_PATTERN.match(token))


def extract_bearer_token(authorization: str | None) -> str | None:
    """从 `Authorization` 头解析 Bearer 令牌。

    Returns:
        令牌字符串；头缺失、方案不匹配或令牌形状非法时返回 None。

    实现细节：方案名按 RFC 9110 做**大小写不敏感**匹配
    （`Bearer` / `bearer` 均合法），但令牌本身大小写敏感。
    形如 `Bearer` (无令牌) 或 `Bearer a b` 一律视为非法 ——
    宽松解析会让"多段垃圾"进入后续流程，属于不必要的攻击面。
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != BEARER_SCHEME.lower():
        return None
    token = parts[1].strip()
    if not is_well_formed_token(token):
        return None
    return token


__all__ = [
    "ACCESS_TOKEN_TTL",
    "BEARER_SCHEME",
    "REFRESH_TOKEN_TTL",
    "TOKEN_ENTROPY_BYTES",
    "TOKEN_HASH_LENGTH",
    "TOKEN_MAX_LENGTH",
    "extract_bearer_token",
    "generate_token",
    "hash_token",
    "is_well_formed_token",
]
