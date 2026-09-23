"""API v1 路由聚合。

Spec 08 §1 Base：`/api/v1/admin`

本阶段只挂载基础设施端点（health）。
业务端点（users / roles / departments / sessions / audit / dicts ...）
分别属于 Phase 1~8，本阶段不实现。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]
