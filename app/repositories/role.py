"""角色与用户-角色关联数据访问。

范围边界（人类已裁定）
--------------------
本 Phase 只提供"关联"所需的最小数据访问：
查询角色、查询用户的角色、整体替换用户角色。
**不实现** Role CRUD、权限授予、角色继承
（属后续 Phase；`role_inheritances` 的存储模型 DD-05 未冻结）。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role, UserRole


class RoleRepository:
    """角色仓储（只读 + 关联管理）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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


__all__ = ["RoleRepository"]
