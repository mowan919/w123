"""数据范围 → SQL 条件的关键转换点。

Frozen 依据
-----------
Spec `10 §10`：所有带数据范围的查询必须在 Service/Repository 层真正约束；
禁止"先查询全部，再在 Python 内存中随意过滤"；
对敏感数据应尽量让 DB query 本身带 scope 条件。

因此数据范围**只允许**通过本模块转换成 SQL 条件，
不允许任何调用方自行拼 `department_id`（AGENTS.md §5.1）。

三个关键安全性质
--------------
1. **fail-closed**：`denies_all_departments` 必须翻译为 `FALSE`，
   而不是"忽略条件"。忽略条件等于把空范围升级为全局范围。
2. **SELF 不与部门条件取并集**：SELF 的用户维度条件严格为
   `id = actor_id`。若改为 `id = actor OR department_id IN (...)`，
   会把"仅本人"放大为"本部门所有人"，属典型越权。
3. **永不接受 None 语义的"部门条件"**：`ResolvedScope` 已通过不变量
   保证只有 ALL 才允许 `department_ids=None`。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, false, true

from app.core.scope import ResolvedScope
from app.models.department import Department
from app.models.user import AdminUser


def department_scope_condition(scope: ResolvedScope) -> ColumnElement[bool]:
    """把数据范围转换为 `departments.id` 上的 SQL 条件。"""
    if scope.is_unrestricted_departments:
        return true()
    if scope.denies_all_departments:
        return false()
    assert scope.department_ids is not None  # 由 ResolvedScope 不变量保证
    return Department.id.in_(sorted(scope.department_ids))


def user_scope_condition(scope: ResolvedScope) -> ColumnElement[bool]:
    """把数据范围转换为 `admin_users` 上的 SQL 条件。

    SELF 语义说明：SELF 只返回操作者本人这一条记录，
    **不叠加部门条件**（避免放大为"本部门用户"）；
    也不做交集（避免操作者未分配部门时连自己都查不到）。
    """
    if scope.restrict_to_actor:
        assert scope.actor_id is not None  # 由 ResolvedScope 不变量保证
        return AdminUser.id == scope.actor_id

    if scope.is_unrestricted_departments:
        return true()
    if scope.denies_all_departments:
        return false()
    assert scope.department_ids is not None
    return AdminUser.department_id.in_(sorted(scope.department_ids))


__all__ = ["department_scope_condition", "user_scope_condition"]
