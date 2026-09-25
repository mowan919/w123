"""权限资源 CRUD 端点测试（Phase 8 / DD-20 §5.1.1 冻结契约）。

对应 Verification `008-dynamic-permission.md` 的两项：

- **页面可由后台配置**（`03 §5`）：Page 资源必须能通过管理接口建/改/删；
- **Menu 可关联多个 Page**（`00 §1#4` / `09 §4`）：多对多关联必须可经 HTTP 维护。

另有三项**安全性质**在此钉住：

1. 八个端点全部经后端 API 权限校验（`08 §10`），未认证 → 401、无权限 → 403；
2. **页面权限不等于接口权限**：拥有 PAGE 授权的用户调用资源管理接口仍必须被拒
   （`09 §3`："前端隐藏页面 = 安全"被明令禁止；反向同理）；
3. 路由级拒绝**必须留痕**（`10 §8`）—— 用真实落库验证，
   而不是只看响应码。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import buffer as log_buffer
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import PermissionResourceType, PermissionStatus
from app.models.logs import AuditLog
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

DEPT_ID = 61001
ROLE_RES_ADMIN = 61011
ROLE_NO_PERM = 61012
ROLE_PAGE_ONLY = 61013
RES_API_RESOURCE_MANAGE = 61021
RES_PAGE_GRANTED = 61022

USER_ID = 61101
NO_PERM_USER_ID = 61102
PAGE_ONLY_USER_ID = 61103
USERNAME = "p8-res-admin"
NO_PERM_USERNAME = "p8-res-noperm"
PAGE_ONLY_USERNAME = "p8-res-pageonly"
PASSWORD = "Perm-Res-Passw0rd!08"

#: DD-20 §5.1.1 冻结的 8 条资源端点。
FROZEN_PATHS = {
    f"{ADMIN_PREFIX}/permission-resources",
    f"{ADMIN_PREFIX}/permission-resources/tree",
    f"{ADMIN_PREFIX}/permission-resources/{{resource_id}}",
    f"{ADMIN_PREFIX}/permission-resources/{{resource_id}}/delete",
    f"{ADMIN_PREFIX}/permission-resources/{{resource_id}}/pages",
}

#: 前置 Phase 已交付、本次不得改动的路径（回归护栏）。
PREEXISTING_PATHS = {
    f"{ADMIN_PREFIX}/dicts",
    f"{ADMIN_PREFIX}/params",
    f"{ADMIN_PREFIX}/sessions",
    f"{AUTH_PREFIX}/login",
    f"{AUTH_PREFIX}/me",
    f"{AUTH_PREFIX}/mfa/setup",
}


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


@pytest.fixture
def flush_into_session(db_session: AsyncSession, isolate_log_flush: None) -> Iterator[None]:
    """让中间件的日志落库写入测试事务（请求结束后可按行断言）。

    与 `tests/test_trace_access_log.py::flush_into_session` 同一手法：
    默认 autouse 夹具把落库换成"吞掉写入"的替身，
    这里显式覆盖成真实会话，从而验证**端到端**的拒绝留痕。
    """

    @asynccontextmanager
    async def provider() -> AsyncIterator[AsyncSession]:
        yield db_session

    log_buffer.set_session_provider(provider)
    try:
        yield
    finally:
        log_buffer.set_session_provider(None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(response: Response) -> Any:
    return response.json()["data"]


async def _seed(session: AsyncSession) -> None:
    """三个用户：资源管理员 / 无任何权限 / 只有页面权限（无接口权限）。

    第三个用户是本文件的关键前提：它证明"前端权限（PAGE）"
    与"后端接口权限（API resource_code）"是**两件事**。
    """
    await make_department(session, department_id=DEPT_ID, department_code="P8-RES-DEPT")
    for role_id, code in (
        (ROLE_RES_ADMIN, "P8_RES_ADMIN"),
        (ROLE_NO_PERM, "P8_RES_NONE"),
        (ROLE_PAGE_ONLY, "P8_RES_PAGE_ONLY"),
    ):
        await make_role(session, role_id=role_id, role_code=code)

    await make_permission_resource(
        session,
        resource_id=RES_API_RESOURCE_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="PERMISSION_RESOURCE_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/permission-resources",
        status=PermissionStatus.ACTIVE,
    )
    await link_role_permission(session, role_id=ROLE_RES_ADMIN, resource_id=RES_API_RESOURCE_MANAGE)

    # 一个真实的 PAGE 资源，授权给"只有页面权限"的用户。
    await make_permission_resource(
        session,
        resource_id=RES_PAGE_GRANTED,
        resource_type=PermissionResourceType.PAGE,
        resource_code="report:view",
        route_path="/reports",
        component_path="views/report/index.vue",
    )
    await link_role_permission(session, role_id=ROLE_PAGE_ONLY, resource_id=RES_PAGE_GRANTED)

    for user_id, username, role_id in (
        (USER_ID, USERNAME, ROLE_RES_ADMIN),
        (NO_PERM_USER_ID, NO_PERM_USERNAME, ROLE_NO_PERM),
        (PAGE_ONLY_USER_ID, PAGE_ONLY_USERNAME, ROLE_PAGE_ONLY),
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
    """走真实登录拿令牌（授权依赖需要重建操作者上下文）。"""
    response = await api.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return _data(response)["access_token"]


def _page_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resource_type": "PAGE",
        "resource_code": "order:list",
        "resource_name": "订单列表",
        "route_path": "/orders",
        "component_path": "views/order/list.vue",
        "sort_order": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 路由面
# ---------------------------------------------------------------------------
class TestRouteSurface:
    """路由面必须与冻结契约**严格一致**（多一个或少一个都是缺陷）。"""

    def test_permission_resource_paths_match_the_frozen_contract(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        assert paths >= FROZEN_PATHS, f"缺少端点：{FROZEN_PATHS - paths}"
        actual = {path for path in paths if "/permission-resources" in path}
        assert actual == FROZEN_PATHS, f"路由面与 DD-20 §5.1.1 契约不符：{actual}"

    def test_existing_phase_paths_are_untouched(self, app: FastAPI) -> None:
        """本 Phase 只新增权限相关路径，不得影响既有端点。"""
        paths = set(app.openapi()["paths"])
        assert paths >= PREEXISTING_PATHS, f"既有端点丢失：{PREEXISTING_PATHS - paths}"

    async def test_tree_path_is_not_shadowed_by_the_id_path(
        self, api: AsyncClient, db_session
    ) -> None:
        """`/permission-resources/tree` 必须真的命中树端点，而不是被 ID 端点吞掉。

        若 `/{resource_id}` 先注册，`tree` 会被当成 ID 交给 `int` 解析，
        返回 **422 而不是 200** —— 两个装饰器各自都"看起来正确"，
        这类顺序缺陷只能靠**真实请求**发现（路由对象列表在这里被框架包装，
        读不出声明顺序）。
        """
        await _seed(db_session)
        token = await _login(api)
        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"resourceType": "MENU"},
            headers=_auth(token),
        )
        assert response.status_code != 422, response.text
        assert response.status_code == 200
        assert isinstance(_data(response), list)


# ---------------------------------------------------------------------------
# 访问控制（`08 §10` 后端强制授权）
# ---------------------------------------------------------------------------
class TestAccessControl:
    async def test_anonymous_is_rejected_with_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        calls = (
            ("get", f"{ADMIN_PREFIX}/permission-resources", None),
            ("post", f"{ADMIN_PREFIX}/permission-resources", _page_payload()),
            ("get", f"{ADMIN_PREFIX}/permission-resources/tree?resourceType=MENU", None),
            ("get", f"{ADMIN_PREFIX}/permission-resources/1", None),
            ("put", f"{ADMIN_PREFIX}/permission-resources/1", {"resource_name": "X"}),
            ("post", f"{ADMIN_PREFIX}/permission-resources/1/delete", None),
            ("get", f"{ADMIN_PREFIX}/permission-resources/1/pages", None),
            ("put", f"{ADMIN_PREFIX}/permission-resources/1/pages", {"pageIds": []}),
        )
        for method, path, body in calls:
            response = await getattr(api, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001, path

    async def test_without_permission_is_rejected_with_403(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)

        calls = (
            ("get", f"{ADMIN_PREFIX}/permission-resources", None),
            ("post", f"{ADMIN_PREFIX}/permission-resources", _page_payload()),
            ("get", f"{ADMIN_PREFIX}/permission-resources/tree?resourceType=MENU", None),
            ("get", f"{ADMIN_PREFIX}/permission-resources/1", None),
            ("put", f"{ADMIN_PREFIX}/permission-resources/1", {"resource_name": "X"}),
            ("post", f"{ADMIN_PREFIX}/permission-resources/1/delete", None),
            ("get", f"{ADMIN_PREFIX}/permission-resources/1/pages", None),
            ("put", f"{ADMIN_PREFIX}/permission-resources/1/pages", {"pageIds": []}),
        )
        for method, path, body in calls:
            response = await getattr(api, method)(
                path, headers=_auth(token), **({"json": body} if body else {})
            )
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

    async def test_page_permission_does_not_grant_api_authorization(
        self, api: AsyncClient, db_session
    ) -> None:
        """**本 Phase 最重要的一条安全性质**（`09 §3` 的直接落地）。

        该用户持有 `report:view` 这个 PAGE 资源授权 —— 也就是说
        `/auth/permissions` 会（正确地）把它作为"可访问页面"下发，
        前端会渲染出该页面与入口。

        但这**不意味着**他能调用资源管理接口。若后端把"有页面权限"
        当成"有接口权限"，那么任何人只要被分配了任意一个页面，
        就能改整个权限体系 —— 而前端隐藏恰恰不能作为边界（`5.1`）。

        因此：前端拿到什么，与后端放行什么，必须是**两条独立的判定链**。
        """
        await _seed(db_session)
        token = await _login(api, username=PAGE_ONLY_USERNAME)

        # 先确认契约侧确实下发了该页面（否则本用例变成"什么都没发生"的假通过）
        contract = await api.get(f"{AUTH_PREFIX}/permissions", headers=_auth(token))
        assert contract.status_code == 200
        assert [page["code"] for page in _data(contract)["pages"]] == ["report:view"]

        # 同一个令牌调用资源管理接口 → 必须仍被拒。
        response = await api.get(f"{ADMIN_PREFIX}/permission-resources", headers=_auth(token))
        assert response.status_code == 403
        assert response.json()["code"] == 403001

    async def test_route_level_denial_is_audited(
        self, api: AsyncClient, db_session, flush_into_session: None
    ) -> None:
        """路由级拒绝必须写 FAILURE 审计（`10 §8`）。

        路由级授权发生在**服务层之前**。若这里不留痕，"有人反复尝试调用
        无权接口"在审计里完全不可见 —— 而这正好是最需要留证的行为之一。
        本用例走**真实落库**（不是只看响应码），验证 `audit_logs` 里有那一行。
        """
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)

        response = await api.get(f"{ADMIN_PREFIX}/permission-resources", headers=_auth(token))
        assert response.status_code == 403

        rows = (
            (
                await db_session.execute(
                    select(AuditLog).where(
                        AuditLog.operator_id == NO_PERM_USER_ID,
                        AuditLog.action == "PERMISSION_RESOURCE_READ",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows, "路由级拒绝没有留下审计行"
        assert rows[-1].result == "FAILURE"
        assert rows[-1].error_code == 403001
        assert rows[-1].resource_type == "PERMISSION_RESOURCE"


# ---------------------------------------------------------------------------
# 页面可由后台配置（`03 §5`）
# ---------------------------------------------------------------------------
class TestPageCrud:
    async def test_page_can_be_created_read_updated_and_deleted(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)

        created = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json=_page_payload(),
            headers=_auth(token),
        )
        assert created.status_code == 200, created.text
        page = _data(created)
        # 业务 ID 必须序列化为字符串（`00 §6`）
        assert isinstance(page["id"], str)
        assert page["resource_type"] == "PAGE"
        assert page["route_path"] == "/orders"
        assert page["status"] == "ACTIVE"

        fetched = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/{page['id']}", headers=_auth(token)
        )
        assert fetched.status_code == 200
        assert _data(fetched)["resource_code"] == "order:list"

        updated = await api.put(
            f"{ADMIN_PREFIX}/permission-resources/{page['id']}",
            json={"resource_name": "订单管理", "status": "DISABLED"},
            headers=_auth(token),
        )
        assert updated.status_code == 200
        assert _data(updated)["resource_name"] == "订单管理"
        assert _data(updated)["status"] == "DISABLED"

        deleted = await api.post(
            f"{ADMIN_PREFIX}/permission-resources/{page['id']}/delete",
            headers=_auth(token),
        )
        assert deleted.status_code == 200
        assert _data(deleted)["status"] == "DISABLED"

        # 逻辑删除后详情不再可见（不是 500，也不是"仍能读到"）
        gone = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/{page['id']}", headers=_auth(token)
        )
        assert gone.status_code == 404

    async def test_page_without_route_is_rejected(self, api: AsyncClient, db_session) -> None:
        """类型专属列的形状规则必须生效（PAGE 必须有路由与组件）。

        规则来源是 `app.models.permission.TYPE_REQUIRED_COLUMNS`，
        与数据库 CHECK 同一份定义；应用层先拒绝是为了给出可用的 400，
        而不是让 INSERT 撞约束后变成 500。
        """
        await _seed(db_session)
        token = await _login(api)
        payload = _page_payload()
        payload.pop("route_path")
        response = await api.post(
            f"{ADMIN_PREFIX}/permission-resources", json=payload, headers=_auth(token)
        )
        assert response.status_code == 400
        assert "route_path" in response.json()["message"]

    async def test_shape_violation_across_types_is_rejected(
        self, api: AsyncClient, db_session
    ) -> None:
        """给 PAGE 塞 `api_path` 必须被拒（"看起来生效、实际没有"的典型来源）。"""
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json=_page_payload(api_path="/api/v1/admin/x"),
            headers=_auth(token),
        )
        assert response.status_code == 400

    async def test_delete_is_rejected_while_referenced(self, api: AsyncClient, db_session) -> None:
        """仍有角色授权引用时删除必须被拒（409），而不是级联清理。

        静默清理会同时改变多个角色的有效权限，影响面不可见；
        拒绝则强制管理员显式决定（与 `03 §4` 的取向一致）。
        """
        await _seed(db_session)
        token = await _login(api)

        created = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json=_page_payload(resource_code="order:granted"),
            headers=_auth(token),
        )
        page_id = _data(created)["id"]

        # 授权给"只有页面权限"的角色（该角色存在即形成引用）
        await link_role_permission(db_session, role_id=ROLE_PAGE_ONLY, resource_id=int(page_id))

        response = await api.post(
            f"{ADMIN_PREFIX}/permission-resources/{page_id}/delete",
            headers=_auth(token),
        )
        assert response.status_code == 409
        assert response.json()["code"] == 409001

    async def test_list_filters_by_type_and_keyword(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json=_page_payload(),
            headers=_auth(token),
        )

        listed = await api.get(
            f"{ADMIN_PREFIX}/permission-resources",
            params={"resourceType": "PAGE", "keyword": "订单", "pageNum": 1, "pageSize": 10},
            headers=_auth(token),
        )
        assert listed.status_code == 200
        body = _data(listed)
        assert body["total"] == 1
        assert body["pageNum"] == 1
        assert body["list"][0]["resource_code"] == "order:list"

        # 类型过滤必须真的生效：同样的关键字按 MENU 过滤应为空
        other_type = await api.get(
            f"{ADMIN_PREFIX}/permission-resources",
            params={"resourceType": "MENU", "keyword": "订单"},
            headers=_auth(token),
        )
        assert _data(other_type)["total"] == 0


# ---------------------------------------------------------------------------
# Menu 可关联多个 Page（`00 §1#4`）
# ---------------------------------------------------------------------------
class TestMenuPages:
    async def test_menu_can_link_multiple_pages(self, api: AsyncClient, db_session) -> None:
        """一个 Menu 关联多个 Page，且可整体替换（`00 §1#4` / `09 §4`）。"""
        await _seed(db_session)
        token = await _login(api)

        menu = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "nav:order",
                    "resource_name": "订单",
                    "icon": "shopping",
                },
                headers=_auth(token),
            )
        )
        page_a = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json=_page_payload(resource_code="order:list"),
                headers=_auth(token),
            )
        )
        page_b = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json=_page_payload(resource_code="order:detail", route_path="/orders/:id"),
                headers=_auth(token),
            )
        )

        linked = await api.put(
            f"{ADMIN_PREFIX}/permission-resources/{menu['id']}/pages",
            json={"pageIds": [page_a["id"], page_b["id"]]},
            headers=_auth(token),
        )
        assert linked.status_code == 200, linked.text
        assert {page["resource_code"] for page in _data(linked)["pages"]} == {
            "order:list",
            "order:detail",
        }

        # 读回来必须是同一集合（持久化生效）
        read_back = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/{menu['id']}/pages", headers=_auth(token)
        )
        assert read_back.status_code == 200
        assert len(_data(read_back)["pages"]) == 2

        # 整体替换：空数组 = 解除全部关联（PUT 语义幂等）
        cleared = await api.put(
            f"{ADMIN_PREFIX}/permission-resources/{menu['id']}/pages",
            json={"pageIds": []},
            headers=_auth(token),
        )
        assert cleared.status_code == 200
        assert _data(cleared)["pages"] == []

    async def test_non_page_resource_cannot_be_linked(self, api: AsyncClient, db_session) -> None:
        """把非 PAGE 资源关联进菜单必须被拒（否则导航会指向不可判权的东西）。

        `menu_pages` 的类型正确性由**应用层**保证：外键只能约束"行存在"，
        表达不了"这一行必须是 PAGE 类型"。
        """
        await _seed(db_session)
        token = await _login(api)

        menu = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "nav:order",
                    "resource_name": "订单",
                },
                headers=_auth(token),
            )
        )
        other_menu = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "nav:other",
                    "resource_name": "其他",
                },
                headers=_auth(token),
            )
        )
        response = await api.put(
            f"{ADMIN_PREFIX}/permission-resources/{menu['id']}/pages",
            json={"pageIds": [other_menu["id"]]},
            headers=_auth(token),
        )
        assert response.status_code == 400

    async def test_pages_of_non_menu_resource_is_rejected(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)
        page = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json=_page_payload(),
                headers=_auth(token),
            )
        )
        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/{page['id']}/pages", headers=_auth(token)
        )
        assert response.status_code == 400

    async def test_menu_hierarchy_is_returned_by_tree(self, api: AsyncClient, db_session) -> None:
        """`GET /permission-resources/tree?resourceType=MENU` 返回导航层级。"""
        await _seed(db_session)
        token = await _login(api)

        parent = _data(
            await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "nav:system",
                    "resource_name": "系统管理",
                },
                headers=_auth(token),
            )
        )
        await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json={
                "resource_type": "MENU",
                "resource_code": "nav:system:user",
                "resource_name": "用户",
                "parent_id": parent["id"],
            },
            headers=_auth(token),
        )

        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"resourceType": "MENU"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        nodes = _data(response)
        assert len(nodes) == 1
        assert nodes[0]["resource"]["resource_code"] == "nav:system"
        assert nodes[0]["children"][0]["resource"]["resource_code"] == "nav:system:user"

    async def test_tree_requires_resource_type(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.get(f"{ADMIN_PREFIX}/permission-resources/tree", headers=_auth(token))
        assert response.status_code == 400
