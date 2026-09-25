"""前端动态权限契约的 HTTP 层测试（Verification 008 的主战场）。

对应 Verification `008-dynamic-permission.md` 的十一项中，
本文件负责：

| 项 | 内容 | 本文件如何证明 |
|---|---|---|
| 1 | 后端可返回页面权限 | 响应 `pages[]`（含 routePath / componentPath） |
| 2 | 后端可返回菜单权限 | 响应 `menus[]`（含层级 / 图标 / 可访问页面） |
| 3 | 后端可返回按钮权限 | 响应 `buttons[]`（含所属页面） |
| 4 | 后端可返回 API 权限 | 响应 `apis[]`，且与实际后端判权**分开**验证 |
| 5 | 后端可返回字段权限 | 响应 `fields[]`（四级取值 + 所属页面） |
| 6 | 后端可返回 data scope | 响应 `data_scope`（策略 + 部门集合 + 是否含本人） |
| 9 | 前端可据配置动态生成 route/menu | **测试内实现一个独立消费者**，仅凭响应构造出路由表与菜单树 |
| 10 | 前端变化不影响后端 API 安全 | 配对用例：有页面/按钮 ≠ 有接口；有接口 ≠ 有页面 |

关于第 9 项的做法说明
--------------------
本仓库**没有前端工程**，因此无法交付"前端代码"。可以交付、也必须交付的是
**契约的充分性**证明：消费方只拿到这份 JSON 就能生成路由与导航，
不需要任何硬编码的权限常量。

因此本文件里写了一个**独立的消费者实现**（`build_route_table` /
`build_menu_tree` / `attach_buttons`）—— 它扮演前端的角色，
只读响应、不读数据库、不引用任何 Python 权限常量。
若契约缺少 `route_path` / `component_path` / `parent_id` / `page_ids` 中的任何一项，
这个消费者就构造不出结果，用例立刻失败。这样"契约足够用"是可执行的断言，
而不是一句自评。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.auth.actor import SUPER_ADMIN_ROLE_CODE
from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import (
    FieldAccessLevel,
    PermissionResourceType,
    PermissionStatus,
)
from tests.factories import (
    link_menu_page,
    link_role_field_permission,
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
PERMISSIONS_PATH = f"{AUTH_PREFIX}/permissions"

DEPT_ID = 63001
CHILD_DEPT_ID = 63002

ROLE_UI = 63011
ROLE_API = 63012
ROLE_SUPER = 63013
ROLE_EMPTY = 63014

RES_API_DICT_MANAGE = 63021

USER_UI = 63201
USER_API = 63202
USER_SUPER = 63203
USER_ROLE_LESS = 63204
USER_MUST_CHANGE = 63205
USER_UI_NAME = "p8-dyn-ui"
USER_API_NAME = "p8-dyn-api"
USER_SUPER_NAME = "p8-dyn-super"
USER_ROLE_LESS_NAME = "p8-dyn-norole"
USER_MUST_CHANGE_NAME = "p8-dyn-mustchange"
PASSWORD = "Dyn-Perm-Passw0rd!08"

PAGE_DASH = 63301
PAGE_SECRET = 63302
MENU_MAIN = 63303
MENU_EMPTY = 63304
BUTTON_EXPORT = 63305
FIELD_PHONE = 63306


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
    await make_department(session, department_id=DEPT_ID, department_code="P8-DYN-DEPT")
    await make_department(
        session, department_id=CHILD_DEPT_ID, department_code="P8-DYN-CHILD", parent_id=DEPT_ID
    )

    for role_id, code, scope in (
        (ROLE_UI, "P8_DYN_UI", DataScope.DEPARTMENT_CHILDREN),
        (ROLE_API, "P8_DYN_API", DataScope.DEPARTMENT_CHILDREN),
        (ROLE_SUPER, SUPER_ADMIN_ROLE_CODE, DataScope.ALL),
        (ROLE_EMPTY, "P8_DYN_EMPTY", DataScope.DEPARTMENT_CHILDREN),
    ):
        await make_role(session, role_id=role_id, role_code=code, data_scope=scope)

    await make_permission_resource(
        session,
        resource_id=RES_API_DICT_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="DICT_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/dicts",
        status=PermissionStatus.ACTIVE,
    )
    await link_role_permission(session, role_id=ROLE_API, resource_id=RES_API_DICT_MANAGE)

    await make_permission_resource(
        session,
        resource_id=PAGE_DASH,
        resource_type=PermissionResourceType.PAGE,
        resource_code="dashboard:view",
        resource_name="仪表盘",
        sort_order=1,
        route_path="/dashboard",
        component_path="views/dashboard/index.vue",
    )
    await make_permission_resource(
        session,
        resource_id=PAGE_SECRET,
        resource_type=PermissionResourceType.PAGE,
        resource_code="secret:view",
        resource_name="未授权页面",
        sort_order=2,
        route_path="/secret",
        component_path="views/secret/index.vue",
    )
    await make_permission_resource(
        session,
        resource_id=MENU_MAIN,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:dashboard",
        resource_name="概览",
        icon="home",
        sort_order=1,
    )
    await make_permission_resource(
        session,
        resource_id=MENU_EMPTY,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:secret",
        resource_name="机密",
        sort_order=2,
    )
    await make_permission_resource(
        session,
        resource_id=BUTTON_EXPORT,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="dashboard:export",
        resource_name="导出",
        parent_id=PAGE_DASH,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_PHONE,
        resource_type=PermissionResourceType.FIELD,
        resource_code="dashboard:phone",
        field_key="phone",
        owner_resource_id=PAGE_DASH,
    )

    await link_menu_page(session, menu_id=MENU_MAIN, page_id=PAGE_DASH)
    await link_menu_page(session, menu_id=MENU_MAIN, page_id=PAGE_SECRET)
    await link_menu_page(session, menu_id=MENU_EMPTY, page_id=PAGE_SECRET)

    # 前端权限（页面/菜单/按钮/字段）与后端接口权限**分开**授予：
    # ROLE_UI 拿到界面元素，ROLE_API 拿到接口 —— 用于证明两条判定链互相独立。
    for resource_id in (PAGE_DASH, MENU_MAIN, MENU_EMPTY, BUTTON_EXPORT):
        await link_role_permission(session, role_id=ROLE_UI, resource_id=resource_id)
    await link_role_field_permission(
        session,
        role_id=ROLE_UI,
        field_id=FIELD_PHONE,
        access_level=FieldAccessLevel.READ_ONLY,
    )

    for user_id, username, role_id, extra in (
        (USER_UI, USER_UI_NAME, ROLE_UI, {}),
        (USER_API, USER_API_NAME, ROLE_API, {}),
        (USER_SUPER, USER_SUPER_NAME, ROLE_SUPER, {}),
        (USER_ROLE_LESS, USER_ROLE_LESS_NAME, None, {}),
        (USER_MUST_CHANGE, USER_MUST_CHANGE_NAME, ROLE_UI, {"must_change_password": True}),
    ):
        await make_user(
            session,
            user_id=user_id,
            username=username,
            department_id=DEPT_ID,
            password=PASSWORD,
            password_changed_at=utc_now(),
            **extra,
        )
        if role_id is not None:
            await link_user_role(session, user_id=user_id, role_id=role_id)


async def _login(api: AsyncClient, *, username: str) -> str:
    response = await api.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return _data(response)["access_token"]


async def _permissions(api: AsyncClient, token: str) -> dict[str, Any]:
    response = await api.get(PERMISSIONS_PATH, headers=_auth(token))
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------------------------
# 前端消费者的参考实现（扮演前端角色，只读响应）
# ---------------------------------------------------------------------------
def build_route_table(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """仅凭契约构造前端路由表。

    这是"第 9 项"的可执行证据：消费方需要 `route_path` 与 `component_path`，
    不需要任何硬编码的权限常量。
    """
    return [
        {
            "name": page["code"],
            "path": page["route_path"],
            "component": page["component_path"],
        }
        for page in contract["pages"]
    ]


def build_menu_tree(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """仅凭契约构造菜单树，并**丢弃没有任何可访问页面的空菜单**。

    空菜单的裁剪是**前端策略**（后端只保证下发的都是已授权的）：
    `nav:secret` 被授权但它关联的页面都不可访问，消费者据此不渲染它。
    """
    accessible = {page["id"] for page in contract["pages"]}
    nodes = {
        menu["id"]: {
            "code": menu["code"],
            "title": menu["name"],
            "icon": menu.get("icon"),
            "page_ids": [pid for pid in menu.get("page_ids", []) if pid in accessible],
            "children": [],
        }
        for menu in contract["menus"]
    }
    roots: list[dict[str, Any]] = []
    for menu in contract["menus"]:
        node = nodes[menu["id"]]
        parent_id = menu.get("parent_id")
        if parent_id is not None and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return [node for node in roots if node["page_ids"] or node["children"]]


def attach_buttons(contract: dict[str, Any]) -> dict[str, list[str]]:
    """把按钮挂到所属页面上（按钮按 `parent_id` 表达归属）。"""
    mapping: dict[str, list[str]] = {}
    for button in contract["buttons"]:
        mapping.setdefault(button["parent_id"], []).append(button["code"])
    return mapping


def group_fields_by_page(contract: dict[str, Any]) -> dict[str, dict[str, str]]:
    """把字段策略按所属页面分组（前端据此决定字段的显示/可编辑行为）。"""
    grouped: dict[str, dict[str, str]] = {}
    for field in contract["fields"]:
        grouped.setdefault(field["owner_resource_id"], {})[field["field_key"]] = field[
            "access_level"
        ]
    return grouped


def _collect_keys(payload: Any) -> set[str]:
    """递归收集 JSON 载荷中的全部**键名**（用于敏感字段检查）。"""
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(str(key))
            keys |= _collect_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            keys |= _collect_keys(item)
    return keys


# ---------------------------------------------------------------------------
# 路由面与认证
# ---------------------------------------------------------------------------
class TestRouteSurface:
    def test_permissions_endpoint_is_mounted_in_the_auth_domain(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        assert PERMISSIONS_PATH in paths
        # 不得在 admin 域再开一份（两个 auth 前缀 = 两份真相）
        assert "/api/v1/admin/auth/permissions" not in paths

    def test_endpoint_is_read_only(self, app: FastAPI) -> None:
        """该端点只读：不提供任何写方法（权限变更必须走授权/资源端点）。"""
        methods = set(app.openapi()["paths"][PERMISSIONS_PATH])
        assert methods == {"get"}, methods


class TestAuthentication:
    async def test_anonymous_is_rejected_with_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        response = await api.get(PERMISSIONS_PATH)
        assert response.status_code == 401
        assert response.json()["code"] == 401001

    async def test_forced_password_change_state_is_rejected_with_403(
        self, api: AsyncClient, db_session
    ) -> None:
        """强制改密期间**不**下发权限契约。

        此时客户端只应调用 `/auth/me` 与 `/auth/password`；
        若这里放行，等于让"必须改密"的用户先逛后台。
        401 也不合适：调用者是**已认证**的，用 401 会让客户端误判
        "登录失效"并清掉会话，用户反而走不到改密那一步。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_MUST_CHANGE_NAME)
        response = await api.get(PERMISSIONS_PATH, headers=_auth(token))
        assert response.status_code == 403
        assert response.json()["code"] == 403001

    async def test_role_less_user_still_gets_a_renderable_contract(
        self, api: AsyncClient, db_session
    ) -> None:
        """无角色用户必须得到 **200 + 空权限**，而不是 500。

        "新账号尚未分配角色"是正常状态。若这里 500，前端只能渲染故障页，
        运维会以为是服务端 bug —— 而正确的表现是"你暂时没有任何权限"。
        这也是 DD-21 在本 Phase 的落地形态（拒绝型上下文）。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_ROLE_LESS_NAME)
        response = await api.get(PERMISSIONS_PATH, headers=_auth(token))

        assert response.status_code == 200, response.text
        body = _data(response)
        assert body["pages"] == []
        assert body["menus"] == []
        assert body["buttons"] == []
        assert body["apis"] == []
        assert body["fields"] == []
        # `policy = null` 表达"无任何有效策略"；`department_ids = []` 表达"全拒"。
        # 用某个具体策略值顶替会把"没配"显示成"配了最窄策略"。
        assert body["data_scope"]["policy"] is None
        assert body["data_scope"]["department_ids"] == []
        assert body["is_super_admin"] is False


# ---------------------------------------------------------------------------
# 第 1–6 项：契约内容
# ---------------------------------------------------------------------------
class TestContractContent:
    async def test_response_expresses_all_seven_required_sections(
        self, api: AsyncClient, db_session
    ) -> None:
        """`09 §2` 的清单必须逐项出现在响应里（少一项 = 前端缺一块能力）。"""
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        assert set(body) >= {
            "user_id",
            "pages",
            "menus",
            "buttons",
            "apis",
            "fields",
            "data_scope",
            "permission_version",
        }

    async def test_pages_carry_route_and_component(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        assert [page["code"] for page in body["pages"]] == ["dashboard:view"]
        page = body["pages"][0]
        assert page["route_path"] == "/dashboard"
        assert page["component_path"] == "views/dashboard/index.vue"
        assert page["id"] == str(PAGE_DASH)

    async def test_menus_expose_hierarchy_icon_and_accessible_pages(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        menus = {menu["code"]: menu for menu in body["menus"]}
        assert set(menus) == {"nav:dashboard", "nav:secret"}
        assert menus["nav:dashboard"]["icon"] == "home"
        # 关键：与该用户已授权页面**求交**后的结果
        assert menus["nav:dashboard"]["page_ids"] == [str(PAGE_DASH)]
        # 该菜单关联的页面全不可访问 → 空列表（是否渲染由前端决定）
        assert menus["nav:secret"]["page_ids"] == []

    async def test_buttons_are_attached_to_their_page(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        assert [button["code"] for button in body["buttons"]] == ["dashboard:export"]
        assert body["buttons"][0]["parent_id"] == str(PAGE_DASH)

    async def test_apis_carry_method_and_path(self, api: AsyncClient, db_session) -> None:
        """API 段落的 `api_method` / `api_path` 仅作台账与展示（DD-20 §5.1.3）。

        用**持有接口授权**的那个用户验证：界面权限持有者（`ROLE_UI`）
        的 `apis` 必须为空 —— 两条链互不派生（见第 10 项的对应用例）。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_API_NAME)
        body = await _permissions(api, token)

        assert [api_item["code"] for api_item in body["apis"]] == ["DICT_MANAGE"]
        assert body["apis"][0]["api_method"] == "GET"
        assert body["apis"][0]["api_path"] == "/api/v1/admin/dicts"

        ui_token = await _login(api, username=USER_UI_NAME)
        ui_body = await _permissions(api, ui_token)
        assert ui_body["apis"] == []

    async def test_fields_carry_level_and_owner(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        assert len(body["fields"]) == 1
        field = body["fields"][0]
        assert field["field_key"] == "phone"
        assert field["access_level"] == "READ_ONLY"
        assert field["owner_resource_id"] == str(PAGE_DASH)

    async def test_data_scope_is_resolved_not_raw(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        assert body["data_scope"]["policy"] == "DEPARTMENT_CHILDREN"
        # DEPARTMENT_CHILDREN 必须已展开为"本部门 + 后代"
        assert set(body["data_scope"]["department_ids"]) == {str(DEPT_ID), str(CHILD_DEPT_ID)}
        assert body["data_scope"]["include_self"] is False

    async def test_super_admin_gets_the_whole_configured_surface(
        self, api: AsyncClient, db_session
    ) -> None:
        """超管的契约返回**全部有效资源**（JUDGMENT-8-01）。

        若返回空集合，超管登录后会看到一个空后台 —— 而真实授权是"全部"。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_SUPER_NAME)
        body = await _permissions(api, token)

        assert body["is_super_admin"] is True
        assert {page["code"] for page in body["pages"]} == {"dashboard:view", "secret:view"}
        assert {menu["code"] for menu in body["menus"]} == {"nav:dashboard", "nav:secret"}
        assert {button["code"] for button in body["buttons"]} == {"dashboard:export"}

    async def test_no_sensitive_material_leaks_into_the_contract(
        self, api: AsyncClient, db_session
    ) -> None:
        """契约只含权限元数据，不含任何凭据类字段（`00 §8` / `10 §4`）。

        检查分两层，缺一不可：

        - **键名**不得出现凭据类字段（递归遍历 JSON 键）；
        - **口令字面量**不得出现在响应文本里。

        ⚠️ 不能拿子串当键名判据：资源编码里出现 `secret`（如 `nav:secret`）
        是合法的业务标识，把它一律判为泄漏会造出一条**永远无法满足**的规则，
        最后必然被人调松。判据必须对准"字段名"这一真正的问题面。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        response = await api.get(PERMISSIONS_PATH, headers=_auth(token))
        body = _data(response)

        forbidden_keys = {
            "password",
            "password_hash",
            "access_token",
            "refresh_token",
            "mfa_secret",
            "secret",
            "token",
            "phone",
            "email",
        }
        leaked = sorted(_collect_keys(body) & forbidden_keys)
        assert leaked == [], f"契约中出现了凭据类字段：{leaked}"
        assert PASSWORD not in response.text


# ---------------------------------------------------------------------------
# 第 9 项：前端可据此后动态生成 route / menu
# ---------------------------------------------------------------------------
class TestDynamicGeneration:
    """用一个独立消费者证明**契约充分**（不需要任何硬编码权限常量）。"""

    async def test_route_table_can_be_generated_from_the_contract(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        routes = build_route_table(await _permissions(api, token))

        assert routes == [
            {
                "name": "dashboard:view",
                "path": "/dashboard",
                "component": "views/dashboard/index.vue",
            }
        ]
        # 未授权的页面绝不会出现在生成结果里（它不在 pages 中，消费者无从构造）
        assert all(route["path"] != "/secret" for route in routes)

    async def test_menu_tree_is_pruned_by_the_consumer(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        tree = build_menu_tree(await _permissions(api, token))

        assert [node["code"] for node in tree] == ["nav:dashboard"]
        assert tree[0]["page_ids"] == [str(PAGE_DASH)]
        assert tree[0]["children"] == []

    async def test_buttons_and_fields_are_wired_to_their_pages(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)

        buttons = attach_buttons(body)
        assert buttons[str(PAGE_DASH)] == ["dashboard:export"]

        fields = group_fields_by_page(body)
        assert fields[str(PAGE_DASH)] == {"phone": "READ_ONLY"}

    async def test_nested_menus_are_rendered_as_a_tree(self, api: AsyncClient, db_session) -> None:
        """层级菜单必须能被消费者还原（`parent_id` 是唯一依据）。

        通过管理端点建一个"父菜单 + 子菜单"的层级，再让持有者读取契约并构树 ——
        这条链路同时覆盖了"菜单配置面"与"菜单输出面"的衔接。
        """
        await _seed(db_session)
        admin_token = await _login(api, username=USER_SUPER_NAME)

        parent = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "nav:root",
                    "resource_name": "根菜单",
                },
                headers=_auth(admin_token),
            )
        )
        await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json={
                "resource_type": "MENU",
                "resource_code": "nav:root:child",
                "resource_name": "子菜单",
                "parent_id": parent["id"],
            },
            headers=_auth(admin_token),
        )
        # 把新菜单授权给 ROLE_UI 的持有者（经角色授权端点）
        new_menus = await api.get(
            f"{ADMIN_PREFIX}/permission-resources",
            params={"resourceType": "MENU"},
            headers=_auth(admin_token),
        )
        ids = [
            item["id"]
            for item in _data(new_menus)["list"]
            if item["resource_code"].startswith("nav:r")
        ]
        await api.put(
            f"{ADMIN_PREFIX}/roles/{ROLE_UI}/permissions/menus",
            json={"resourceIds": [*ids, str(MENU_MAIN)]},
            headers=_auth(admin_token),
        )

        token = await _login(api, username=USER_UI_NAME)
        tree = build_menu_tree(await _permissions(api, token))
        root = {node["code"]: node for node in tree}["nav:root"]
        assert [child["code"] for child in root["children"]] == ["nav:root:child"]


