"""API v1 路由聚合（**admin 资源域**）。

Spec 08 §1 Base：`/api/v1/admin`

认证端点（`/api/v1/auth/**`）**不在此处挂载** —— 它们属于认证域，
由 `app.main.create_app` 以独立前缀挂载。理由：
登录时尚不存在"已认证的操作者"，把登录端点放进 admin 域
会让"资源域"与"认证域"的边界模糊，并暗示"先认证才能登录"。

本阶段挂载：基础设施端点（health）。
业务端点（users / roles / departments / sessions / audit / dicts ...）
分别属于后续 Phase，本阶段不实现。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]
