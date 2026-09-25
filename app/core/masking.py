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

import re
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
    return _scrub_scalar(key, value)


def _scrub_scalar(key: str, value: Any) -> Any:
    """按键名脱敏一个标量，再对文本做模式脱敏。

    两道都要走：键名规则覆盖"这个字段叫 phone"，
    文本规则覆盖"值里恰好写着手机号但字段名叫 `remark`"。
    前者是声明式的，后者是兜底的 —— 只有前者时，
    一个自由文本字段就能把手机号完整带进日志。
    """
    masked = mask_value(key, value)
    if isinstance(masked, str):
        return scrub_text(masked)
    return masked


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
                cleaned[key] = _scrub_scalar(key, raw_value)
        return cleaned

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [scrub(item, _depth=_depth + 1) for item in value]

    if isinstance(value, str):
        return scrub_text(value)

    return value


# ---------------------------------------------------------------------------
# 自由文本脱敏
# ---------------------------------------------------------------------------
# 为什么结构脱敏之外还需要文本脱敏
# ------------------------------
# `scrub()` 靠**键名**判断敏感度。而日志正文是**渲染后的字符串**：
#
#     logger.info("登录失败 phone=13812341234 password=%s", raw_password)
#
# 渲染之后既没有 `phone` 键也没有 `password` 键，`scrub()` 无从下手 ——
# 而 `MaskingFilter` 跳过的恰恰是 `msg` / `args`（它们是保留键）。
# 于是 `06 §4` 的脱敏规则在最常见的路径上**形同虚设**。
#
# 因此这里补一层基于**模式**的文本脱敏，作用在渲染结果上。
#
# 刻意保守：宁可多脱一点，不可漏脱
# ------------------------------
# 手机号只匹配中国大陆 11 位号段（`1[3-9]` 开头、前后不是数字），
# 使 19 位 Snowflake ID 等业务数字不会被误伤。
# 密钥对（`password=...`）一律整体替换为 `<redacted>` —— 对**自由文本**而言，
# "只留前 6 字符"会把 Secret 的前缀写进日志，而前缀本身已足以用于关联、
# 部分暴力破解与"哪个密钥泄露了"的确认；`10 §4` 的措辞是"不得记录明文"，
# 因此这里比 `mask_token` 更严。方向只允许更严，不允许更松。
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

#: `Authorization: Bearer xxx` —— 值直到行尾。
_AUTHORIZATION_RE = re.compile(r"(?i)\bauthorization\b\s*[:=]\s*[^\r\n,;]*")

#: `Bearer xxx` / `Basic xxx`（缺少 `authorization` 关键字时的兜底）。
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}")

#: 密钥类键值对。
#:
#: ## 为什么必须容忍键名与值两侧的**引号**（FINDING-9-01）
#:
#: 最早的写法是 `键\s*[:=]\s*\S+`，它只能命中 `password=hunter2`
#: 与 `password: hunter2` 这类"裸"写法。但结构化日志**最常出现的形状是
#: JSON**：`{"password": "hunter2"}` —— 键名后面紧跟一个 `"` 才是冒号，
#: 于是 `\s*[:=]` 匹配不上，**整条密码原样落库**。
#: 那不是"少脱敏了一种格式"，而是漏掉了最常见的那一种。
#:
#: 因此在键名与冒号之间、冒号与值之间都允许可选引号，
#: 并让值取到引号 / 空白 / 分隔符为止（而不是贪婪的 `\S+`，
#: 否则会把值后面的 `"` 也吃掉，破坏输出的可读性）。
_SECRET_PAIR_RE = re.compile(
    r"(?i)\b("
    r"password|passwd|pwd|new_password|old_password|confirm_password|password_hash|"
    r"mfa_secret|totp_secret|otp_secret|secret|client_secret|signing_secret|"
    r"encryption_key|mfa_encryption_key|private_key|secret_key|"
    r"access_token|refresh_token|id_token|session_token|token|api_key"
    r")\b\s*[\"']?\s*[:=]\s*[\"']?[^'\"\s,;}\]]+"
)

#: JWT（三段 base64url）。它是最容易在自由文本里出现形态的令牌。
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}")


def mask_phone_in_text(match: re.Match[str]) -> str:
    """把文本中命中的手机号替换为 `138****1234` 形态。"""
    return f"{match.group(1)}****{match.group(3)}"


def scrub_text(value: str) -> str:
    """对**自由文本**做模式脱敏（消息体、异常堆栈）。

    顺序有意为之：先处理"整段密钥"，再处理单个令牌形态，最后才处理
    可部分保留的 phone / email —— 否则一次 `password=13812341234`
    会被先脱成 `password=138****1234`，虽然结果仍安全，
    但多绕一步会掩盖"这里原本是密钥字段"这一更强的事实。

    幂等：输出中的 `***` / `<redacted>` 不会再被任何模式命中。
    """
    if not value:
        return value

    text = _AUTHORIZATION_RE.sub("authorization=<redacted>", value)
    text = _BEARER_RE.sub(r"\1 <redacted>", text)
    text = _JWT_RE.sub(NEVER_LOG, text)
    text = _SECRET_PAIR_RE.sub(lambda m: f"{m.group(1)}={NEVER_LOG}", text)
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}{MASKED}@{m.group(2)}", text)
    return _PHONE_RE.sub(mask_phone_in_text, text)
