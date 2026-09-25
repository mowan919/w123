"""安全响应头中间件（Phase 9 / `PHASES.md` Phase 9: Security headers）。

为什么单独放在一个中间件里
--------------------------
安全头是"**每一个**响应都必须有"的属性。如果靠各个端点自己加，
那么"新写的端点忘了加"不会有任何测试失败，只会在上线后某个
安全扫描里冒出来 —— 这类属性必须**结构性**地施加，而不是靠纪律。

本中间件是纯 ASGI 实现（与 `TraceMiddleware` 同口径），
在 `send` 层拦截 `http.response.start` 并补全缺失的头。

逐项的取舍
---------
- **`X-Content-Type-Options: nosniff`**
  阻止浏览器对响应做 MIME 嗅探。本 API 的所有 `Content-Type` 都是
  服务端明确设定的，嗅探只会带来"把 JSON 当别的类型解释"的风险。

- **`X-Frame-Options: DENY`**
  管理后台没有任何需要被嵌套的场景。允许嵌套等于接受点击劫持
  （clickjacking）：攻击者把一个透明的 iframe 叠在按钮上，
  管理员"点的是自己看到的页面"，实际点的是被嵌套的后台。

- **`Referrer-Policy: no-referrer`**
  后台 URL 里带业务 ID（`/users/{id}`）。默认策略会把完整 URL
  泄漏给任何外链目标，等于把内部 ID 交给第三方。

- **`Cache-Control: no-store`**
  **这一项对本系统尤其重要**：响应里有权限契约、用户列表、
  会话列表。若被中间缓存或浏览器缓存留存，"权限已变更"
  在缓存有效期内对客户端不可见 —— 那正好破坏 `09 §7`
  "权限变更立即生效"。同时它是 `13 §4` 敏感数据不留存的直接落地。

- **`Strict-Transport-Security`**
  **默认关闭**。HSTS 是一个"一旦下发就难以撤回"的承诺：
  浏览器在 max-age 内会强制 HTTPS，若部署其实只在 HTTP 下工作
  （或某个内网健康检查端口只开 HTTP），下发 HSTS 会把那个端口
  直接变成不可用。因此它由 `settings.security_hsts_enabled` 控制，
  由部署方在**确认**全站 HTTPS 之后开启，而不是由代码替它决定。

为什么**不**加 `Content-Security-Policy`
-------------------------------------
本服务只输出 JSON，不渲染 HTML。CSP 约束的是页面能加载哪些
脚本/样式/连接目标 —— 对纯 JSON API 没有保护对象，
却会因为"策略太宽"而在扫描报告里产生一条噪音。
若将来交付前端静态资源，CSP 应在那个资源服务上配置。
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

#: 无条件施加的头（值不含任何请求数据，可安全复用同一个 dict 对象）。
_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)


def _build_headers() -> list[tuple[bytes, bytes]]:
    headers = list(_BASE_HEADERS)
    if settings.security_hsts_enabled:
        headers.append(
            (
                b"strict-transport-security",
                f"max-age={settings.security_hsts_max_age}".encode(),
            )
        )
    return headers


class SecurityHeadersMiddleware:
    """为所有 HTTP 响应补全安全头（已存在的同名头**不覆盖**）。

    为什么不覆盖：限流在登录响应上会带 `RateLimit-*`，端点也可能
    出于自身原因设置 `Cache-Control`（例如将来给静态资源开缓存）。
    中间件若是"覆盖式"的，端点就无法表达任何例外 ——
    因此这里只**补缺**，把最终决定权留给更靠近业务的那层。
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._headers = _build_headers()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing: MutableMapping[str, Any] = {}
                raw = message.get("headers")
                if raw:
                    existing = {k.decode().lower(): v for k, v in raw if k and v}
                missing = [
                    (name, value) for name, value in self._headers if name.decode() not in existing
                ]
                if missing:
                    message["headers"] = list(raw or []) + missing
            await send(message)

        await self._app(scope, receive, send_with_headers)
