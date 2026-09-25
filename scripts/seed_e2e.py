"""E2E 三角色种子数据（FE-12 §4）。

背景
----
`docs/verification/` 里的 E2E 需要至少三个真实角色：
SUPER_ADMIN / DEPARTMENT_ADMIN / 普通用户。后端契约一旦没有这三份数据，
`/auth/permissions` 返回空集合，测试无从判定"有权限"与"没权限"的差别
（两者都是空，等于测了个寂寞）。

本脚本只做一件事：把这三份**可被前端消费**的最小权限集写进库。
它不实现任何业务规则，全部取值与后端契约保持一致：

- 资源编码沿用后端 `permission_resources.resource_code`；
- PAGE 必须同时具备 `route_path` 与 `component_path`
  （`ck_permission_resources_resource_type_fields` 冻结要求，
  前端 `generateRoutes` 也只认 `component_path`）；
- 字段权限用 `role_field_permissions.access_level` 四级取值（DD-06）；
- 数据范围写 `roles.data_scope`（DD-07）。

口令策略（唯一判定点 `app.core.security.password`）要求 ≥ 12 字符。

用法
----
    .venv\\Scripts\\python.exe scripts\\seed_e2e.py            # 不存在则写入
    .venv\\Scripts\\python.exe scripts\\seed_e2e.py --reset   # 先清再写（幂等重置）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.scope import DataScope  # noqa: E402
from app.core.security.password import (  # noqa: E402
    get_password_hasher,
    validate_password_policy,
)
from app.db.base import utc_now  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.enums import (  # noqa: E402
    DepartmentStatus,
    FieldAccessLevel,
    PermissionResourceType,
    PermissionStatus,
    RoleStatus,
    UserStatus,
)
from app.models.permission import (  # noqa: E402
    MenuPage,
    PermissionResource,
    RoleFieldPermission,
    RolePermission,
)
from app.models.role import Role, UserRole  # noqa: E402
from app.models.session import SessionRefreshTokenHistory, UserSession  # noqa: E402
from app.models.user import AdminUser  # noqa: E402

# ---------------------------------------------------------------- 数据定义

DEPARTMENTS: list[tuple[str, str, str | None]] = [
    # (code, name, parent_code)
    ("ROOT", "集团", None),
    ("TECH", "技术部", "ROOT"),
    ("MARKET", "市场部", "ROOT"),
]

ROLES: list[tuple[str, str, DataScope, str]] = [
    ("SUPER_ADMIN", "超级管理员", DataScope.ALL, "拥有全部资源的访问权"),
    ("DEPARTMENT_ADMIN", "部门管理员", DataScope.DEPARTMENT_CHILDREN, "仅本部门及下级"),
    ("VIEWER", "只读用户", DataScope.SELF, "只读，字段大多 HIDDEN"),
]

USERS: list[tuple[str, str, str, str, str]] = [
    # username, password, display name, role_code, department_code
    ("admin", "E2e@Super2026", "系统管理员", "SUPER_ADMIN", "ROOT"),
    ("deptadmin", "E2e@Dept2026", "部门管理员", "DEPARTMENT_ADMIN", "TECH"),
    ("viewer", "E2e@Viewer2026", "只读用户", "VIEWER", "TECH"),
]

#: 前端 `VIEW_REGISTRY` 的十个页面。
#: `component_path` 必须与注册表键一致，否则动态路由会跳过它。
PAGES: list[tuple[str, str, str, str, int]] = [
    ("system:user:page", "用户管理", "/system/users", "system/user", 10),
    ("system:department:page", "部门管理", "/system/departments", "system/department", 20),
    ("system:role:page", "角色管理", "/system/roles", "system/role", 30),
    ("system:permission:page", "权限配置", "/system/permissions", "system/permission", 40),
    (
        "system:permission-resource:page",
        "权限资源",
        "/system/permission-resources",
        "system/permission-resource",
        50,
    ),
    ("system:session:page", "会话管理", "/system/sessions", "system/session", 60),
    ("system:dictionary:page", "字典管理", "/system/dictionaries", "system/dictionary", 70),
    ("system:param:page", "系统参数", "/system/params", "system/param", 80),
    ("system:audit-log:page", "审计日志", "/system/audit-logs", "system/audit-log", 90),
    ("system:trace:page", "链路查询", "/system/traces", "system/trace", 100),
]

#: (code, name, page_code) —— 按钮挂在其所属 PAGE 下（DD-20：BUTTON.parent_id 必填且指向 PAGE）。
BUTTONS: list[tuple[str, str, str]] = [
    ("user:create", "新增用户", "system:user:page"),
    ("user:update", "编辑用户", "system:user:page"),
    ("user:delete", "删除用户", "system:user:page"),
    ("user:reset-password", "重置口令", "system:user:page"),
    ("department:create", "新增部门", "system:department:page"),
    ("department:update", "编辑部门", "system:department:page"),
    ("role:create", "新增角色", "system:role:page"),
    ("role:update", "编辑角色", "system:role:page"),
    ("dictionary:create", "新增字典", "system:dictionary:page"),
]

#: (code, name, method, path, page_code)
#:
#: ⚠️ **code 必须与 `app.services.authorization.ApiPermissionCode` 逐字一致。**
#: 端点用 `require_api_permission(ApiPermissionCode.USER_MANAGE)` 声明所需编码，
#: 判定的依据就是这一列。曾经这里写的是自造的 `api:user:list` / `api:user:create`，
#: 没有任何端点认它们 —— 后果是"授权界面上明明勾了"的角色照样 403。
#: 更麻烦的是报错信息只会说"缺少 USER_MANAGE"，看不出是自造编码没对上。
#: 权限码唯一键是 `(resource_type, resource_code)`，所以每个码只写一行。
#:
#: path 取**后端相对路径**（`/admin/...`），不含 `/api/v1` 前缀。
APIS: list[tuple[str, str, str, str, str]] = [
    ("USER_MANAGE", "用户管理（读/写）", "GET", "/admin/users", "system:user:page"),
    (
        "DEPARTMENT_MANAGE",
        "部门管理（读/写）",
        "GET",
        "/admin/departments",
        "system:department:page",
    ),
    ("ROLE_MANAGE", "角色管理（读/写）", "GET", "/admin/roles", "system:role:page"),
    (
        "SESSION_MANAGE",
        "会话管理（查看/踢下线）",
        "GET",
        "/admin/sessions",
        "system:session:page",
    ),
    ("DICT_MANAGE", "字典管理（读/写）", "GET", "/admin/dicts", "system:dictionary:page"),
    ("PARAM_MANAGE", "系统参数（读/写）", "GET", "/admin/params", "system:param:page"),
    ("AUDIT_READ", "审计日志查询", "GET", "/admin/audit/logs", "system:audit-log:page"),
    ("TRACE_READ", "链路查询", "GET", "/admin/traces", "system:trace:page"),
    (
        "PERMISSION_RESOURCE_MANAGE",
        "权限资源管理",
        "GET",
        "/admin/permission-resources",
        "system:permission-resource:page",
    ),
]

#: (field_key, page_code)
FIELDS: list[tuple[str, str]] = [
    ("phone", "system:user:page"),
    ("email", "system:user:page"),
    ("remark", "system:user:page"),
    ("department_name", "system:department:page"),
]

#: 菜单（导航层级），code 沿用前端 `menuTree` 的父子约定。
MENUS: list[tuple[str, str, str | None, str | None, int]] = [
    ("system:system", "系统管理", None, "setting", 10),
    ("system:user", "用户管理", "system:system", None, 20),
    ("system:department", "部门管理", "system:system", None, 30),
    ("system:role", "角色管理", "system:system", None, 40),
    ("system:permission", "权限配置", "system:system", None, 50),
    ("system:session", "会话管理", "system:system", None, 60),
    ("system:dictionary", "字典管理", "system:system", None, 70),
    ("system:param", "系统参数", "system:system", None, 80),
    ("system:audit-log", "审计日志", "system:system", None, 90),
    ("system:trace", "链路查询", "system:system", None, 100),
]

#: 角色 → 可见页面。VIEWER 刻意看不到"权限配置 / 系统参数 / 审计日志"。
ROLE_PAGES: dict[str, list[str]] = {
    "SUPER_ADMIN": [page[0] for page in PAGES],
    "DEPARTMENT_ADMIN": [
        "system:user:page",
        "system:department:page",
        "system:role:page",
        "system:session:page",
    ],
    "VIEWER": ["system:user:page", "system:department:page"],
}

#: 角色 → 授权按钮。
ROLE_BUTTONS: dict[str, list[str]] = {
    "SUPER_ADMIN": [button[0] for button in BUTTONS],
    "DEPARTMENT_ADMIN": ["user:create", "user:update", "department:create", "department:update"],
    "VIEWER": [],
}

#: 角色 → 授权接口。
#:
#: VIEWER **一个接口都不给** —— 只读用户不该碰管理面。这样 `GET /admin/users`
#: 在三个角色下的结果必然不同（超管 200 全量 / 部门管理员 200 范围内 / 只读 403），
#: 而"三个角色同一请求给出三种结果"正是 FE-12 §4 要求的判据：
#: 只要有一个角色拿到 200，另外两个也让 200，这个 E2E 就等于没测。
ROLE_APIS: dict[str, list[str]] = {
    "SUPER_ADMIN": [api[0] for api in APIS],
    "DEPARTMENT_ADMIN": ["USER_MANAGE", "DEPARTMENT_MANAGE"],
    "VIEWER": [],
}

#: 角色 → 字段权限（DD-06 四级）。
ROLE_FIELDS: dict[str, dict[str, FieldAccessLevel]] = {
    "SUPER_ADMIN": {
        "phone": FieldAccessLevel.READ_ONLY,
        "email": FieldAccessLevel.EDITABLE,
        "remark": FieldAccessLevel.EDITABLE,
        "department_name": FieldAccessLevel.EDITABLE,
    },
    # 部门管理员能看到联系方式，但不能改。
    "DEPARTMENT_ADMIN": {
        "phone": FieldAccessLevel.VISIBLE,
        "email": FieldAccessLevel.VISIBLE,
        "remark": FieldAccessLevel.READ_ONLY,
        "department_name": FieldAccessLevel.READ_ONLY,
    },
    # 只读用户：可见但不改，敏感字段直接 HIDDEN。
    "VIEWER": {
        "phone": FieldAccessLevel.HIDDEN,
        "email": FieldAccessLevel.HIDDEN,
        "remark": FieldAccessLevel.READ_ONLY,
        "department_name": FieldAccessLevel.READ_ONLY,
    },
}


# ---------------------------------------------------------------- 写入


async def reset(session: AsyncSession) -> None:
    """按 FK 依赖顺序清空本次要写的表。

    `UserSession` 必须在 `AdminUser` **之前** —— 会话表的 `user_id` 是 RESTRICT
    外键，先删用户会直接撞 `RestrictViolationError`（实测）。
    `SessionRefreshTokenHistory` 同理挂在会话之下。
    """
    for table in (
        SessionRefreshTokenHistory,
        UserSession,
        UserRole,
        RoleFieldPermission,
        RolePermission,
        MenuPage,
        PermissionResource,
        AdminUser,
        UserRole,
        Role,
        Department,
    ):
        await session.execute(delete(table))
    await session.commit()


async def seed() -> int:
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(Role.id).where(Role.role_code == "SUPER_ADMIN"))
        ).scalar_one_or_none()
        if existing is not None:
            print("种子数据已存在，跳过（需要重置请加 --reset）")
            return 0

        # ---- 部门 ----
        dept_id: dict[str, int] = {}
        for code, name, parent_code in DEPARTMENTS:
            dept_row = Department(
                department_code=code,
                department_name=name,
                parent_id=dept_id.get(parent_code) if parent_code else None,
                status=DepartmentStatus.ACTIVE,
            )
            session.add(dept_row)
            await session.flush()
            dept_id[code] = dept_row.id

        # ---- 资源 ----
        resource_id: dict[tuple[str, str], int] = {}

        # 类型专属列的默认值：类型不符的列一律留空，
        # 由 `ck_permission_resources_resource_type_fields` .Database 兜底拒绝形状错误的数据。
        defaults: dict[str, object] = {
            "status": PermissionStatus.ACTIVE,
            "sort_order": 0,
            "parent_id": None,
            "route_path": None,
            "component_path": None,
            "icon": None,
            "api_method": None,
            "api_path": None,
            "field_key": None,
            "owner_resource_id": None,
        }

        def add_resource(**kwargs: object) -> PermissionResource:
            # 类型检查器对 **kwargs 展开进构造函数无能为力，这里只需要它
            # 放过这一处；其余每处 ORM 构造都是显式的，不靠 ignore 蒙混。
            resource: PermissionResource = PermissionResource(**{**defaults, **kwargs})
            session.add(resource)
            return resource

        for code, name, route_path, component_path, order in PAGES:
            resource_row = add_resource(
                resource_type=PermissionResourceType.PAGE,
                resource_code=code,
                resource_name=name,
                route_path=route_path,
                component_path=component_path,
                sort_order=order,
            )
            await session.flush()
            resource_id[("PAGE", code)] = resource_row.id

        for code, name, page_code in BUTTONS:
            resource_row = add_resource(
                resource_type=PermissionResourceType.BUTTON,
                resource_code=code,
                resource_name=name,
                parent_id=resource_id[("PAGE", page_code)],
                sort_order=10,
            )
            await session.flush()
            resource_id[("BUTTON", code)] = resource_row.id

        for code, name, method, path, page_code in APIS:
            resource_row = add_resource(
                resource_type=PermissionResourceType.API,
                resource_code=code,
                resource_name=name,
                api_method=method,
                api_path=path,
                parent_id=resource_id[("PAGE", page_code)],
                sort_order=10,
            )
            await session.flush()
            resource_id[("API", code)] = resource_row.id

        for field_key, page_code in FIELDS:
            resource_row = add_resource(
                resource_type=PermissionResourceType.FIELD,
                resource_code=f"field:{field_key}",
                resource_name=field_key,
                field_key=field_key,
                owner_resource_id=resource_id[("PAGE", page_code)],
                sort_order=10,
            )
            await session.flush()
            resource_id[("FIELD", field_key)] = resource_row.id

        # 菜单：parent_id 指向 MENU 类型的资源。
        for code, name, parent_code, icon, order in MENUS:
            resource_row = add_resource(
                resource_type=PermissionResourceType.MENU,
                resource_code=code,
                resource_name=name,
                icon=icon,
                parent_id=resource_id[("MENU", parent_code)] if parent_code else None,
                sort_order=order,
            )
            await session.flush()
            resource_id[("MENU", code)] = resource_row.id

        # MENU ↔ PAGE 关联（一个菜单可关联多个页面）。
        for menu_code, page_code in [
            ("system:user", "system:user:page"),
            ("system:department", "system:department:page"),
            ("system:role", "system:role:page"),
            ("system:permission", "system:permission:page"),
            ("system:session", "system:session:page"),
            ("system:dictionary", "system:dictionary:page"),
            ("system:param", "system:param:page"),
            ("system:audit-log", "system:audit-log:page"),
            ("system:trace", "system:trace:page"),
        ]:
            session.add(
                MenuPage(
                    menu_id=resource_id[("MENU", menu_code)],
                    page_id=resource_id[("PAGE", page_code)],
                )
            )

        # ---- 角色 ----
        role_id: dict[str, int] = {}
        for code, name, scope, description in ROLES:
            role_row = Role(
                role_code=code,
                role_name=name,
                status=RoleStatus.ACTIVE,
                data_scope=scope,
                description=description,
            )
            session.add(role_row)
            await session.flush()
            role_id[code] = role_row.id

        for role_code, granted in ROLE_PAGES.items():
            for page_code in granted:
                session.add(
                    RolePermission(
                        role_id=role_id[role_code],
                        resource_id=resource_id[("PAGE", page_code)],
                    )
                )
                # 菜单随页面一起可见（否则菜单点进去会被守卫拦到 403）。
                #
                # 这里的键必须是**二元组**：`resource_id` 的键全是
                # `("TYPE", code)` 形式（上面每一处赋值都是如此）。曾经写成
                # `if menu_for_page in resource_id` —— 用裸字符串去查一个键为
                # 元组的 dict，结果恒为 False，于是这段授权**一次都没写过**，
                # 页面都给全了却一个菜单都没有。mypy 的
                # `comparison-overlap` 就是冲着这里来的。
                menu_for_page = page_code.replace(":page", "")
                if ("MENU", menu_for_page) in resource_id:
                    session.add(
                        RolePermission(
                            role_id=role_id[role_code],
                            resource_id=resource_id[("MENU", menu_for_page)],
                        )
                    )

        for role_code, granted in ROLE_BUTTONS.items():
            for button_code in granted:
                session.add(
                    RolePermission(
                        role_id=role_id[role_code],
                        resource_id=resource_id[("BUTTON", button_code)],
                    )
                )

        for role_code, granted in ROLE_APIS.items():
            for api_code in granted:
                session.add(
                    RolePermission(
                        role_id=role_id[role_code],
                        resource_id=resource_id[("API", api_code)],
                    )
                )

        for role_code, levels in ROLE_FIELDS.items():
            for field_key, level in levels.items():
                session.add(
                    RoleFieldPermission(
                        role_id=role_id[role_code],
                        field_id=resource_id[("FIELD", field_key)],
                        access_level=level,
                    )
                )

        # ---- 用户 ----
        hasher = get_password_hasher()
        user_id: dict[str, int] = {}
        for username, password, display_name, role_code, dept in USERS:
            violations = validate_password_policy(password)
            if violations:
                msg = f"{username} 的口令不满足策略：{[v.message for v in violations]}"
                raise SystemExit(msg)
            user_row = AdminUser(
                username=username,
                password_hash=hasher.hash(password),
                display_name=display_name,
                department_id=dept_id[dept],
                status=UserStatus.ACTIVE,
                must_change_password=False,
                failed_login_count=0,
                locked_until=None,
                password_changed_at=utc_now(),
            )
            session.add(user_row)
            await session.flush()
            user_id[username] = user_row.id
            session.add(UserRole(user_id=user_row.id, role_id=role_id[role_code]))

        await session.commit()

    print(f"种子写入完成：部门 {len(DEPARTMENTS)}、角色 {len(ROLES)}、用户 {len(USERS)}")
    for username, password, *_ in USERS:
        print(f"  {username} / {password}")
    return 0


#: 本脚本写过的全部资源编码 —— `--unseed` 按业务键还原时要用到。
#:
#: 注意 FIELD 的编码规则是 `field:{key}` 而不是裸 `field_key`，
#: 这里若照抄 `resource_code=field_key`，撤销时会漏掉字段资源。
ALL_RESOURCE_CODES: set[str] = (
    {entry[0] for entry in PAGES}
    | {entry[0] for entry in BUTTONS}
    | {entry[0] for entry in APIS}
    | {entry[0] for entry in MENUS}
    | {f"field:{entry[0]}" for entry in FIELDS}
)


async def unseed(session: AsyncSession) -> int:
    """删除本脚本写过的行，把库还原到种子之前的状态。

    存在的理由：`--reset` 是**全表清空**，而本脚本与测试套件共用同一个库。
    `tests/conftest.py` 自己往同样的表里塞夹具（例如
    `test_session_management.py` 会建一个固定 `role_code="SUPER_ADMIN"` 的角色）
    并且**期望库里没有同名行**。在测试库上跑一次 `--reset`，下一轮 pytest
    会以四百多个失败开场 —— 那些失败与代码无关，纯粹是数据被自己清掉了。
    因此清库动作之后必须能把这份种子原样撤掉。

    这里按**业务键**删除，只动本脚本写过的行，其它数据一概不碰。
    """
    resource_id = set(
        (
            await session.execute(
                select(PermissionResource.id).where(
                    PermissionResource.resource_code.in_(ALL_RESOURCE_CODES)
                )
            )
        ).scalars()
    )
    role_id = set(
        (
            await session.execute(
                select(Role.id).where(Role.role_code.in_([entry[0] for entry in ROLES]))
            )
        ).scalars()
    )
    user_id = set(
        (
            await session.execute(
                select(AdminUser.id).where(AdminUser.username.in_([entry[0] for entry in USERS]))
            )
        ).scalars()
    )

    # 顺序同 `reset()`：先删依赖方，再删被依赖方。
    await session.execute(delete(SessionRefreshTokenHistory))
    if user_id:
        await session.execute(delete(UserSession).where(UserSession.user_id.in_(user_id)))
        await session.execute(delete(UserRole).where(UserRole.user_id.in_(user_id)))
        await session.execute(delete(AdminUser).where(AdminUser.id.in_(user_id)))
    if role_id:
        await session.execute(
            delete(RoleFieldPermission).where(RoleFieldPermission.role_id.in_(role_id))
        )
        await session.execute(delete(RolePermission).where(RolePermission.role_id.in_(role_id)))
        await session.execute(delete(Role).where(Role.id.in_(role_id)))
    if resource_id:
        await session.execute(delete(MenuPage).where(MenuPage.menu_id.in_(resource_id)))
        await session.execute(delete(MenuPage).where(MenuPage.page_id.in_(resource_id)))
        await session.execute(
            delete(PermissionResource).where(PermissionResource.id.in_(resource_id))
        )
    dept_codes = [entry[0] for entry in DEPARTMENTS]
    await session.execute(delete(Department).where(Department.department_code.in_(dept_codes)))
    await session.commit()
    print(f"已撤销种子：资源 {len(resource_id)}、角色 {len(role_id)}、用户 {len(user_id)}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="E2E 三角色种子数据")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="先清空相关表再写入（可重复执行）",
    )
    parser.add_argument(
        "--unseed",
        action="store_true",
        help="只撤销本脚本写过的行，不去动其它数据（在测试库上用这个）",
    )
    args = parser.parse_args()

    if args.unseed:
        factory = get_session_factory()
        async with factory() as session:
            return await unseed(session)

    if args.reset:
        factory = get_session_factory()
        async with factory() as session:
            await reset(session)
        print("已清空相关表")

    return await seed()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
