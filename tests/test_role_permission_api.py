"""角色授权与数据范围端点测试（Phase 8 / Spec `08 §7`）。

对应 Verification `008-dynamic-permission.md` 的：

- **权限变更立即生效**（`00 §1#5` / `09 §7`）—— 用**同一个令牌**在授权变更前后
  各读一次 `/auth/permissions`，验证结果立即变化、无需重新登录；
- **后端可返回 data scope**（`03 §10`）—— 范围变更同样必须即时反映到契约。

另外钉住三条容易写错的语义：

1. **按类别替换不得波及别的类别**（一次改页面授权静默清掉 API 授权，
   是本项目明确标记为"最易写错处"的路径）；
2. **资源类型必须匹配**：把 PAGE 的 ID 传给 `.../permissions/apis`
   会造成"配了却没生效"的配置失效，必须 400；
3. **非 CUSTOM 不得携带部门集合**：静默丢弃会制造"以为已限定、实际未限定"。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import PermissionResourceType, PermissionStatus
from tests.factories import (
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

ADMIN_PREFIX = "/api/v1/admin"
AUTH_PREFIX = "/api/v1/auth"

DEPT_ID = 62001
CHILD_DEPT_ID = 62002

ROLE_ADMIN = 62011
ROLE_TARGET = 62012
ROLE_NO_PERM = 62013
ROLE_MANAGE_ONLY = 62014
RES_API_ROLE_MANAGE = 62021
RES_API_RESOURCE_MANAGE = 62022

USER_ID = 62101
NO_PERM_USER_ID = 62102
HOLDER_USER_ID = 62103
MANAGE_ONLY_USER_ID = 62104
USERNAME = "p8-role-admin"
NO_PERM_USERNAME = "p8-role-noperm"
HOLDER_USERNAME = "p8-role-holder"
MANAGE_ONLY_USERNAME = "p8-role-manage-only"
PASSWORD = "Role-Perm-Passw0rd!08"

PAGE_A = 62201
PAGE_B = 62202
MENU_ID = 62203
BUTTON_ID = 62204
API_ID = 62205
FIELD_PHONE = 62206

#: `08 §7` 中与权限相关的端点（角色实体 CRUD 不属本 Phase，见 FINDING-8-01）。
FROZEN_ROLE_PATHS = {
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/pages",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/menus",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/buttons",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/apis",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/fields",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/data-scope",
}

#: 全部 8 条端点（含 GET 与 PUT 共用的三条路径）。
_ACCESS_CALLS: tuple[tuple[str, str, str, dict[str, Any] | None], ...] = (
    ("get", f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions", "perms-read", None),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
        "perms-pages",
        {"resourceIds": []},
    ),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/menus",
        "perms-menus",
        {"resourceIds": []},
    ),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/buttons",
        "perms-buttons",
        {"resourceIds": []},
    ),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/apis",
        "perms-apis",
        {"resourceIds": []},
    ),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/fields",
        "perms-fields",
        {"fields": []},
    ),
    ("get", f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope", "scope-read", None),
    (
        "put",
        f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope",
        "scope-write",
        {"data_scope": "SELF", "department_ids": []},
    ),
)


@pytest.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """把 `get_db` 指向用例事务的 HTTP 客户端。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(response: Response) -> Any:
    return response.json()["data"]