# ---------------------------------------------------------------------------
# 第 10 项：前端变化不影响后端 API 安全
# ---------------------------------------------------------------------------
class TestFrontendCannotAffectBackendAuthorization:
    """前端拿到的界面权限与后端放行的接口权限**是两条独立判定链**。"""

    async def test_interface_permissions_do_not_grant_api_access(
        self, api: AsyncClient, db_session
    ) -> None:
        """持有页面 / 菜单 / 按钮授权 ≠ 能调用对应接口。

        `ROLE_UI` 的持有者拿到 `dashboard:view` 页面与 `dashboard:export` 按钮
        （前端会渲染出"导出"按钮），但**没有**任何 API 授权。
        此时调用受保护接口必须仍然 403 —— 否则"把按钮藏起来"就成了安全边界，
        而 `09 §3` 明令禁止这一点。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)
        body = await _permissions(api, token)
        assert body["apis"] == []  # 前端侧确实"什么都没有"

        for path in (
            f"{ADMIN_PREFIX}/dicts",
            f"{ADMIN_PREFIX}/permission-resources",
            f"{ADMIN_PREFIX}/roles/1/permissions",
        ):
            response = await api.get(path, headers=_auth(token))
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

    async def test_api_authorization_works_without_any_interface_permission(
        self, api: AsyncClient, db_session
    ) -> None:
        """反向配对：没有页面授权也不妨碍接口授权生效。

        `ROLE_API` 的持有者契约里 `pages` 为空（前端看不到任何页面），
        但持有 `DICT_MANAGE` 的 API 授权 → 对应接口必须 200。

        这一对用例共同说明：**界面权限与接口权限各自独立生效**，
        任何一侧的变化都不会被另一侧"顺带"改变 ——
        因此"前端改了"不可能把后端变松，反之亦然。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_API_NAME)
        body = await _permissions(api, token)
        assert [api_item["code"] for api_item in body["apis"]] == ["DICT_MANAGE"]
        assert body["pages"] == []

        allowed = await api.get(f"{ADMIN_PREFIX}/dicts", headers=_auth(token))
        assert allowed.status_code == 200, allowed.text

    async def test_contract_endpoint_does_not_accept_a_target_user(
        self, api: AsyncClient, db_session
    ) -> None:
        """契约端点**不接受**任何"目标用户"入参：目标恒为令牌所指的本人。

        若接受 `userId`，任何登录用户都能枚举他人的权限树 ——
        查看他人权限属权限预览（`03 §11`），是另一条需要授权的能力。
        """
        await _seed(db_session)
        token = await _login(api, username=USER_UI_NAME)

        for params in (
            {"userId": USER_SUPER},
            {"user_id": USER_SUPER},
            {"username": USER_SUPER_NAME},
        ):
            response = await api.get(PERMISSIONS_PATH, params=params, headers=_auth(token))
            # 参数被忽略（200，仍返回本人权限）或显式拒绝（422）都可接受；
            # 不可接受的是"返回了别人的权限"。
            assert response.status_code in {200, 422}, params
            if response.status_code == 200:
                assert _data(response)["user_id"] == str(USER_UI)
