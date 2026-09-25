"""种子**写入实现**（`scripts/seed_common.py`）的幂等性测试。

为什么必须测幂等
----------------
`seed_init.py` / `seed_e2e.py` 的卖点就是"可反复执行，不需要 `--reset`"，
而这个卖点里的每一个字都是可以悄悄失效的：

- 部门 / 角色 / 资源 / 字典 / 参数都有业务键，查得到就跳过；
- **授权没有业务键之外的余地** —— `role_permissions` / `role_field_permissions`
  都是 `(role_id, resource_id)` / `(role_id, field_id)` 复合主键，写进去是
  "有就是有"，不存在 upsert。第一版的授权函数只 `add()` 不查，第二次执行
  必然撞 `pk_role_permissions`，而报错出现在"部门角色都写完了"之后，
  看起来像别的地方坏了。

`--dry-run` 测不出这个问题：它每次都在同一个事务里从头跑，从不见到"已提交过
的状态"。所以这里必须**跑两次**。

安全性
------
全部用例都用 `db_session` 夹具，它把每个用例包在一个外层事务里、结束**回滚**，
而种子函数一律只 `flush()` 不 `commit()`，因此这些用例不会往库里留下任何东西，
也不会干扰别的用例自己 INSERT 的角色行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import seed_data as data
from seed_common import (
    grant_role_permissions,
    seed_admin_user,
    seed_departments,
    seed_resources,
    seed_roles,
)
from sqlalchemy import func, select

from app.models.permission import RoleFieldPermission, RolePermission
from app.models.user import AdminUser

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: `seed_admin_user` 用的口令。必须满足 `validate_password_policy`（≥12 字符）。
SEED_TEST_PASSWORD = "Idempotent@Seed2026"


def _expected_role_permission_count() -> int:
    """按清单算出"授权表应当有多少行"，用于精确核对而不是 `>=` 这种松判据。

    PAGE 授权会顺带把同名 MENU 一并授权（菜单随页面可见），菜单在资源清单里
    存在时才写，因此要按资源清单过滤一遍。
    """
    menu_codes = {entry[0] for entry in data.MENUS}
    total = 0
    for _role, pages in data.ROLE_PAGES.items():
        for page_code in pages:
            total += 1
            if page_code.replace(":page", "") in menu_codes:
                total += 1
    total += sum(len(granted) for granted in data.ROLE_BUTTONS.values())
    total += sum(len(granted) for granted in data.ROLE_APIS.values())
    return total


@pytest.mark.integration
async def test_resource_and_grant_seeding_is_idempotent(db_session: AsyncSession) -> None:
    """跑两遍：第一遍全新建，第二遍一行都不新建、也不撞主键。"""
    _dept_id, dept_created = await seed_departments(db_session)
    resource_id, resource_created = await seed_resources(db_session)
    role_id, role_created = await seed_roles(db_session)
    await grant_role_permissions(db_session, role_id=role_id, resource_id=resource_id)
    # ⚠️ 必须显式 flush。夹具是 `autoflush=False`，而"查一遍已有什么"是幂等的
    # 前提 —— 不落库的话第二遍看到的仍是空表，于是又把同一批授权 add 一遍，
    # 最终一个 assert 都不会红（这是本文件第一版写出过的**空过**）。
    await db_session.flush()

    assert dept_created == len(data.DEPARTMENTS)
    assert resource_created == len(data.ALL_RESOURCE_CODES)
    assert role_created == len(data.ROLES)

    # 第二遍：数量归零，且**不许抛异常**。
    # 少了这次断言，就只剩"第一次是不是成功了"这一个信息 ——
    # 而"重复执行"才是种子脚本真正的使用场景。
    _dept_id2, dept_created2 = await seed_departments(db_session)
    _resource_id2, resource_created2 = await seed_resources(db_session)
    _role_id2, role_created2 = await seed_roles(db_session)
    await grant_role_permissions(db_session, role_id=role_id, resource_id=resource_id)
    await db_session.flush()

    assert dept_created2 == 0
    assert resource_created2 == 0
    assert role_created2 == 0


@pytest.mark.integration
async def test_grants_match_the_grant_tables_exactly(db_session: AsyncSession) -> None:
    """授权清单里每一条都要真的落库 —— 漏写比写错更隐蔽（静默少给权限）。

    这里钉的是**精确数量**而不是"不少于某个数"：前者能同时挡住漏写与重复写，
    后者只能挡住漏写。
    """
    await seed_departments(db_session)
    resource_id, _created = await seed_resources(db_session)
    role_id, _created = await seed_roles(db_session)
    await grant_role_permissions(db_session, role_id=role_id, resource_id=resource_id)
    await db_session.flush()  # 同 `test_resource_and_grant_seeding_is_idempotent`

    actual = (
        await db_session.execute(select(func.count()).select_from(RolePermission))
    ).scalar_one()
    assert actual == _expected_role_permission_count(), (
        f"授权表有 {actual} 行，清单算出来应当是 {_expected_role_permission_count()} 行"
    )

    fields = (
        await db_session.execute(select(func.count()).select_from(RoleFieldPermission))
    ).scalar_one()
    assert fields == sum(len(levels) for levels in data.ROLE_FIELDS.values())


@pytest.mark.integration
async def test_admin_user_seeding_is_idempotent(db_session: AsyncSession) -> None:
    """管理员按 username 去重；第二次不重建、也不覆盖已存在的账号。"""
    dept_id, _created = await seed_departments(db_session)
    role_id, _created = await seed_roles(db_session)

    first = await seed_admin_user(
        db_session,
        username="seed_dup_check",
        password=SEED_TEST_PASSWORD,
        display_name="种子幂等检查",
        role_code="SUPER_ADMIN",
        role_id=role_id,
        dept_id=dept_id.get("ROOT"),
    )
    assert first is True

    second = await seed_admin_user(
        db_session,
        username="seed_dup_check",
        password=SEED_TEST_PASSWORD,
        display_name="种子幂等检查（改过名字）",
        role_code="SUPER_ADMIN",
        role_id=role_id,
        dept_id=dept_id.get("ROOT"),
    )
    assert second is False, "重复执行时管理员被重建了（口令被换掉，等于换了个账号）"

    # 领域不变量（RISK-001）：初始账号必须逼本人改密，否则等于留了个不换密的后门。
    # 同时核对第二遍没有把 display_name 改掉 —— "跳过"必须是真的跳过。
    user = (
        await db_session.execute(select(AdminUser).where(AdminUser.username == "seed_dup_check"))
    ).scalar_one()
    assert user.must_change_password is True
    assert user.password_hash != SEED_TEST_PASSWORD
    assert user.display_name == "种子幂等检查", "重复执行覆盖了已存在的管理员"
