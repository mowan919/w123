"""种子数据的**写入实现**，被 `seed_e2e.py` 与 `seed_init.py` 共用。

为什么抽出来
------------
两份种子的**写入过程**几乎相同（建部门 → 建资源 → 建角色 → 授权 → 建用户），
只有"建哪些数据"不同。如果各写一份，改一列字段要改两处 —— 而且这两处必然
漂移，漂移又是静默的。

幂等约定
--------
每个函数都按**业务键**先查后写，已存在就跳过。因此整个流程可以反复执行，
也不需要 `--reset`（`--reset` 是清空全表，属于危险操作，见 `seed_e2e.py` 的说明）。

事务约定
--------
函数内部只 `flush()` 不 `commit()`。调用方决定是否提交：

    async with factory() as session:
        await seed_everything(session)
        if apply:
            await session.commit()
        else:
            await session.rollback()   # --dry-run：同样跑完全部查询，只是不留痕

`--dry-run` 走**完全相同**的代码路径、只是最后回滚，好处是"预演成功"意味着
"真跑也一定成功"，不会出现 dry-run 与实跑两套行为。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seed_data import (
    APIS,
    BUTTONS,
    DEPARTMENTS,
    FIELDS,
    MENU_PAGES,
    MENUS,
    PAGES,
    ROLE_APIS,
    ROLE_BUTTONS,
    ROLE_FIELDS,
    ROLE_PAGES,
    ROLES,
)
from sqlalchemy import select

from app.core.security.password import get_password_hasher, validate_password_policy
from app.db.base import utc_now
from app.models.department import Department
from app.models.dict import SysDictItem, SysDictType
from app.models.enums import (
    DepartmentStatus,
    DictStatus,
    PermissionResourceType,
    PermissionStatus,
    RoleStatus,
    UserStatus,
)
from app.models.param import SysParam
from app.models.permission import (
    MenuPage,
    PermissionResource,
    RoleFieldPermission,
    RolePermission,
)
from app.models.role import Role, UserRole
from app.models.user import AdminUser
from app.services.system_param import MFA_REQUIRED_DEFAULT_KEY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------- 部门


async def seed_departments(session: AsyncSession) -> tuple[dict[str, int], int]:
    """建部门，返回 `{code: id}`。

    幂等键是 `department_code`。返回值是 `{code: id}` 与**本次新建行数** ——
    只报"清单里有多少个"会骗人：重复执行时清单长度不变，一行都没建。
    """
    dept_id: dict[str, int] = {}
    rows = (
        await session.execute(
            select(Department.id, Department.department_code).where(
                Department.department_code.in_([entry[0] for entry in DEPARTMENTS])
            )
        )
    ).all()
    pre_existing = {code for _id, code in rows}
    for row_id, code in rows:
        dept_id[code] = row_id

    for code, name, parent_code in DEPARTMENTS:
        if code in dept_id:
            continue
        dept_row = Department(
            department_code=code,
            department_name=name,
            parent_id=dept_id.get(parent_code) if parent_code else None,
            status=DepartmentStatus.ACTIVE,
        )
        session.add(dept_row)
        await session.flush()
        dept_id[code] = dept_row.id
    return dept_id, len(dept_id) - len(pre_existing & dept_id.keys())


# ---------------------------------------------------------------- 权限资源


async def seed_resources(session: AsyncSession) -> tuple[dict[tuple[str, str], int], int]:
    """建权限资源，返回 `{(resource_type, code): id}`。

    幂等键是 `(resource_type, resource_code)` —— **注意是复合键**：
    `user:create`（BUTTON）与它所属 PAGE 的编码前缀相同，只按 `resource_code`
    去重会让后建的那个覆盖 / 跳过先建的那个。
    """
    resource_id: dict[tuple[str, str], int] = {}
    resource_created = 0
    wanted: set[tuple[str, str]] = set()
    for code, *_ in PAGES:
        wanted.add((PermissionResourceType.PAGE.value, code))
    for code, *_ in BUTTONS:
        wanted.add((PermissionResourceType.BUTTON.value, code))
    for code, *_ in APIS:
        wanted.add((PermissionResourceType.API.value, code))
    for code, *_ in FIELDS:
        wanted.add((PermissionResourceType.FIELD.value, f"field:{code}"))
    for code, *_ in MENUS:
        wanted.add((PermissionResourceType.MENU.value, code))

    rows = (
        await session.execute(
            select(
                PermissionResource.id,
                PermissionResource.resource_code,
                PermissionResource.resource_type,
            )
        )
    ).all()
    for row_id, code, kind in rows:
        key = (kind, code)
        if key in wanted:
            resource_id[key] = row_id

    # 类型专属列的默认值：类型不符的列一律留空，
    # 由 `ck_permission_resources_resource_type_fields` 在库层兜底拒绝形状错误的数据。
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
        key = (PermissionResourceType.PAGE.value, code)
        if key in resource_id:
            continue
        resource_created += 1
        resource_row = add_resource(
            resource_type=PermissionResourceType.PAGE,
            resource_code=code,
            resource_name=name,
            route_path=route_path,
            component_path=component_path,
            sort_order=order,
        )
        await session.flush()
        resource_id[key] = resource_row.id

    for code, name, page_code in BUTTONS:
        key = (PermissionResourceType.BUTTON.value, code)
        if key in resource_id:
            continue
        resource_created += 1
        resource_row = add_resource(
            resource_type=PermissionResourceType.BUTTON,
            resource_code=code,
            resource_name=name,
            parent_id=resource_id[(PermissionResourceType.PAGE.value, page_code)],
            sort_order=10,
        )
        await session.flush()
        resource_id[key] = resource_row.id

    for code, name, method, path, page_code in APIS:
        key = (PermissionResourceType.API.value, code)
        if key in resource_id:
            continue
        resource_created += 1
        resource_row = add_resource(
            resource_type=PermissionResourceType.API,
            resource_code=code,
            resource_name=name,
            api_method=method,
            api_path=path,
            parent_id=resource_id[(PermissionResourceType.PAGE.value, page_code)],
            sort_order=10,
        )
        await session.flush()
        resource_id[key] = resource_row.id

    for field_key, page_code in FIELDS:
        key = (PermissionResourceType.FIELD.value, f"field:{field_key}")
        if key in resource_id:
            continue
        resource_created += 1
        resource_row = add_resource(
            resource_type=PermissionResourceType.FIELD,
            resource_code=f"field:{field_key}",
            resource_name=field_key,
            field_key=field_key,
            owner_resource_id=resource_id[(PermissionResourceType.PAGE.value, page_code)],
            sort_order=10,
        )
        await session.flush()
        resource_id[key] = resource_row.id

    # 菜单：parent_id 指向 MENU 类型的资源。
    for code, name, parent_code, icon, order in MENUS:
        key = (PermissionResourceType.MENU.value, code)
        if key in resource_id:
            continue
        resource_created += 1
        resource_row = add_resource(
            resource_type=PermissionResourceType.MENU,
            resource_code=code,
            resource_name=name,
            icon=icon,
            parent_id=resource_id[(PermissionResourceType.MENU.value, parent_code)]
            if parent_code
            else None,
            sort_order=order,
        )
        await session.flush()
        resource_id[key] = resource_row.id

    # MENU ↔ PAGE 关联（一个菜单可关联多个页面）。
    # 关联表没有业务键之外的唯一性可依，直接按 (menu_id, page_id) 去重写入；
    # 重复写同一组合由主键冲突表达，这里先查一遍已有关联。
    # `.all()` 返回的是 `Row` 序列而不是元组序列，直接喂给 `set()` 会存下 Row；
    # 随后用 `(menu_id, page_id)` 去 `in` 一个装了 Row 的 set，恒为 False ——
    # 于是同一条关联每次跑都重复写。这里显式解包成元组。
    existing_links = {
        (row.menu_id, row.page_id)
        for row in (await session.execute(select(MenuPage.menu_id, MenuPage.page_id))).all()
    }
    for menu_code, page_code in MENU_PAGES:
        menu_key = (PermissionResourceType.MENU.value, menu_code)
        page_key = (PermissionResourceType.PAGE.value, page_code)
        if menu_key not in resource_id or page_key not in resource_id:
            continue
        menu_id = resource_id[menu_key]
        page_id = resource_id[page_key]
        if (menu_id, page_id) in existing_links:
            continue
        session.add(MenuPage(menu_id=menu_id, page_id=page_id))
        existing_links.add((menu_id, page_id))

    return resource_id, resource_created


# ---------------------------------------------------------------- 角色与授权


async def seed_roles(session: AsyncSession) -> tuple[dict[str, int], int]:
    """建角色，返回 `{role_code: id}` 与本次新建行数。幂等键是 `role_code`。"""
    role_id: dict[str, int] = {}
    rows = (
        await session.execute(
            select(Role.id, Role.role_code).where(Role.role_code.in_([entry[0] for entry in ROLES]))
        )
    ).all()
    role_codes_before = {code for _id, code in rows}
    for row_id, code in rows:
        role_id[code] = row_id

    for code, name, scope, description in ROLES:
        if code in role_id:
            continue
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
    return role_id, len(role_id) - len(role_codes_before)


async def grant_role_permissions(
    session: AsyncSession,
    *,
    role_id: dict[str, int],
    resource_id: dict[tuple[str, str], int],
) -> None:
    """按 `seed_data` 的映射表把资源授权给角色。

    授权的**清单**来源是 `seed_data`，这里只管怎么落库，因此两个调用方拿到
    的授权范围必然一致。

    ⚠️ `resource_id` 的键是**二元组** `(type, code)`。曾经用裸字符串去查这个
    dict，结果恒为 False —— 那次授权**一次都没写进去**，页面都给全了却一个
    菜单都没有。mypy 的 `comparison-overlap` 就是冲着这里来的，别改回裸字符串。

    ⚠️ 两张授权表都是 `(role_id, resource_id)` / `(role_id, field_id)` **复合主键**，
    写进去是"有就是有"，没有 upsert 余地。第一版只 `add()` 不查，第二次执行
    必然撞 `pk_role_permissions` / `pk_role_field_permissions` —— 而"能反复执行"
    正是这两个脚本的卖点。已存在一律跳过（不覆写），同一轮内的重复也一并折叠。

    为什么是"跳过"而不是"更新等级"：字段授权等级一旦被管理员改动，
    种子脚本再跑一遍不该把它改回清单里的值。要改范围请直接改 `seed_data` 并
    在管理界面同步，或者用 `seed_e2e.py --reset`（清空后重建）。
    """
    # 一次性把已有的授权全取出来，后续纯内存判断。
    # `.all()` 返回 `Row` 序列而不是元组序列，必须显式解包（同 `seed_resources`）。
    # 注意别把这对外层的 set 叫 `granted`：下面每个循环也把 `granted` 用作
    # "本轮要授权的清单"，同名会被循环变量整个覆盖掉（Python 没有块作用域）。
    existing_grants: set[tuple[int, int]] = {
        (row.role_id, row.resource_id)
        for row in (
            await session.execute(select(RolePermission.role_id, RolePermission.resource_id))
        ).all()
    }
    existing_field_grants: set[tuple[int, int]] = {
        (row.role_id, row.field_id)
        for row in (
            await session.execute(select(RoleFieldPermission.role_id, RoleFieldPermission.field_id))
        ).all()
    }

    page_type = PermissionResourceType.PAGE.value
    menu_type = PermissionResourceType.MENU.value
    button_type = PermissionResourceType.BUTTON.value
    api_type = PermissionResourceType.API.value
    field_type = PermissionResourceType.FIELD.value

    for role_code, granted in ROLE_PAGES.items():
        if role_code not in role_id:
            continue
        for page_code in granted:
            role_pk = role_id[role_code]
            pair = (role_pk, resource_id[(page_type, page_code)])
            if pair not in existing_grants:
                existing_grants.add(pair)
                session.add(RolePermission(role_id=role_pk, resource_id=pair[1]))
            # 菜单随页面一起可见（否则菜单点进去会被守卫拦到 403）。
            menu_for_page = page_code.replace(":page", "")
            if (menu_type, menu_for_page) in resource_id:
                menu_pair = (role_pk, resource_id[(menu_type, menu_for_page)])
                if menu_pair not in existing_grants:
                    existing_grants.add(menu_pair)
                    session.add(RolePermission(role_id=role_pk, resource_id=menu_pair[1]))

    for role_code, granted in ROLE_BUTTONS.items():
        if role_code not in role_id:
            continue
        for button_code in granted:
            pair = (role_id[role_code], resource_id[(button_type, button_code)])
            if pair in existing_grants:
                continue
            existing_grants.add(pair)
            session.add(RolePermission(role_id=pair[0], resource_id=pair[1]))

    for role_code, granted in ROLE_APIS.items():
        if role_code not in role_id:
            continue
        for api_code in granted:
            pair = (role_id[role_code], resource_id[(api_type, api_code)])
            if pair in existing_grants:
                continue
            existing_grants.add(pair)
            session.add(RolePermission(role_id=pair[0], resource_id=pair[1]))

    for role_code, levels in ROLE_FIELDS.items():
        if role_code not in role_id:
            continue
        for field_key, level in levels.items():
            # ⚠️ 键里带 `field:` 前缀。`seed_resources` 里 FIELD 的键是
            # `("FIELD", "field:phone")`，而 `ROLE_FIELDS` 写的是裸 `phone`。
            # 这里若图省事写成 `(field_type, field_key)`，就会 KeyError ——
            # 而且是在**授权这一段的后半程**才炸，部门/角色/菜单都写进去了。
            pair = (role_id[role_code], resource_id[(field_type, f"field:{field_key}")])
            if pair in existing_field_grants:
                continue
            existing_field_grants.add(pair)
            session.add(RoleFieldPermission(role_id=pair[0], field_id=pair[1], access_level=level))


# ---------------------------------------------------------------- 用户


async def seed_admin_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str,
    role_code: str,
    role_id: dict[str, int],
    dept_id: int | None,
) -> bool:
    """建初始管理员，返回**是否真的创建了**（新建时也只有 yes/no 两种结果）。

    口令**必须**由调用方从环境 / 密钥管理注入，本函数不接受缺省口令 ——
    一个"生成的初始账号"如果带的是众所周知的内置口令，等于给系统留了后门。
    """
    existing = (
        await session.execute(select(AdminUser.id).where(AdminUser.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        return False

    violations = validate_password_policy(password)
    if violations:
        msg = f"{username} 的口令不满足策略：{[v.message for v in violations]}"
        raise SystemExit(msg)

    if role_code not in role_id:
        msg = f"角色 {role_code} 不存在，无法为管理员授权"
        raise SystemExit(msg)

    hasher = get_password_hasher()
    user_row = AdminUser(
        username=username,
        password_hash=hasher.hash(password),
        display_name=display_name,
        department_id=dept_id,
        status=UserStatus.ACTIVE,
        # RISK-001 的既定行为：新建 / 重置出来的账号必须本人改一次密。
        must_change_password=True,
        failed_login_count=0,
        locked_until=None,
        password_changed_at=utc_now(),
    )
    session.add(user_row)
    await session.flush()
    session.add(UserRole(user_id=user_row.id, role_id=role_id[role_code]))
    return True


# ---------------------------------------------------------------- 字典


async def seed_user_status_dict(session: AsyncSession) -> tuple[None, int]:
    """建 `user_status` 字典类型及其三个取值。

    这是**唯一**被前端 `labelOf()` 消费的字典码（其余字典由字典管理页录入），
    没有它时状态列会直接显示 `ACTIVE` 这类原始枚举值。

    幂等键：`dict_type.dict_code` 与 `(dict_type_id, item_value)`。
    """
    # 变量名刻意不叫 `dict_row`：一个变量先装 `int | None`、再被赋成 ORM 对象，
    # 类型检查器会直接报错（也会把后面 `dict_type_id=` 的用法绕晕）。
    dict_type_id: int | None = (
        await session.execute(select(SysDictType.id).where(SysDictType.dict_code == "user_status"))
    ).scalar_one_or_none()
    if dict_type_id is None:
        new_dict = SysDictType(
            dict_code="user_status",
            dict_name="用户状态",
            description="后台用户的账号状态；DROP 后会退回显示原始枚举值",
            status=DictStatus.ACTIVE,
        )
        session.add(new_dict)
        await session.flush()
        dict_type_id = new_dict.id
    assert dict_type_id is not None

    items: list[tuple[str, str, str, int, bool]] = [
        ("正常", "ACTIVE", "user_status_active", 10, True),
        ("停用", "DISABLED", "user_status_disabled", 20, False),
        ("已锁定", "LOCKED", "user_status_locked", 30, False),
    ]
    existing_values = set(
        (
            await session.execute(
                select(SysDictItem.item_value).where(SysDictItem.dict_type_id == dict_type_id)
            )
        ).scalars()
    )
    dict_created = 0
    for label, value, code, order, is_default in items:
        if value in existing_values:
            continue
        session.add(
            SysDictItem(
                dict_type_id=dict_type_id,
                item_label=label,
                item_value=value,
                item_code=code,
                sort_order=order,
                status=DictStatus.ACTIVE,
                is_default=is_default,
                description=None,
            )
        )
        dict_created += 1
    return None, dict_created


# ---------------------------------------------------------------- 参数


async def seed_mfa_default_param(session: AsyncSession) -> tuple[bool, int]:
    """确保 `mfa.required_default` 参数行存在，返回是否新建。

    这一行**同时**由迁移 `phase7_dict` 以固定 ID 写入（见其模块文档）。
    因此这里只做"缺失则补"：若已存在就跳过 —— 若反过来无条件新建，
    会撞 `uq_sys_params_param_key_active` 唯一约束。
    """
    existing = (
        await session.execute(
            select(SysParam.id).where(SysParam.param_key == MFA_REQUIRED_DEFAULT_KEY)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False, 0
    session.add(
        SysParam(
            param_key=MFA_REQUIRED_DEFAULT_KEY,
            param_name="MFA 系统级默认策略",
            param_type="BOOL",
            param_value=None,
            default_value="false",
            status="ACTIVE",
            description=("策略链 user > role > system 的 system 级默认值（Spec 04 §7）"),
        )
    )
    return True, 1
