"""数据范围 → SQL 条件的关键转换点。

Frozen 依据
-----------
Spec `10 §10`：所有带数据范围的查询必须在 Service/Repository 层真正约束；
禁止"先查询全部，再在 Python 内存中随意过滤"；
对敏感数据应尽量让 DB query 本身带 scope 条件。

因此数据范围**只允许**通过本模块转换成 SQL 条件，
不允许任何调用方自行拼 `department_id`（AGENTS.md §5.1）。

四个关键安全性质
--------------
1. **fail-closed**：空部门集合必须翻译为 `FALSE`，
   而不是"忽略条件"。忽略条件等于把空范围升级为全局范围。
2. **SELF 不与部门条件取并集**：SELF（`restrict_to_actor`）的用户维度条件
   严格为 `id = actor_id`。若改为 `id = actor OR department_id IN (...)`，
   会把"仅本人"放大为"本部门所有人"，属典型越权。
3. **`include_self` 只做加法**：它来自 DD-19 的"SELF ∪ 其他策略"合并结果，
   语义是"在部门集合之外**额外**包含本人"。
   它与性质 2 不冲突 —— 性质 2 约束的是 SELF 单独存在的情形；
   `include_self` 从不放宽部门维度，只增加本人这一条记录。
4. **永不接受 None 语义的"部门条件"**：`ResolvedScope` 已通过不变量
   保证只有 ALL 才允许 `department_ids=None`。

⚠️ 性质 1 与 3 的组合是易错点：空部门集合 + `include_self=True`
必须返回 `id = actor_id`，**不能**返回 `FALSE`（那会让只持有 SELF
角色的用户连自己都查不到），也**不能**返回 `true()`（那是全局越权）。
`tests/test_scope_guard.py` 对这两种退化方向都有专门用例。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, false, or_, true

from app.core.scope import ResolvedScope
from app.models.department import Department
from app.models.user import AdminUser


def department_scope_condition(scope: ResolvedScope) -> ColumnElement[bool]:
    """把数据范围转换为 `departments.id` 上的 SQL 条件。

    `include_self` 在本函数**不产生任何放宽**：
    部门维度不存在"包含本人"这种概念（本人不是一个部门）。
    """
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
        # 空部门集合 + include_self：连自己都要能看到，但绝不能返回 true()
        if scope.include_self:
            assert scope.actor_id is not None
            return AdminUser.id == scope.actor_id
        return false()

    assert scope.department_ids is not None
    department_condition = AdminUser.department_id.in_(sorted(scope.department_ids))
    if scope.include_self:
        assert scope.actor_id is not None
        return or_(department_condition, AdminUser.id == scope.actor_id)
    return department_condition


__all__ = ["department_scope_condition", "user_scope_condition"]
