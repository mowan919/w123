"""全新部署的初始数据（`13 §3` 部署顺序里 `alembic upgrade` 之后的那一步）。

为什么需要它
------------
`alembic upgrade head` 之后库里是**空的**：没有部门、没有角色、没有任何权限
资源，也就意味着**没有任何人能登录**，连进管理界面改数据的人都没有。
这个脚本把"一个全新环境从不可用到可用"所必需的那一层骨架补齐。

它补的是**骨架**，不是业务数据
------------------------------
- 一个根部门（真实组织架构请通过管理界面建，脚本不臆造层级）；
- 三个角色 + 一套权限资源 + 授权映射（清单来自 `scripts/seed_data.py`）；
- `user_status` 字典（前端 `labelOf()` 唯一消费的字典码）；
- `mfa.required_default` 参数行（缺失时补，由迁移 seeded 过，已存在则跳过）；
- 初始管理员 —— **口令必须来自环境 / 密钥管理**，缺省则跳过创建。

绝不生成"众所周知的默认口令"
----------------------------
口令策略唯一判定点是 `app.core.security.password.validate_password_policy`，
脚本除了校验它还**要求口令必须由环境变量注入**：`--with-admin` 但环境里没有
`SEED_INIT_ADMIN_PASSWORD` 时直接报错退出，而不是用一个内置口令把账号建出来。
生成出来的账号带 `must_change_password=True`（RISK-001）。

幂等
----
按业务键先查后写，可反复执行，不需要 `--reset`。
`--dry-run` 走**完全相同**的代码路径，只在最后 `rollback()` —— 因此"预演成功"
意味着"真跑也一定成功"，不会出现 dry-run 与实跑两套行为。

用法
----
    .venv\\Scripts\\python.exe scripts\\seed_init.py --dry-run
    .venv\\Scripts\\python.exe scripts\\seed_init.py --with-admin
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seed_common import (  # noqa: E402
    grant_role_permissions,
    seed_admin_user,
    seed_departments,
    seed_mfa_default_param,
    seed_resources,
    seed_roles,
    seed_user_status_dict,
)
from sqlalchemy import text  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402

#: 要归属到初始管理员的部门编码。刻意只挂根部门：真实组织架构交给管理员建，
#: 脚本臆造层级（如"技术部 / 市场部"）会让人误以为这是系统自带的业务数据。
ADMIN_DEPARTMENT_CODE = "ROOT"

#: 缺这些环境变量时的提示，单独成常量便于断言文案。
#:
#: 这两项是**环境变量名**而不是口令；扫描器把名字里带 PASSWORD 的赋值一律
#: 当硬编码口令报警（S105），这里单独关掉这一条。
PASSWORD_ENV = "SEED_INIT_ADMIN_PASSWORD"  # noqa: S105
USERNAME_ENV = "SEED_INIT_ADMIN_USERNAME"


async def run(*, with_admin: bool, apply: bool) -> int:
    """跑完全部种子逻辑；`apply=False` 时在**最后一步**回滚。

    返回 (是否真的提交, 统计行)。
    """
    factory = get_session_factory()

    # 预检：**迁移跑没跑过**，而不是"角色有没有"。
    # 第一版写的是"没有 SUPER_ADMIN 就退出"，结果在**全新库**上永远退出口
    # —— 而全新库恰恰是最需要跑这个脚本的时候。判定跑没跑过只能看表在不在。
    async with factory() as session:
        if (await session.execute(text("SELECT to_regclass('roles')"))).scalar_one() is None:
            print("未发现 roles 表，先执行 `alembic upgrade head`")
            return 1

    async with factory() as session:
        dept_id, dept_created = await seed_departments(session)
        resource_id, resource_created = await seed_resources(session)
        role_id, role_created = await seed_roles(session)
        await grant_role_permissions(session, role_id=role_id, resource_id=resource_id)

        # 先归零：`--with-admin` 之外的分支不会进下面的 if，放在里面会在
        # 汇总时变成 `UnboundLocalError`（ dry-run 时最容易撞到）。
        user_created = False
        if with_admin:
            username = os.environ.get(USERNAME_ENV, "admin")
            password = os.environ.get(PASSWORD_ENV)
            if not password:
                msg = (
                    f"未提供 {PASSWORD_ENV}，拒绝创建初始管理员。\n"
                    f"  生成口令请用密钥管理产出（≥12 字符，满足 "
                    f"`validate_password_policy`），然后：\n"
                    f"    {USERNAME_ENV}={username} {PASSWORD_ENV}=… "
                    f"python scripts/seed_init.py --with-admin"
                )
                raise SystemExit(msg)
            user_created = await seed_admin_user(
                session,
                username=username,
                password=password,
                display_name="系统管理员",
                role_code="SUPER_ADMIN",
                role_id=role_id,
                dept_id=dept_id.get(ADMIN_DEPARTMENT_CODE),
            )

        _, dict_created = await seed_user_status_dict(session)
        _, param_created = await seed_mfa_default_param(session)

        if apply:
            await session.commit()
        else:
            await session.rollback()

    # 统计口径是"**本次实际新建**几行"，不是清单长度：重复跑时清单还是那么长，
    # 一行都没新建。dry-run 报这个，才能回答"这次到底会写什么"。
    lines = [
        f"部门    {dept_created} 新建 / {len(dept_id)} 可用",
        f"资源    {resource_created} 新建 / {len(resource_id)} 可用",
        f"角色    {role_created} 新建 / {len(role_id)} 可用",
        f"字典    {dict_created} 个（user_status）",
        f"参数    {param_created} 个（mfa.required_default）",
    ]
    if user_created:
        lines.append("管理员  1 个（must_change_password=True，首次登录必须改密）")
    print("\n".join(lines))
    print("dry-run：以上改动已回滚，未落库" if not apply else "已提交")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="全新部署的初始数据")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="跑完全部查询再回滚，只报告将写入什么（默认）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正提交（默认 dry-run，避免误写共享库）",
    )
    parser.add_argument(
        "--with-admin",
        action="store_true",
        help=f"同时创建初始管理员；口令必须来自 {PASSWORD_ENV}",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时出现")

    return await run(with_admin=args.with_admin, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
