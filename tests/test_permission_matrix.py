"""权限矩阵端到端验收（`docs/verification/010-final-acceptance.md` → Permission Matrix）。

裁判书要求至少验证五类主体：

```text
SUPER_ADMIN / Department Admin / Normal User / 多角色用户 / 有继承角色用户
```

为什么必须在 **HTTP 层**跑一遍矩阵
-------------------------------
前面 9 个阶段的验收已经分别验证过：角色 CRUD（`002`）、数据范围（`001`/`002`）、
继承展开（`002`）、多角色求并（DD-19）、API 权限绑定（`008`）。
但那些是**分层验证**：每一层都单独成立，不等于**串起来**还成立。

一次真实请求要穿过四道门：认证 → 路由级 API 权限 → 服务层授权 → 数据范围下推。
其中任何一道装反了（例如路由级放行但服务层用错了 scope），
分层测试都不会红，因为分层测试各自注入了自己那一层的正确输入。
本文件全部走真实登录 + 真实 HTTP，因此四道门的**串联顺序**也在断言范围内。

为什么"有继承角色用户"单独一格
----------------------------
继承展开发生在有效权限引擎（`EffectivePermissionService`）里，
而多角色求并发生在数据范围解析（`DataScopeResolver`）里 ——
两者是**不同的代码路径**。用同一个用例验证两者会掩盖
"其中一条路径没接上"的缺陷（本文件因此把它们分成两个主体）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.actor import SUPER_ADMIN_ROLE_CODE
from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import PermissionResourceType, PermissionStatus
from tests.factories import (
    link_role_inheritance,
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

ADMIN_PREFIX = "/api/v1/admin"

# ---- 组织 ----
DEPT_ROOT = 68101
DEPT_CHILD = 68102
DEPT_OUTSIDE = 68103

# ---- 角色 ----
ROLE_SUPER = 68111
ROLE_DEPT_ADMIN = 68112
ROLE_NORMAL = 68113
ROLE_MULTI_A = 68114  # 只给 USER_MANAGE，范围 SELF
ROLE_MULTI_B = 68115  # 只给 ROLE_MANAGE，范围 DEPARTMENT_CHILDREN
ROLE_PARENT = 68116  # 继承链上的父：持有 USER_MANAGE
ROLE_CHILD = 68117  # 继承链上的子：**自身无任何授权**

# ---- 权限资源 ----
RES_USER_MANAGE = 68121
RES_ROLE_MANAGE = 68122

# ---- 用户 ----
USER_SUPER = 68201
USER_DEPT_ADMIN = 68202
USER_NORMAL = 68203
USER_MULTI = 68204
USER_INHERIT = 68205
USER_TARGET_IN = 68206  # 在 DEPT_CHILD（部门管理员可见）
USER_TARGET_OUT = 68207  # 在 DEPT_OUTSIDE（部门管理员不可见）

PASSWORD = "Matrix-Passw0rd!10"


def _username(user_id: int) -> str:
    return f"mx-{user_id}"


async def _seed(db_session) -> None:
    await make_department(db_session, department_id=DEPT_ROOT, department_code="MX_ROOT")
    await make_department(
        db_session, department_id=DEPT_CHILD, department_code="MX_CHILD", parent_id=DEPT_ROOT
    )
    await make_department(db_session, department_id=DEPT_OUTSIDE, department_code="MX_OUTSIDE")

    await make_role(
        db_session, role_id=ROLE_SUPER, role_code=SUPER_ADMIN_ROLE_CODE, data_scope=DataScope.ALL
    )
    await make_role(
        db_session,
        role_id=ROLE_DEPT_ADMIN,
        role_code="MX_DEPT_ADMIN",
        data_scope=DataScope.DEPARTMENT_CHILDREN,
    )
    await make_role(db_session, role_id=ROLE_NORMAL, role_code="MX_NORMAL")
    await make_role(
        db_session, role_id=ROLE_MULTI_A, role_code="MX_MULTI_A", data_scope=DataScope.SELF
    )
    await make_role(
        db_session,
        role_id=ROLE_MULTI_B,
        role_code="MX_MULTI_B",
        data_scope=DataScope.DEPARTMENT_CHILDREN,
    )
    await make_role(db_session, role_id=ROLE_PARENT, role_code="MX_PARENT")
    await make_role(db_session, role_id=ROLE_CHILD, role_code="MX_CHILD_ROLE")

    for resource_id, code in (
        (RES_USER_MANAGE, "USER_MANAGE"),
        (RES_ROLE_MANAGE, "ROLE_MANAGE"),
    ):
        await make_permission_resource(
            db_session,
            resource_id=resource_id,
            resource_type=PermissionResourceType.API,
            resource_code=code,
            api_method="GET",
            api_path="/api/v1/admin",
            status=PermissionStatus.ACTIVE,
        )

    await link_role_permission(db_session, role_id=ROLE_DEPT_ADMIN, resource_id=RES_USER_MANAGE)
    await link_role_permission(db_session, role_id=ROLE_MULTI_A, resource_id=RES_USER_MANAGE)
    await link_role_permission(db_session, role_id=ROLE_MULTI_B, resource_id=RES_ROLE_MANAGE)
    # 父角色持有授权；子角色**自身**没有任何授权（靠继承获得）
    await link_role_permission(db_session, role_id=ROLE_PARENT, resource_id=RES_USER_MANAGE)
    await link_role_inheritance(db_session, parent_role_id=ROLE_PARENT, child_role_id=ROLE_CHILD)

    for user_id, dept_id in (
        (USER_SUPER, DEPT_ROOT),
        (USER_DEPT_ADMIN, DEPT_ROOT),
        (USER_NORMAL, DEPT_CHILD),
        (USER_MULTI, DEPT_ROOT),
        (USER_INHERIT, DEPT_ROOT),
        (USER_TARGET_IN, DEPT_CHILD),
        (USER_TARGET_OUT, DEPT_OUTSIDE),
    ):
        await make_user(
            db_session,
            user_id=user_id,
            username=_username(user_id),
            password=PASSWORD,
            password_changed_at=utc_now(),
            department_id=dept_id,
        )

    for user_id, role_id in (
        (USER_SUPER, ROLE_SUPER),
        (USER_DEPT_ADMIN, ROLE_DEPT_ADMIN),
        (USER_NORMAL, ROLE_NORMAL),
        (USER_INHERIT, ROLE_CHILD),
        (USER_TARGET_IN, ROLE_NORMAL),
        (USER_TARGET_OUT, ROLE_NORMAL),
    ):
        await link_user_role(db_session, user_id=user_id, role_id=role_id)
    # 多角色用户：两个角色各持一部分权限
    await link_user_role(db_session, user_id=USER_MULTI, role_id=ROLE_MULTI_A)
    await link_user_role(db_session, user_id=USER_MULTI, role_id=ROLE_MULTI_B)


@pytest_asyncio.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[object]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _login(api: AsyncClient, user_id: int) -> dict[str, str]:
    response = await api.post(
        "/api/v1/auth/login",
        json={"username": _username(user_id), "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _data(response) -> dict:
    return response.json()["data"]


# ===========================================================================
# 1. SUPER_ADMIN
# ===========================================================================
class TestSuperAdmin:
    async def test_sees_every_department(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, USER_SUPER)
        body = _data(await api.get(f"{ADMIN_PREFIX}/users", headers=headers))
        ids = {int(item["id"]) for item in body["list"]}
        assert {USER_TARGET_IN, USER_TARGET_OUT} <= ids

    async def test_reaches_every_managed_endpoint(self, api: AsyncClient, db_session) -> None:
        """超管不需要任何 `*_MANAGE` 权限位也能访问（集中式 bypass，Spec `10 §3`）。

        注意 bypass 只作用于**授权**，不作用于数据范围：
        本用例同时断言"范围外用户也可见"，即 SUPER_ADMIN 的范围是全局。
        """
        await _seed(db_session)
        headers = await _login(api, USER_SUPER)
        assert (await api.get(f"{ADMIN_PREFIX}/users", headers=headers)).status_code == 200
        assert (await api.get(f"{ADMIN_PREFIX}/roles", headers=headers)).status_code == 200
        assert (
            await api.get(f"{ADMIN_PREFIX}/departments/tree", headers=headers)
        ).status_code == 200

    async def test_cannot_be_disabled_by_another_admin(self, api: AsyncClient, db_session) -> None:
        """`00 §1#7`：其他管理员不能操作 SUPER_ADMIN（RISK-002 裁定）。"""
        await _seed(db_session)
        # 让部门管理员也持有禁用所需权限，排除"只是缺权限位"的假阳性
        await link_role_permission(db_session, role_id=ROLE_DEPT_ADMIN, resource_id=RES_ROLE_MANAGE)
        headers = await _login(api, USER_DEPT_ADMIN)
        response = await api.post(f"{ADMIN_PREFIX}/users/{USER_SUPER}/disable", headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == 403001


# ===========================================================================
# 2. Department Admin
# ===========================================================================
class TestDepartmentAdmin:
    async def test_scope_is_department_plus_children(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, USER_DEPT_ADMIN)
        body = _data(await api.get(f"{ADMIN_PREFIX}/users", headers=headers))
        ids = {int(item["id"]) for item in body["list"]}
        assert USER_TARGET_IN in ids, "本部门的下级部门用户必须可见"
        assert USER_TARGET_OUT not in ids, "范围外用户必须**看不到**，而不是看到了再拒绝"

    async def test_cannot_read_target_outside_scope(self, api: AsyncClient, db_session) -> None:
        """范围外的单个目标被**拒绝**（403，且留 FAILURE 审计）。

        为什么不是 404：列表接口把范围下推到 SQL（看不见），
        单读接口抛 `PermissionDeniedError`（看得见但拒绝）。
        后者换来的正是"谁试图访问谁"这条取证记录 ——
        改成 404 会让这类探测在审计里彻底消失。
        """
        await _seed(db_session)
        headers = await _login(api, USER_DEPT_ADMIN)
        response = await api.get(f"{ADMIN_PREFIX}/users/{USER_TARGET_OUT}", headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == 403001


# ===========================================================================
# 3. Normal User
# ===========================================================================
class TestNormalUser:
    async def test_no_manage_permission_is_403(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, USER_NORMAL)
        for path in (f"{ADMIN_PREFIX}/users", f"{ADMIN_PREFIX}/roles"):
            response = await api.get(path, headers=headers)
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

    async def test_can_still_read_own_permission_contract(
        self, api: AsyncClient, db_session
    ) -> None:
        """`/auth/permissions` 对**任何已认证**主体开放（`09 §2`：契约的消费者就是自己）。

        但内容是空的 —— 空不等于 403：前端需要能区分
        "没有权限"与"无权查询权限"。
        """
        await _seed(db_session)
        headers = await _login(api, USER_NORMAL)
        response = await api.get("/api/v1/auth/permissions", headers=headers)
        assert response.status_code == 200
        body = _data(response)
        assert body["pages"] == []
        assert body["apis"] == []


# ===========================================================================
# 4. 多角色用户（取并集）
# ===========================================================================
class TestMultiRoleUser:
    async def test_permissions_are_the_union(self, api: AsyncClient, db_session) -> None:
        """两个角色各持一半权限 ⇒ 用户同时拥有两者（`00 §1#2` 取并集）。

        为什么这条断言能抓到真实缺陷：若实现取的是**交集**或**第一个角色**，
        本用例会红，而"单角色用户"的用例不会 —— 那正是并集语义唯一能被
        观察到的地方。
        """
        await _seed(db_session)
        headers = await _login(api, USER_MULTI)
        assert (await api.get(f"{ADMIN_PREFIX}/users", headers=headers)).status_code == 200, (
            "来自 ROLE_MULTI_A 的 USER_MANAGE"
        )
        assert (await api.get(f"{ADMIN_PREFIX}/roles", headers=headers)).status_code == 200, (
            "来自 ROLE_MULTI_B 的 ROLE_MANAGE"
        )

    async def test_data_scopes_are_also_unioned(self, api: AsyncClient, db_session) -> None:
        """数据范围同样取并（DD-19）：`SELF ∪ DEPARTMENT_CHILDREN` 必须覆盖下级部门。

        若实现取的是**最窄**（SELF），本用例会红 ——
        而"只给一个角色"的用例不会。
        """
        await _seed(db_session)
        headers = await _login(api, USER_MULTI)
        body = _data(await api.get(f"{ADMIN_PREFIX}/users", headers=headers))
        ids = {int(item["id"]) for item in body["list"]}
        assert USER_TARGET_IN in ids
        assert USER_TARGET_OUT not in ids


# ===========================================================================
# 5. 有继承角色用户
# ===========================================================================
class TestInheritedRoleUser:
    async def test_child_role_inherits_parent_permission(
        self, api: AsyncClient, db_session
    ) -> None:
        """子角色自身**没有任何授权**，权限全部来自父角色（`03 §4` V1 支持继承）。"""
        await _seed(db_session)
        headers = await _login(api, USER_INHERIT)
        response = await api.get(f"{ADMIN_PREFIX}/users", headers=headers)
        assert response.status_code == 200, "继承来的 USER_MANAGE 必须生效"

    async def test_contract_reports_inherited_role_ids(self, api: AsyncClient, db_session) -> None:
        """契约里 `inherited_role_ids` 必须与直接角色分开表达（`09 §2`）。

        分两个字段不是装饰：前端需要能回答"这个权限是我自己的还是继承来的"
        —— 否则用户无法理解为什么改不掉某个权限。
        """
        await _seed(db_session)
        headers = await _login(api, USER_INHERIT)
        body = _data(await api.get("/api/v1/auth/permissions", headers=headers))
        assert str(ROLE_CHILD) in body["direct_role_ids"] or ROLE_CHILD in [
            int(value) for value in body["direct_role_ids"]
        ]
        inherited = {int(value) for value in body["inherited_role_ids"]}
        assert ROLE_PARENT in inherited
        assert ROLE_CHILD not in inherited, "继承来的集合里不能出现自己的直接角色"