async def _seed(session) -> None:
    """一个角色管理员 + 一个无权限用户 + 一个"被配置角色"的持有者。"""
    await make_department(session, department_id=DEPT_ID, department_code="P8-ROLE-DEPT")
    await make_department(
        session, department_id=CHILD_DEPT_ID, department_code="P8-ROLE-CHILD", parent_id=DEPT_ID
    )

    await make_role(session, role_id=ROLE_ADMIN, role_code="P8_ROLE_ADMIN")
    await make_role(session, role_id=ROLE_NO_PERM, role_code="P8_ROLE_NONE")
    await make_role(session, role_id=ROLE_MANAGE_ONLY, role_code="P8_ROLE_MANAGE_ONLY")
    await make_role(
        session,
        role_id=ROLE_TARGET,
        role_code="P8_ROLE_TARGET",
        data_scope=DataScope.DEPARTMENT_CHILDREN,
    )

    await make_permission_resource(
        session,
        resource_id=RES_API_ROLE_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="ROLE_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/roles",
        status=PermissionStatus.ACTIVE,
    )
    await make_permission_resource(
        session,
        resource_id=RES_API_RESOURCE_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="PERMISSION_RESOURCE_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/permission-resources",
        status=PermissionStatus.ACTIVE,
    )
    # 平台管理员同时持有两把"钥匙"；`ROLE_MANAGE_ONLY` 刻意只给第一把，
    # 用于验证两个权限位**互不隐含**（见 TestAccessControl 的对应用例）。
    await link_role_permission(session, role_id=ROLE_ADMIN, resource_id=RES_API_ROLE_MANAGE)
    await link_role_permission(session, role_id=ROLE_ADMIN, resource_id=RES_API_RESOURCE_MANAGE)
    await link_role_permission(session, role_id=ROLE_MANAGE_ONLY, resource_id=RES_API_ROLE_MANAGE)

    await make_permission_resource(
        session,
        resource_id=PAGE_A,
        resource_type=PermissionResourceType.PAGE,
        resource_code="report:view",
        route_path="/reports",
        component_path="views/report/index.vue",
    )
    await make_permission_resource(
        session,
        resource_id=PAGE_B,
        resource_type=PermissionResourceType.PAGE,
        resource_code="report:export",
        route_path="/reports/export",
        component_path="views/report/export.vue",
    )
    await make_permission_resource(
        session,
        resource_id=MENU_ID,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:report",
        icon="chart",
    )
    await make_permission_resource(
        session,
        resource_id=BUTTON_ID,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="report:export:btn",
        parent_id=PAGE_A,
    )
    await make_permission_resource(
        session,
        resource_id=API_ID,
        resource_type=PermissionResourceType.API,
        resource_code="REPORT_EXPORT",
        api_method="POST",
        api_path="/api/v1/admin/reports/export",
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_PHONE,
        resource_type=PermissionResourceType.FIELD,
        resource_code="report:phone",
        field_key="phone",
        owner_resource_id=PAGE_A,
    )

    for user_id, username, role_id in (
        (USER_ID, USERNAME, ROLE_ADMIN),
        (NO_PERM_USER_ID, NO_PERM_USERNAME, ROLE_NO_PERM),
        (HOLDER_USER_ID, HOLDER_USERNAME, ROLE_TARGET),
        (MANAGE_ONLY_USER_ID, MANAGE_ONLY_USERNAME, ROLE_MANAGE_ONLY),
    ):
        await make_user(
            session,
            user_id=user_id,
            username=username,
            department_id=DEPT_ID,
            password=PASSWORD,
            password_changed_at=utc_now(),
        )
        await link_user_role(session, user_id=user_id, role_id=role_id)


async def _login(api: AsyncClient, *, username: str = USERNAME) -> str:
    response = await api.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return _data(response)["access_token"]


