"""测试数据构造辅助。

显式指定 `id`：主键默认由 Snowflake 生成，但测试需要可预测的 ID
（Spec `07 §2` 允许显式传入，`07 §10` Seed 亦依赖该能力）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminUser, Department, Role, UserRole
from app.models.enums import DepartmentStatus, RoleStatus, UserStatus


async def make_department(
    session: AsyncSession,
    *,
    department_id: int,
    department_code: str,
    department_name: str | None = None,
    parent_id: int | None = None,
    status: DepartmentStatus = DepartmentStatus.ACTIVE,
) -> Department:
    """创建部门（直接写库，不走 Service）。"""
    department = Department(
        id=department_id,
        parent_id=parent_id,
        department_code=department_code,
        department_name=department_name or f"部门-{department_code}",
        status=status,
    )
    session.add(department)
    await session.flush()
    return department


async def make_user(
    session: AsyncSession,
    *,
    user_id: int,
    username: str,
    department_id: int | None = None,
    status: UserStatus = UserStatus.ACTIVE,
    password_hash: str = "argon2id-placeholder",  # noqa: S107  # 测试占位，非真实口令
) -> AdminUser:
    """创建用户（直接写库，不走 Service）。"""
    user = AdminUser(
        id=user_id,
        username=username,
        password_hash=password_hash,
        display_name=username,
        department_id=department_id,
        status=status,
        failed_login_count=0,
        must_change_password=False,
    )
    session.add(user)
    await session.flush()
    return user


async def make_role(
    session: AsyncSession,
    *,
    role_id: int,
    role_code: str,
    role_name: str | None = None,
    status: RoleStatus = RoleStatus.ACTIVE,
) -> Role:
    """创建角色（与角色业务无关，仅供关联测试使用）。"""
    role = Role(
        id=role_id,
        role_code=role_code,
        role_name=role_name or f"角色-{role_code}",
        status=status,
    )
    session.add(role)
    await session.flush()
    return role


async def link_user_role(session: AsyncSession, *, user_id: int, role_id: int) -> None:
    """建立用户-角色关联。"""
    session.add(UserRole(user_id=user_id, role_id=role_id))
    await session.flush()


__all__ = ["link_user_role", "make_department", "make_role", "make_user"]
