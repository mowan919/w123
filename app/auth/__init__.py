"""认证 / 授权模块。

Phase 2 只交付 `CurrentActor` 值对象与集中式授权入口；
Token 解析、Session、MFA 属后续 Phase（Token 生命周期为 `16 §34#2`，未冻结）。
"""

from __future__ import annotations

from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor

__all__ = ["SUPER_ADMIN_ROLE_CODE", "CurrentActor"]
