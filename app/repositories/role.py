"""角色与用户-角色关联数据访问。

范围边界（人类已裁定）
--------------------
Phase 2 交付：查询角色、查询用户的角色、整体替换用户角色。

Phase 3 追加：
- DD-07：角色数据范围（`roles.data_scope`）与 CUSTOM 部门集合的读写；
- DD-20：角色 CRUD（创建 / 分页查询 / 逻辑删除）所需的读写；
- DD-19：批量读取"多角色的范围配置"，供有效数据范围求并使用。

**仍不在本模块**：权限资源与授权（`app/repositories/permission.py`）、
角色继承（同前，`RoleInheritanceRepository`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RoleStatus
from app.models.role import Role, RoleCustomScopeDepartment, UserRole

#: `_apply_filters` 的泛型参数：保证过滤后语句的行类型不丢失。
_RowT = TypeVar("_RowT", bound=tuple[Any, ...])


class RoleRepository:
    """角色仓储（查询 + 关联管理 + 数据范围持久化 + CRUD）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 角色
    # ------------------------------------------------------------------
    async def get(self, role_id: int) -> Role | None:
        """按 ID 读取**未删除**角色。"""
        stmt = select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_code(self, role_code: str) -> Role | None:
        """按编码读取**未删除**角色（逻辑删除感知唯一性预校验）。"""
        stmt = select(Role).where(
            Role.role_code == role_code,
            Role.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def add(self, role: Role) -> Role:
        """新增角色并 flush（拿到数据库唯一约束的校验结果）。"""
        self._session.add(role)
        await self._session.flush()
        return role

    async def list_roles(
        self,
        *,
        keyword: str | None = None,
        status: RoleStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[Role]:
        """分页列出未删除角色。"""
        stmt = (
            select(Role)
            .where(Role.deleted_at.is_(None))
            .order_by(Role.id)
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_roles(
        self, *, keyword: str | None = None, status: RoleStatus | None = None
    ) -> int:
        """统计未删除角色数量（与 `list_roles` 同口径）。"""
        stmt = select(func.count()).select_from(Role).where(Role.deleted_at.is_(None))
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _apply_filters(
        stmt: Select[_RowT], *, keyword: str | None, status: RoleStatus | None
    ) -> Select[_RowT]:
        """附加可选过滤条件（供 list / count 共用，保证两者口径一致）。"""
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(or_(Role.role_code.ilike(pattern), Role.role_name.ilike(pattern)))
        if status is not None:
            stmt = stmt.where(Role.status == status)
        return stmt

    async def list_by_ids(self, role_ids: list[int]) -> list[Role]:
        """按 ID 批量读取**未删除**角色。"""
        if not role_ids:
            return []
        stmt = select(Role).where(Role.id.in_(role_ids), Role.deleted_at.is_(None))
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_user(self, user_id: int) -> list[Role]:
        """读取用户当前持有的未删除角色。"""
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.deleted_at.is_(None))
            .order_by(Role.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_active_role_ids_for_user(self, user_id: int) -> frozenset[int]:
        """读取用户持有的**未删除且 ACTIVE** 角色 ID。

        有效权限计算必须只认 ACTIVE 角色：被禁用的角色应立刻失去权限，
        因此不能复用 `list_for_user`（它不筛 status）。
        """
        stmt = (
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.deleted_at.is_(None),
                Role.status == RoleStatus.ACTIVE,
            )
        )
        return frozenset(int(x) for x in (await self._session.execute(stmt)).scalars().all())

    async def list_role_codes_for_user(self, user_id: int) -> frozenset[str]:
        """读取用户持有的角色编码集合（用于集中式 SUPER_ADMIN 判定）。"""
        stmt = (
            select(Role.role_code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.deleted_at.is_(None))
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def list_user_ids_for_role_ids(self, role_ids: list[int]) -> frozenset[int]:
        """反查持有这些角色的用户 ID 集合。"""
        if not role_ids:
            return frozenset()
        stmt = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def count_users_for_roles(self, role_ids: Sequence[int]) -> int:
        """统计这些角色被多少个用户**直接**持有（角色删除前的引用检查）。"""
        if not role_ids:
            return 0
        stmt = (
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.role_id.in_(sorted(set(role_ids))))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_custom_scope_departments_for_roles(
        self, role_ids: Sequence[int]
    ) -> dict[int, frozenset[int]]:
        """批量读取多个角色的 CUSTOM 部门集合。

        供 DD-19 多角色数据范围求并使用：一次性取回，避免 N 次查询。
        只返回**有关联行**的角色；未出现的角色视为空集合。
        """
        if not role_ids:
            return {}
        stmt = select(
            RoleCustomScopeDepartment.role_id,
            RoleCustomScopeDepartment.department_id,
        ).where(RoleCustomScopeDepartment.role_id.in_(sorted(set(role_ids))))
        result: dict[int, set[int]] = {}
        for role_id, department_id in (await self._session.execute(stmt)).all():
            result.setdefault(int(role_id), set()).add(int(department_id))
        return {role_id: frozenset(values) for role_id, values in result.items()}

    async def clear_custom_scope_for_roles(self, role_ids: Sequence[int]) -> None:
        """删除这些角色的全部 CUSTOM 部门关联行（角色被删除时清理）。"""
        if not role_ids:
            return
        await self._session.execute(
            delete(RoleCustomScopeDepartment).where(
                RoleCustomScopeDepartment.role_id.in_(sorted(set(role_ids)))
            )
        )
        await self._session.flush()

    async def delete_user_roles_for_roles(self, role_ids: Sequence[int]) -> None:
        """删除这些角色的用户关联（角色被删除时清理）。

        ⚠️ 只有在**确认没有任何用户直接持有**时才允许调用 ——
        角色删除的业务规则是"有用户持有则拒绝删除"，
        而不是"删掉用户的角色关联"（Spec `03 §4`"删除父角色导致隐式错误"）。
        """
        if not role_ids:
            return
        await self._session.execute(
            delete(UserRole).where(UserRole.role_id.in_(sorted(set(role_ids))))
        )
        await self._session.flush()

    async def replace_user_roles(
        self, user_id: int, role_ids: frozenset[int]
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换用户的角色关联。

        Returns:
            (before, after) 角色 ID 集合，供审计 before_data / after_data 使用。

        说明：关联表按硬删除处理（移除关联即删除该行）。
        理由见 `app.models.role` 的模块说明。
        """
        before = frozenset(
            (
                await self._session.execute(
                    select(UserRole.role_id).where(UserRole.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

        to_remove = before - role_ids
        to_add = role_ids - before

        if to_remove:
            await self._session.execute(
                delete(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id.in_(sorted(to_remove)),
                )
            )
        for role_id in sorted(to_add):
            self._session.add(UserRole(user_id=user_id, role_id=role_id))
        await self._session.flush()

        return before, frozenset(role_ids)

    # ------------------------------------------------------------------
    # 数据范围（DD-07 已冻结）
    # ------------------------------------------------------------------
    async def list_custom_scope_department_ids(self, role_id: int) -> frozenset[int]:
        """读取角色的 CUSTOM 部门集合。"""
        stmt = select(RoleCustomScopeDepartment.department_id).where(
            RoleCustomScopeDepartment.role_id == role_id
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def replace_custom_scope_departments(
        self, role_id: int, department_ids: frozenset[int]
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换角色的 CUSTOM 部门集合。

        Returns:
            (before, after)，供审计 before_data / after_data 使用。
        """
        before = await self.list_custom_scope_department_ids(role_id)
        to_remove = before - department_ids
        to_add = department_ids - before

        if to_remove:
            await self._session.execute(
                delete(RoleCustomScopeDepartment).where(
                    RoleCustomScopeDepartment.role_id == role_id,
                    RoleCustomScopeDepartment.department_id.in_(sorted(to_remove)),
                )
            )
        for department_id in sorted(to_add):
            self._session.add(
                RoleCustomScopeDepartment(role_id=role_id, department_id=department_id)
            )
        await self._session.flush()
        return before, frozenset(department_ids)

    async def clear_custom_scope_departments(self, role_id: int) -> frozenset[int]:
        """清空角色的 CUSTOM 部门集合，返回被清除的集合。

        非 CUSTOM 角色必须调用本方法，避免残留行在角色改回 CUSTOM 时
        造成静默的权限放大（Spec `11 §5`）。
        """
        before = await self.list_custom_scope_department_ids(role_id)
        if before:
            await self._session.execute(
                delete(RoleCustomScopeDepartment).where(
                    RoleCustomScopeDepartment.role_id == role_id
                )
            )
            await self._session.flush()
        return before


__all__ = ["RoleRepository"]