async def _contract(api: AsyncClient, token: str) -> dict[str, Any]:
    response = await api.get(f"{AUTH_PREFIX}/permissions", headers=_auth(token))
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------------------------
# 路由面与访问控制
# ---------------------------------------------------------------------------
class TestRouteSurface:
    def test_role_permission_paths_match_spec(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        assert paths >= FROZEN_ROLE_PATHS, f"缺少端点：{FROZEN_ROLE_PATHS - paths}"
        actual = {path for path in paths if "/roles/" in path}
        assert actual == FROZEN_ROLE_PATHS, f"路由面与 `08 §7` 不符：{actual}"


class TestAccessControl:
    async def test_anonymous_is_rejected_with_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        for method, path, label, body in _ACCESS_CALLS:
            response = await getattr(api, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 401, label
            assert response.json()["code"] == 401001, label

    async def test_without_role_manage_is_rejected_with_403(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)
        for method, path, label, body in _ACCESS_CALLS:
            response = await getattr(api, method)(
                path, headers=_auth(token), **({"json": body} if body else {})
            )
            assert response.status_code == 403, label
            assert response.json()["code"] == 403001, label

    async def test_role_manage_does_not_imply_resource_manage(
        self, api: AsyncClient, db_session
    ) -> None:
        """`ROLE_MANAGE` 与 `PERMISSION_RESOURCE_MANAGE` 是**两把独立的钥匙**。

        持有"管理角色授权"的人可以决定"谁拥有哪些权限"，
        但**不**因此获得"修改权限资源定义"的能力（改页面路由、停用接口……）。
        若两者隐含，一个只能配授权的管理员就能改掉整个权限模型的结构 ——
        那不是同一件事的两种说法，而是两个不同的风险面。

        本用例把这条边界变成可执行断言，避免将来有人"顺手"用
        `assert_can_manage_roles` 去守资源端点。
        """
        await _seed(db_session)
        token = await _login(api, username=MANAGE_ONLY_USERNAME)

        # 角色授权端点是允许的
        allowed = await api.get(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions", headers=_auth(token)
        )
        assert allowed.status_code == 200

        # 资源定义端点必须被拒
        denied = await api.get(f"{ADMIN_PREFIX}/permission-resources", headers=_auth(token))
        assert denied.status_code == 403
        assert denied.json()["code"] == 403001


# ---------------------------------------------------------------------------
# 授权读写
# ---------------------------------------------------------------------------
class TestRolePermissionHttp:
    async def test_grant_round_trip_returns_sorted_id_sets(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)

        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": [PAGE_A, PAGE_B]},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        body = _data(response)
        assert body["role_id"] == str(ROLE_TARGET)
        # 业务 ID 一律序列化为字符串（`00 §6`）
        assert body["page_ids"] == [str(PAGE_A), str(PAGE_B)]
        assert body["menu_ids"] == []
        assert body["api_ids"] == []

        read_back = await api.get(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions", headers=_auth(token)
        )
        assert read_back.status_code == 200
        assert _data(read_back)["page_ids"] == [str(PAGE_A), str(PAGE_B)]

    async def test_replacing_one_kind_does_not_touch_others(
        self, api: AsyncClient, db_session
    ) -> None:
        """按类别替换必须**限定在该类别内**。

        这是本项目在决策台账里明确标记的"最易写错处"：
        一次改页面授权若顺手清掉 API/BUTTON 授权，管理员会看到
        "我只改了一个页面，接口权限全没了"，且不会被任何正向用例发现。
        """
        await _seed(db_session)
        token = await _login(api)

        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/apis",
            json={"resourceIds": [API_ID]},
            headers=_auth(token),
        )
        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/buttons",
            json={"resourceIds": [BUTTON_ID]},
            headers=_auth(token),
        )
        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/menus",
            json={"resourceIds": [MENU_ID]},
            headers=_auth(token),
        )
        # 只替换页面
        final = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": [PAGE_A]},
            headers=_auth(token),
        )
        body = _data(final)
        assert body["page_ids"] == [str(PAGE_A)]
        assert body["api_ids"] == [str(API_ID)]
        assert body["button_ids"] == [str(BUTTON_ID)]
        assert body["menu_ids"] == [str(MENU_ID)]

    async def test_wrong_resource_type_is_rejected(self, api: AsyncClient, db_session) -> None:
        """把 PAGE 的 ID 提交到 `.../permissions/apis` 必须 400。

        若放行，那一行确实会落进 `role_permissions`，但有效权限计算按
        `resource_type` 过滤 → **配了却不生效**。这种"配置静默失效"
        比直接报错难排查得多。
        """
        await _seed(db_session)
        token = await _login(api)
        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/apis",
            json={"resourceIds": [PAGE_A]},
            headers=_auth(token),
        )
        assert response.status_code == 400

    async def test_nonexistent_resource_is_rejected(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": [999999999]},
            headers=_auth(token),
        )
        assert response.status_code == 400

    async def test_field_permissions_carry_access_level(self, api: AsyncClient, db_session) -> None:
        """字段授权必须携带四级取值，且响应键为字符串（JSON 对象键约束）。"""
        await _seed(db_session)
        token = await _login(api)

        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/fields",
            json={"fields": [{"resourceId": FIELD_PHONE, "accessLevel": "READ_ONLY"}]},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        assert _data(response)["field_levels"] == {str(FIELD_PHONE): "READ_ONLY"}

    async def test_unknown_field_level_is_rejected(self, api: AsyncClient, db_session) -> None:
        """非四级取值必须在请求校验层被拒（不允许写进库里当"未知等级"）。"""
        await _seed(db_session)
        token = await _login(api)
        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/fields",
            json={"fields": [{"resourceId": FIELD_PHONE, "accessLevel": "WRITABLE"}]},
            headers=_auth(token),
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 数据范围
# ---------------------------------------------------------------------------
class TestRoleDataScopeHttp:
    async def test_scope_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)

        initial = await api.get(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope", headers=_auth(token)
        )
        assert initial.status_code == 200
        assert _data(initial)["data_scope"] == "DEPARTMENT_CHILDREN"
        # 非 CUSTOM 恒为空数组（不留残留配置，DD-07 不变量）
        assert _data(initial)["department_ids"] == []

        updated = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope",
            json={"data_scope": "CUSTOM", "department_ids": [CHILD_DEPT_ID]},
            headers=_auth(token),
        )
        assert updated.status_code == 200, updated.text
        assert _data(updated)["data_scope"] == "CUSTOM"
        assert _data(updated)["department_ids"] == [str(CHILD_DEPT_ID)]

        # 切回非 CUSTOM：CUSTOM 部门集合必须被清空
        reverted = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope",
            json={"data_scope": "SELF", "department_ids": []},
            headers=_auth(token),
        )
        assert _data(reverted)["data_scope"] == "SELF"
        assert _data(reverted)["department_ids"] == []

    async def test_non_custom_with_departments_is_rejected(
        self, api: AsyncClient, db_session
    ) -> None:
        """非 CUSTOM 携带部门集合必须被拒（不得静默丢弃）。

        静默丢弃会制造"以为已限定、实际未限定"的错觉 ——
        而数据范围是越权防护的最后一层（`10 §10`）。
        """
        await _seed(db_session)
        token = await _login(api)
        response = await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope",
            json={"data_scope": "DEPARTMENT", "department_ids": [CHILD_DEPT_ID]},
            headers=_auth(token),
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# 权限变更立即生效（`00 §1#5` / `09 §7`）
# ---------------------------------------------------------------------------
class TestImmediateEffect:
    async def test_grant_change_is_visible_without_relogin(
        self, api: AsyncClient, db_session
    ) -> None:
        """授权变更后，**同一个令牌**下一次读取立即反映新权限。

        这条直接对应验收项"权限变更立即生效"：
        本 Phase 不启用任何权限缓存，权限上下文每请求实时计算，
        因此结构上不可能出现"改了权限但要重新登录才生效"。
        """
        await _seed(db_session)
        admin_token = await _login(api)
        holder_token = await _login(api, username=HOLDER_USERNAME)

        before = await _contract(api, holder_token)
        assert before["pages"] == []

        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": [PAGE_A, PAGE_B]},
            headers=_auth(admin_token),
        )

        # 仍用**同一个** holder 令牌
        after = await _contract(api, holder_token)
        assert {page["code"] for page in after["pages"]} == {"report:view", "report:export"}
        # 版本号必须单调上升（`09 §2` 要求返回版本；DD-04 未冻结其缓存语义）
        assert after["permission_version"] > before["permission_version"]

        # 再撤销 → 同样立即反映
        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": []},
            headers=_auth(admin_token),
        )
        revoked = await _contract(api, holder_token)
        assert revoked["pages"] == []

    async def test_disabling_a_resource_takes_effect_immediately(
        self, api: AsyncClient, db_session
    ) -> None:
        """**停用资源**也是一种权限变更：它必须立即从所有持有者的契约中消失。

        这条覆盖"授权行仍在、资源已停用"这一真实形态：
        契约只认未删除 + ACTIVE 的资源，因此停用立刻生效，
        不依赖任何清理任务或缓存失效。
        """
        await _seed(db_session)
        admin_token = await _login(api)
        holder_token = await _login(api, username=HOLDER_USERNAME)

        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/permissions/pages",
            json={"resourceIds": [PAGE_A]},
            headers=_auth(admin_token),
        )
        assert [page["code"] for page in (await _contract(api, holder_token))["pages"]] == [
            "report:view"
        ]

        disabled = await api.put(
            f"{ADMIN_PREFIX}/permission-resources/{PAGE_A}",
            json={"status": "DISABLED"},
            headers=_auth(admin_token),
        )
        assert disabled.status_code == 200

        after = await _contract(api, holder_token)
        assert after["pages"] == []

    async def test_data_scope_change_is_visible_in_contract(
        self, api: AsyncClient, db_session
    ) -> None:
        """数据范围变更同样必须立即反映到 `/auth/permissions`（第 6 项的闭环）。"""
        await _seed(db_session)
        admin_token = await _login(api)
        holder_token = await _login(api, username=HOLDER_USERNAME)

        before = await _contract(api, holder_token)
        assert before["data_scope"]["policy"] == "DEPARTMENT_CHILDREN"
        assert set(before["data_scope"]["department_ids"]) == {
            str(DEPT_ID),
            str(CHILD_DEPT_ID),
        }

        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/data-scope",
            json={"data_scope": "CUSTOM", "department_ids": [CHILD_DEPT_ID]},
            headers=_auth(admin_token),
        )

        after = await _contract(api, holder_token)
        assert after["data_scope"]["policy"] == "CUSTOM"
        assert after["data_scope"]["department_ids"] == [str(CHILD_DEPT_ID)]
