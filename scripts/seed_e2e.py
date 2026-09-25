"""E2E 三角色种子数据（FE-12 §4）。

背景
----
`docs/verification/` 里的 E2E 需要至少三个真实角色：
SUPER_ADMIN / DEPARTMENT_ADMIN / 普通用户。后端契约一旦没有这三份数据，
`/auth/permissions` 返回空集合，测试无从判定"有权限"与"没权限"的差别
（两者都是空，等于测了个寂寞）。

本脚本只负责**写哪些行**：数据清单来自 `scripts/seed_data.py`，写入实现来自
`scripts/seed_common.py`。它自己的部分只有"E2E 专用用户"（含可复现口令）。

口令策略（唯一判定点 `app.core.security.password`）要求 ≥ 12 字符。

用法
----
    .venv\\Scripts\\python.exe scripts\\seed_e2e.py            # 不存在则写入
    .venv\\Scripts\\python.exe scripts\\seed_e2e.py --reset   # 先清再写（幂等重置）
    .venv\\Scripts\\python.exe scripts\\seed_e2e.py --unseed  # 只按业务键撤销本脚本写过的行
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seed_common import (  # noqa: E402
    grant_role_permissions,
    seed_admin_user,
    seed_departments,
    seed_resources,
    seed_roles,
)
from seed_data import (  # noqa: E402
    ALL_RESOURCE_CODES,
    DEPARTMENTS,
    ROLE_CODES,
    ROLES,
)
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.permission import (  # noqa: E402  # noqa: E402
    MenuPage,
    PermissionResource,
    RoleFieldPermission,
    RolePermission,
)
from app.models.role import Role, UserRole  # noqa: E402
from app.models.session import SessionRefreshTokenHistory, UserSession  # noqa: E402
from app.models.user import AdminUser  # noqa: E402

# ---------------------------------------------------------------- E2E 专用用户

#: (username, password, display name, role_code, department_code)
#:
#: 口令属于**测试环境专用**，随代码进版本库是刻意的（E2E 要靠它复现），
#: 但**绝不能**被"生成初始数据"那一路复用 —— 生产兜底账号走 `seed_init.py`。
USERS: list[tuple[str, str, str, str, str]] = [
    ("admin", "E2e@Super2026", "系统管理员", "SUPER_ADMIN", "ROOT"),
    ("deptadmin", "E2e@Dept2026", "部门管理员", "DEPARTMENT_ADMIN", "TECH"),
    ("viewer", "E2e@Viewer2026", "只读用户", "VIEWER", "TECH"),
]

USER_CODES: list[str] = [entry[0] for entry in USERS]


# ---------------------------------------------------------------- 写入


async def reset(session: AsyncSession) -> None:
    """按 FK 依赖顺序清空本次要写的表。

    ⚠️ 这是**全表清空**，与测试套件共用同一个库时先读
    `docs/DESIGN-DECISIONS.md §18.3`（OPERATION-11-01）：在测试库上跑一次，
    下一轮 pytest 会以四百多个失败开场。要还原请用 `--unseed`。

    `UserSession` 必须在 `AdminUser` **之前** —— 会话表的 `user_id` 是
    RESTRICT 外键，先删用户会直接撞 `RestrictViolationError`（实测）。
    `SessionRefreshTokenHistory` 同理挂在会话之下。
    """
    # 顺序由外键约束决定，不是随意排的：这几个关联表的 FK 都是
    # `ondelete="RESTRICT"`（见 `app/models/permission.py`），顺序错了直接撞
    # `RestrictViolationError`。删父表之前先把子表清干净。
    for table in (
        SessionRefreshTokenHistory,
        UserSession,
        UserRole,
        MenuPage,
        RoleFieldPermission,
        RolePermission,
        Department,
        AdminUser,
        Role,
        PermissionResource,
    ):
        await session.execute(delete(table))
    await session.commit()


async def seed() -> int:
    factory = get_session_factory()
    async with factory() as session:
        if (
            await session.execute(select(Role.id).where(Role.role_code == "SUPER_ADMIN"))
        ).scalar_one_or_none() is not None:
            print("种子数据已存在，跳过（需要重置请加 --reset）")
            return 0

        # 解包：三个 seed_* 现在返回 `(映射, 本次新建行数)`。
        # 只取第一项时别用 `dept_id, _ =` 之外的写法 —— 下面要用到的就是映射。
        dept_map, _dept_created = await seed_departments(session)
        resource_map, _resource_created = await seed_resources(session)
        role_map, _role_created = await seed_roles(session)
        # 授权映射（ROLE_PAGES / ROLE_BUTTONS / ROLE_APIS / ROLE_FIELDS）的实现
        # 在 seed_common，与 `seed_init.py` 同源，不会两边漂移。
        await grant_role_permissions(session, role_id=role_map, resource_id=resource_map)

        user_created = 0
        for username, password, display_name, role_code, dept in USERS:
            if dept not in dept_map:
                msg = f"部门 {dept} 不存在，无法为用户 {username} 归属"
                raise SystemExit(msg)
            created = await seed_admin_user(
                session,
                username=username,
                password=password,
                display_name=display_name,
                role_code=role_code,
                role_id=role_map,
                dept_id=dept_map[dept],
            )
            user_created += 1 if created else 0

        await session.commit()

    print(f"种子写入完成：部门 {len(DEPARTMENTS)}、角色 {len(ROLES)}、用户 {user_created}")
    for username, password, *_ in USERS:
        print(f"  {username} / {password}")
    return 0


async def unseed(session: AsyncSession) -> int:
    """删除本脚本写过的行，把库还原到种子之前的状态。

    存在的理由：`--reset` 是**全表清空**，而本脚本与测试套件共用同一个库。
    `tests/conftest.py` 自己往同样的表里塞夹具（例如
    `test_session_management.py` 会建一个固定 `role_code="SUPER_ADMIN"` 的角色）
    并且**期望库里没有同名行**。清库动作之后必须能把这份种子原样撤掉。

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
        (await session.execute(select(Role.id).where(Role.role_code.in_(ROLE_CODES)))).scalars()
    )
    user_id = set(
        (
            await session.execute(select(AdminUser.id).where(AdminUser.username.in_(USER_CODES)))
        ).scalars()
    )

    # 顺序同 FK 依赖：先删依赖方，再删被依赖方。
    await session.execute(delete(SessionRefreshTokenHistory))
    if user_id:
        await session.execute(delete(UserSession).where(UserSession.user_id.in_(user_id)))
        await session.execute(delete(UserRole).where(UserRole.user_id.in_(user_id)))
        await session.execute(delete(AdminUser).where(AdminUser.id.in_(user_id)))
    # 同样受 RESTRICT 约束：删父之前先清子。
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
    await session.execute(
        delete(Department).where(
            Department.department_code.in_([entry[0] for entry in DEPARTMENTS])
        )
    )
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
