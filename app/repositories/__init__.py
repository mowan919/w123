"""Repository 层。

职责：纯数据访问，接受**已解析**的数据范围约束（`ResolvedScope`），
把范围转换为 SQL 条件后下推到数据库。

Repository **不**做授权决策，也不接受原始 `CurrentActor` ——
避免"授权逻辑散落在数据访问层"。
"""

from __future__ import annotations

from app.repositories.scope_filters import department_scope_condition, user_scope_condition

__all__ = ["department_scope_condition", "user_scope_condition"]
