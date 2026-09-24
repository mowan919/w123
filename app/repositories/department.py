"""部门数据访问。

设计要点
-------
1. **范围下推到 SQL**（Spec 10 §10）：`list_in_scope` 直接把
   `ResolvedScope` 转换为 WHERE 条件，绝不在 Python 里过滤。
2. **子树展开用递归 CTE**（Spec 07 §9 parent-child index）：
   `descendant_ids` / `count_users_in_subtree` 均单条 SQL 完成，
   不把整棵树拉进内存。
3. **递归使用 `UNION`（非 `UNION ALL`）**：天然去重，因而对数据中的
   父子环具备终止性 —— 即使 Service 的环检测被绕过，查询也不会无限递归。
4. 所有查询默认排除 `deleted_at IS NOT NULL`（Spec 00 §6 / 02 §5）。
"""

from __future__ import annotations

from sqlalchemy import CTE, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import ResolvedScope
from app.models.department import Department
from app.models.user import AdminUser
from app.repositories.scope_filters import department_scope_condition


class DepartmentRepository:
    """部门仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 单条读取
    # ------------------------------------------------------------------
    async def get(self, department_id: int, *, include_deleted: bool = False) -> Department | None:
        """按 ID 读取部门；默认排除逻辑删除。"""
        stmt = select(Department).where(Department.id == department_id)
        if not include_deleted:
            stmt = stmt.where(Department.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, department_code: str) -> Department | None:
        """按编码读取**未删除**部门（用于唯一性预校验）。"""
        stmt = select(Department).where(
            Department.department_code == department_code,
            Department.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add(self, department: Department) -> Department:
        """新增部门并 flush（拿到数据库生成的约束校验结果）。"""
        self._session.add(department)
        await self._session.flush()
        return department

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------
    async def list_in_scope(self, scope: ResolvedScope) -> list[Department]:
        """列出范围内的部门（未删除）。

        范围条件在 SQL 中生效；`denies_all_departments` 时返回空列表。
        """
        stmt = (
            select(Department)
            .where(Department.deleted_at.is_(None), department_scope_condition(scope))
            .order_by(Department.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # 递归查询
    # ------------------------------------------------------------------
    def _subtree_cte(self, root_id: int) -> CTE:
        """构造"以 root 为根、仅未删除节点"的子树递归 CTE。

        `union`（去重）而非 `union_all`：数据出现环时可自然终止。
        """
        base = (
            select(Department.id.label("id"))
            .where(Department.id == root_id, Department.deleted_at.is_(None))
            .cte("dept_subtree", recursive=True)
        )
        children = (
            select(Department.id)
            .join(base, Department.parent_id == base.c.id)
            .where(Department.deleted_at.is_(None))
        )
        return base.union(children)

    async def descendant_ids(self, root_id: int, *, include_self: bool = True) -> frozenset[int]:
        """返回 root 的全部后代部门 ID（未删除）。"""
        subtree = self._subtree_cte(root_id)
        stmt = select(subtree.c.id)
        if not include_self:
            stmt = stmt.where(subtree.c.id != root_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return frozenset(rows)

    async def ancestor_ids(self, department_id: int) -> tuple[int, ...]:
        """返回从直接父级到根的祖先链（含被逻辑删除的节点，用于环检测）。"""
        base = (
            select(Department.id.label("id"), Department.parent_id.label("parent_id"))
            .where(Department.id == department_id)
            .cte("dept_ancestors", recursive=True)
        )
        parent = select(Department.id, Department.parent_id).join(
            base, Department.id == base.c.parent_id
        )
        ancestors = base.union(parent)
        stmt = select(ancestors.c.parent_id).where(ancestors.c.parent_id.is_not(None))
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(rows)

    # ------------------------------------------------------------------
    # 完整性检查（部门删除 / 用户归属）
    # ------------------------------------------------------------------
    async def count_children(self, department_id: int) -> int:
        """未删除的直接子部门数量。"""
        stmt = (
            select(func.count())
            .select_from(Department)
            .where(
                Department.parent_id == department_id,
                Department.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_users(self, department_id: int) -> int:
        """该部门（不含子部门）下未删除的用户数量。"""
        stmt = (
            select(func.count())
            .select_from(AdminUser)
            .where(
                AdminUser.department_id == department_id,
                AdminUser.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def exists_user_in_subtree(self, root_id: int) -> bool:
        """子树内（含自身）是否存在未删除用户。

        单条 SQL 完成，不拉取用户列表。
        """
        subtree = self._subtree_cte(root_id)
        stmt = (
            select(func.count())
            .select_from(AdminUser)
            .join(subtree, AdminUser.department_id == subtree.c.id)
            .where(AdminUser.deleted_at.is_(None))
        )
        return int((await self._session.execute(stmt)).scalar_one()) > 0

    async def search_ids_by_name(self, keyword: str, *, limit: int = 50) -> list[int]:
        """按名称模糊检索部门 ID（大小写不敏感）。

        仅返回 ID，便于调用方与范围条件做交集；
        不做任何授权判断。
        """
        pattern = f"%{keyword}%"
        stmt = (
            select(Department.id)
            .where(
                Department.deleted_at.is_(None),
                or_(
                    Department.department_name.ilike(pattern),
                    Department.department_code.ilike(pattern),
                ),
            )
            .order_by(Department.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def existing_ids(self, department_ids: frozenset[int]) -> frozenset[int]:
        """返回给定集合中**存在且未删除**的部门 ID。

        供引用完整性校验使用（例如 CUSTOM 数据范围引用的部门）。
        只做存在性判断，不做任何授权判断。
        """
        if not department_ids:
            return frozenset()
        stmt = select(Department.id).where(
            Department.id.in_(sorted(department_ids)),
            Department.deleted_at.is_(None),
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())


__all__ = ["DepartmentRepository"]
