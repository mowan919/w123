"""测试数据构造辅助。

显式指定 `id`：主键默认由 Snowflake 生成，但测试需要可预测的 ID
（Spec `07 §2` 允许显式传入，`07 §10` Seed 亦依赖该能力）。

Phase 3 追加：权限资源、角色授权、字段授权、角色继承、Menu→Page 关联。
这些工厂**直接写库**（绕过 Service 的授权与形状校验），
目的是让测试可以构造"服务层本不该产生的"数据形态 ——
例如角色继承的环、非 CUSTOM 角色残留的 CUSTOM 部门行 ——
从而验证**读路径**的环路安全与 fail-closed 行为。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import DataScope
from app.models import (
    AdminUser,
    Department,
    FieldAccessLevel,
    MenuPage,
    PermissionResource,
    PermissionResourceType,
    PermissionStatus,
    Role,
    RoleCustomScopeDepartment,
    RoleFieldPermission,
    RoleInheritance,
    RolePermission,
    UserRole,
)
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
    data_scope: DataScope | None = None,
) -> Role:
    """创建角色（与角色业务无关，仅供关联测试使用）。

    `data_scope` 省略时走列默认值（`DEPARTMENT_CHILDREN`），
    以便测试真实依赖"未显式配置时的默认范围"这一行为。
    """
    role = Role(
        id=role_id,
        role_code=role_code,
        role_name=role_name or f"角色-{role_code}",
        status=status,
    )
    if data_scope is not None:
        role.data_scope = data_scope
    session.add(role)
    await session.flush()
    return role


async def link_user_role(session: AsyncSession, *, user_id: int, role_id: int) -> None:
    """建立用户-角色关联。"""
    session.add(UserRole(user_id=user_id, role_id=role_id))
    await session.flush()


async def link_role_custom_scope(
    session: AsyncSession, *, role_id: int, department_id: int
) -> None:
    """写入角色 CUSTOM 数据范围的部门关联。"""
    session.add(RoleCustomScopeDepartment(role_id=role_id, department_id=department_id))
    await session.flush()


async def make_permission_resource(
    session: AsyncSession,
    *,
    resource_id: int,
    resource_type: PermissionResourceType,
    resource_code: str,
    resource_name: str | None = None,
    parent_id: int | None = None,
    sort_order: int = 0,
    status: PermissionStatus = PermissionStatus.ACTIVE,
    **type_specific: Any,
) -> PermissionResource:
    """创建权限资源（直接写库，不走 Service）。

    `type_specific` 用于传入类型专属列
    （`route_path` / `component_path` / `icon` / `api_method` / `api_path` /
    `field_key` / `owner_resource_id`）。
    """
    resource = PermissionResource(
        id=resource_id,
        resource_type=resource_type,
        resource_code=resource_code,
        resource_name=resource_name or resource_code,
        parent_id=parent_id,
        sort_order=sort_order,
        status=status,
        **type_specific,
    )
    session.add(resource)
    await session.flush()
    return resource


async def link_role_permission(session: AsyncSession, *, role_id: int, resource_id: int) -> None:
    """建立角色 → 权限资源授权。"""
    session.add(RolePermission(role_id=role_id, resource_id=resource_id))
    await session.flush()


async def link_role_field_permission(
    session: AsyncSession,
    *,
    role_id: int,
    field_id: int,
    access_level: FieldAccessLevel,
) -> None:
    """建立角色 → 字段资源授权（携带等级）。"""
    session.add(RoleFieldPermission(role_id=role_id, field_id=field_id, access_level=access_level))
    await session.flush()


async def link_role_inheritance(
    session: AsyncSession, *, parent_role_id: int, child_role_id: int
) -> None:
    """建立角色继承关系（child 继承 parent）。

    直接写库，因此可用于构造**环**来验证读路径的环路安全性
    （服务层会拒绝成环，无法通过 API 造出环）。
    """
    session.add(RoleInheritance(parent_role_id=parent_role_id, child_role_id=child_role_id))
    await session.flush()


async def link_menu_page(session: AsyncSession, *, menu_id: int, page_id: int) -> None:
    """建立 Menu → Page 关联。"""
    session.add(MenuPage(menu_id=menu_id, page_id=page_id))
    await session.flush()


__all__ = [
    "link_menu_page",
    "link_role_custom_scope",
    "link_role_field_permission",
    "link_role_inheritance",
    "link_role_permission",
    "link_user_role",
    "make_department",
    "make_permission_resource",
    "make_role",
    "make_user",
]
