"""测试数据构造辅助。

显式指定 `id`：主键默认由 Snowflake 生成，但测试需要可预测的 ID
（Spec `07 §2` 允许显式传入，`07 §10` Seed 亦依赖该能力）。

Phase 3 追加：权限资源、角色授权、字段授权、角色继承、Menu→Page 关联。
这些工厂**直接写库**（绕过 Service 的授权与形状校验），
目的是让测试可以构造"服务层本不该产生的"数据形态 ——
例如角色继承的环、非 CUSTOM 角色残留的 CUSTOM 部门行 ——
从而验证**读路径**的环路安全与 fail-closed 行为。

Phase 4 追加：会话工厂（`make_session`）与真实口令哈希（`password_hash_for`）。
`make_session` 接收**明文**令牌并在内部做 SHA-256，
使"库里只有哈希"这一安全性质在任何用例中都成立。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import DataScope
from app.core.security.password import get_password_hasher
from app.core.security.token import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL, hash_token
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
    SessionRevokeReason,
    UserRole,
    UserSession,
)
from app.models.enums import DepartmentStatus, RoleStatus, UserStatus


def password_hash_for(password: str) -> str:
    """用真实的 argon2id 哈希器生成口令哈希（供认证测试使用）。

    认证测试必须走真实哈希：若测试自己塞一个假哈希，
    `PasswordHasher.verify` 会因"哈希格式非法"而恒返回 False，
    于是"口令正确"的用例会以"登录失败"告终 ——
    这种测试看似通过（断言了失败），实际什么都没验证。
    """
    return get_password_hasher().hash(password)


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
    password_hash: str = "argon2id-placeholder",  # noqa: S107 - 测试占位，非真实口令
    password: str | None = None,
    password_changed_at: datetime | None = None,
    must_change_password: bool = False,
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
) -> AdminUser:
    """创建用户（直接写库，不走 Service）。

    `password` 是便利参数：传入**明文**口令时自动用真实的 argon2id 哈希
    （`app.core.security.password`）生成 `password_hash`，
    供认证测试使用 —— 认证必须走真实哈希校验，不能拿占位串糊过去。

    `password_changed_at` 默认 **None**，即"改密时间未知"。
    按 `is_password_expired` 的口径这会被视为**已过期**（fail-closed），
    因此认证相关用例应显式传入 `utc_now()` 表示"刚改过密码"。
    """
    resolved_hash = password_hash_for(password) if password is not None else password_hash
    user = AdminUser(
        id=user_id,
        username=username,
        password_hash=resolved_hash,
        display_name=username,
        department_id=department_id,
        status=status,
        failed_login_count=failed_login_count,
        locked_until=locked_until,
        password_changed_at=password_changed_at,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.flush()
    return user


async def make_session(
    session: AsyncSession,
    *,
    session_id: int,
    user_id: int,
    access_token: str,
    refresh_token: str,
    login_at: datetime,
    access_ttl: timedelta = ACCESS_TOKEN_TTL,
    refresh_ttl: timedelta = REFRESH_TOKEN_TTL,
    ip: str | None = None,
    user_agent: str | None = None,
    device: str | None = None,
    revoked_at: datetime | None = None,
    revoke_reason: SessionRevokeReason | None = None,
) -> UserSession:
    """创建会话（直接写库，不走 Service）。

    传**明文**令牌、内部存 SHA-256：这样测试可以像真实客户端一样持有令牌，
    同时保证"库里没有明文"这一性质在任何用例里都成立
    （若测试自己塞哈希，就测试不出实现是否忘了哈希）。
    """
    user_session = UserSession(
        id=session_id,
        user_id=user_id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        login_at=login_at,
        last_active_at=login_at,
        expires_at=login_at + access_ttl,
        refresh_expires_at=login_at + refresh_ttl,
        ip=ip,
        user_agent=user_agent,
        device=device,
        revoked_at=revoked_at,
        revoke_reason=revoke_reason,
    )
    session.add(user_session)
    await session.flush()
    return user_session


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
    "make_session",
    "make_user",
    "password_hash_for",
]
