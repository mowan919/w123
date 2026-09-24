"""`User-Agent` → 设备描述（INTERIM 技术取值）。

Spec 依据与边界
--------------
Spec `04 §3` 要求 Session 记录 `device`，但**未规定** device 的判定来源。
Spec `16` 的待冻结项中也没有这一项，因此本模块取一个保守的 INTERIM 实现：

    从 `User-Agent` 做**启发式粗分类**，输出形如
    `Chrome · Windows · desktop` 的短标签。

明确不作为任何安全依据
--------------------
`User-Agent` 完全由客户端控制，**可任意伪造**。因此：

- 本模块的输出**只用于后台展示**（"这个会话大概是什么设备"）；
- **绝不**参与任何授权、风控、范围判断或"新设备告警"逻辑；
- 需要可信设备信息时必须由人类另行裁定（例如设备指纹 / 绑定），
  不得把本模块的输出提升为安全依据。

不引入第三方解析库（如 `ua-parser`）的理由：Spec 未冻结选型，
而该字段的安全价值为零，引入依赖只会扩大供应链面。
"""

from __future__ import annotations

import re

#: `sessions.device` 列宽；超出部分截断，避免写库失败。
DEVICE_MAX_LENGTH = 128

_UNKNOWN = "unknown"

#: (正则, 标签) —— 顺序即优先级，先匹配者胜。
#: 浏览器判定必须在操作系统之前，因为多数 UA 同时包含两者。
_BROWSERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Edg[A-Za-z]*/"), "Edge"),
    (re.compile(r"OPR/|Opera/"), "Opera"),
    (re.compile(r"Firefox/"), "Firefox"),
    (re.compile(r"Chrome/"), "Chrome"),
    (re.compile(r"Safari/"), "Safari"),
    (re.compile(r"MSIE |Trident/"), "Internet Explorer"),
    # 自动化 / 命令行客户端：归类为其他，便于在后台一眼看出"这不是浏览器"。
    (re.compile(r"curl/|Wget/|python-requests|httpx/|Go-http-client|okhttp"), "http-client"),
)

_OPERATING_SYSTEMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Windows NT 10\.0"), "Windows"),
    (re.compile(r"Windows NT 6\.3"), "Windows 8.1"),
    (re.compile(r"Windows NT 6\.1"), "Windows 7"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"iPhone OS|iOS"), "iOS"),
    (re.compile(r"iPad"), "iPadOS"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"Mac OS X|Macintosh"), "macOS"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"Linux"), "Linux"),
)

_DEVICE_CLASSES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"bot|crawler|spider|slurp", re.IGNORECASE), "bot"),
    (re.compile(r"iPad|Tablet|PlayBook|Silk", re.IGNORECASE), "tablet"),
    (re.compile(r"Mobile|iPhone|iPod|Android.*Mobile|Windows Phone", re.IGNORECASE), "mobile"),
    (re.compile(r"curl/|Wget/|python-requests|httpx/|Go-http-client|okhttp"), "programmatic"),
    (re.compile(r"Windows|Macintosh|X11|CrOS|Linux"), "desktop"),
)


def _first_match(patterns: tuple[tuple[re.Pattern[str], str], ...], value: str) -> str | None:
    for pattern, label in patterns:
        if pattern.search(value):
            return label
    return None


def describe_device(user_agent: str | None) -> str | None:
    """把 `User-Agent` 归类为短标签。

    Returns:
        `"Chrome · Windows · desktop"` 这类标签；
        `User-Agent` 缺失（None / 空白）时返回 `None` ——
        缺失就是缺失，不编造 `"unknown"`，避免下游把"未知"误当成一个事实。
        无法识别的部分用 `unknown` 占位（例如 `"unknown · Linux · desktop"`）。
    """
    if user_agent is None:
        return None
    raw = user_agent.strip()
    if not raw:
        return None

    parts = (
        _first_match(_BROWSERS, raw) or _UNKNOWN,
        _first_match(_OPERATING_SYSTEMS, raw) or _UNKNOWN,
        _first_match(_DEVICE_CLASSES, raw) or _UNKNOWN,
    )
    label = " · ".join(parts)
    return label[:DEVICE_MAX_LENGTH]


__all__ = ["DEVICE_MAX_LENGTH", "describe_device"]
