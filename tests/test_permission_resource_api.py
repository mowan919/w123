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
from app.models.permission import PermissionResource
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

    ⚠️ `PERMISSION_RESOURCE_MANAGE` 是**种子脚本**写入的真实数据
    （`scripts/seed_data.py`）。共享库里已经有这一行，直接建会撞
    `uq_permission_resources_type_code_active`，本文件 21 个用例会**整组**
    在装置阶段失败（OPERATION-11-01）。因此先查后建：有就复用它的 ID 授权，
    没有才新建 —— 用例要的是"该角色持有这个接口权限"，
    而不是"这一行必须由本用例创建"。
    """
    await make_department(session, department_id=DEPT_ID, department_code="P8-RES-DEPT")
    for role_id, code in (
        (ROLE_RES_ADMIN, "P8_RES_ADMIN"),
        (ROLE_NO_PERM, "P8_RES_NONE"),
        (ROLE_PAGE_ONLY, "P8_RES_PAGE_ONLY"),
    ):
        await make_role(session, role_id=role_id, role_code=code)

    seeded_api_id = (
        (
            await session.execute(
                select(PermissionResource.id).where(
                    PermissionResource.resource_type == PermissionResourceType.API,
                    PermissionResource.resource_code == "PERMISSION_RESOURCE_MANAGE",
                    PermissionResource.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if seeded_api_id is None:
        await make_permission_resource(
            session,
            resource_id=RES_API_RESOURCE_MANAGE,
            resource_type=PermissionResourceType.API,
            resource_code="PERMISSION_RESOURCE_MANAGE",
            api_method="GET",
            api_path="/api/v1/admin/permission-resources",
            status=PermissionStatus.ACTIVE,
        )
        manage_resource_id = RES_API_RESOURCE_MANAGE
    else:
        manage_resource_id = int(seeded_api_id)
    await link_role_permission(session, role_id=ROLE_RES_ADMIN, resource_id=manage_resource_id)

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
# 资源树用例的固定装置
# ---------------------------------------------------------------------------
#: 本组用例独占的 ID 段（避开 `_seed` 的 61001+ 与共享库的种子行）。
TREE_PAGE_ID = 61910
TREE_BUTTON_ID = 61911
TREE_OTHER_PAGE_ID = 61912
TREE_MENU_ID = 61913
TREE_SUB_MENU_ID = 61914
TREE_DISABLED_BUTTON_ID = 61915
TREE_FIELD_ID = 61916
TREE_ORPHAN_FIELD_ID = 61917
TREE_GONE_OWNER_PAGE_ID = 61918
SAME_KEY_A_ID = 61920
SAME_KEY_B_ID = 61921
UNRELATED_PAGE_ID = 61922

#: 仅在 `cr-same-key` 一致性用例里使用：**存的是大写、搜的是小写**。
#: 两条命中路径不同 —— 一条靠 `resource_code`，一条靠 `resource_name`。
SAME_KEY_CODE = "cr-same-key:alpha"
SAME_KEY_NAME = "CR-SAME-KEY 乙"


async def _seed_tree(session: AsyncSession) -> None:
    """一棵**跨类型**的小树，专供资源树用例。

    ```
    PAGE  cr-tree:page          ← 根（PAGE 不允许有父）
      ├─ BUTTON cr-tree:page:create   ACTIVE
      ├─ BUTTON cr-tree:page:delete   DISABLED
      └─ FIELD  cr-tree:page:phone    ← 归属走 owner_resource_id，不是 parent_id
    PAGE  cr-tree:other         ← 无关页面，用来验证"真的被筛掉了"
    PAGE  cr-tree:gone          ← **已软删**，用来验证 owner 不在批次里时不崩
    FIELD cr-tree:gone:field         ← owner_resource_id 指向上面那个已删页面
    MENU  cr-tree:menu          ← 根
      └─ MENU cr-tree:sub           ← MENU 内嵌套
    ```

    直接写库而不是走 HTTP：这些用例断言的是**读取**语义，
    用工厂能精确构造状态（例如一个 DISABLED 但未删除的按钮），
    也免得每棵树都要凑齐 PAGE / MENU 的形状必填列。
    """
    await make_permission_resource(
        session,
        resource_id=TREE_PAGE_ID,
        resource_type=PermissionResourceType.PAGE,
        resource_code="cr-tree:page",
        resource_name="CR 树页面",
        route_path="/cr-tree",
        component_path="cr/tree.vue",
    )
    await make_permission_resource(
        session,
        resource_id=TREE_BUTTON_ID,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="cr-tree:page:create",
        resource_name="CR 树按钮",
        parent_id=TREE_PAGE_ID,
    )
    await make_permission_resource(
        session,
        resource_id=TREE_DISABLED_BUTTON_ID,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="cr-tree:page:delete",
        resource_name="CR 树禁用按钮",
        parent_id=TREE_PAGE_ID,
        status=PermissionStatus.DISABLED,
    )
    # FIELD 的归属只能由 `owner_resource_id` 表达：`parent_id` 恒为空。
    # 构树若只认 `parent_id`，它就会变成没有归属的一级行。
    await make_permission_resource(
        session,
        resource_id=TREE_FIELD_ID,
        resource_type=PermissionResourceType.FIELD,
        resource_code="cr-tree:page:phone",
        resource_name="CR 树字段",
        field_key="phone",
        owner_resource_id=TREE_PAGE_ID,
    )
    await make_permission_resource(
        session,
        resource_id=TREE_OTHER_PAGE_ID,
        resource_type=PermissionResourceType.PAGE,
        resource_code="cr-tree:other",
        resource_name="CR 无关页面",
        route_path="/cr-other",
        component_path="cr/other.vue",
    )
    # 归属页面被软删：`owner_resource_id` 指向的是**已从批次里消失**的 ID。
    # `owner_resource_id` 有 FK，所以这里必须建出真实行再软删，
    # 不能直接写一个不存在的 ID。
    gone_owner = await make_permission_resource(
        session,
        resource_id=TREE_GONE_OWNER_PAGE_ID,
        resource_type=PermissionResourceType.PAGE,
        resource_code="cr-tree:gone",
        resource_name="CR 已删页面",
        route_path="/cr-gone",
        component_path="cr/gone.vue",
    )
    gone_owner.deleted_at = utc_now()
    await session.flush()
    await make_permission_resource(
        session,
        resource_id=TREE_ORPHAN_FIELD_ID,
        resource_type=PermissionResourceType.FIELD,
        resource_code="cr-tree:gone:field",
        resource_name="CR 无主字段",
        field_key="gone",
        owner_resource_id=TREE_GONE_OWNER_PAGE_ID,
    )
    await make_permission_resource(
        session,
        resource_id=TREE_MENU_ID,
        resource_type=PermissionResourceType.MENU,
        resource_code="cr-tree:menu",
        resource_name="CR 树菜单",
        # ⚠️ MENU **不得携带** route_path / component_path：
        # 它们在 `TYPE_OPTIONAL_COLUMNS[MENU]` 之外，数据库 CHECK
        # `ck_permission_resources_resource_type_fields` 会直接拒绝。
        # 菜单是纯导航分组，能点进去的页面由 PAGE 资源 + 菜单挂载关系决定。
        icon="menu",
    )
    await make_permission_resource(
        session,
        resource_id=TREE_SUB_MENU_ID,
        resource_type=PermissionResourceType.MENU,
        resource_code="cr-tree:menu:sub",
        resource_name="CR 子菜单",
        parent_id=TREE_MENU_ID,
        icon="menu",
    )


def _key(value: Any) -> str:
    """业务 ID 在 JSON 里是**字符串**（DD-20）、在本地是 int，比对前统一。"""
    return str(value)


def _walk(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """深度优先遍历树响应（含所有层级的子节点）。"""
    for node in nodes:
        yield node
        yield from _walk(node["children"])


def _find_node(nodes: list[dict[str, Any]], resource_id: int) -> dict[str, Any] | None:
    """按资源 ID 找节点；找不到返回 `None`，便于直接断言"不该出现"。"""
    for node in _walk(nodes):
        if _key(node["resource"]["id"]) == _key(resource_id):
            return node
    return None


def _child_ids(node: dict[str, Any]) -> list[str]:
    return [_key(child["resource"]["id"]) for child in node["children"]]


def _root_ids(nodes: list[dict[str, Any]]) -> set[str]:
    return {_key(node["resource"]["id"]) for node in nodes}


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

    async def test_menu_must_not_carry_route_path(self, api: AsyncClient, db_session) -> None:
        """给 MENU 填 `route_path` / `component_path` 必须被拒。

        菜单是**纯导航分组**：能点进去的页面由 PAGE 资源 + `menu_pages`
        关联决定，菜单自己不带路由。所以 `TYPE_REQUIRED_COLUMNS[MENU]` 为空、
        `TYPE_OPTIONAL_COLUMNS[MENU]` 只有 `parent_id` / `icon` ——
        其余类型专属列必须为 NULL，数据库 CHECK 也照此拒绝。

        这条规则值得单独钉住，因为**表单侧曾经反过来**：把 route_path /
        component_path 做成了 MENU 的必填项，于是"新增菜单"必然 400。
        前端按类型分支的必填规则必须与这里一致。
        """
        await _seed(db_session)
        token = await _login(api)

        for extra in ({"route_path": "/system/x"}, {"component_path": "system/x"}):
            response = await api.post(
                f"{ADMIN_PREFIX}/permission-resources",
                json={
                    "resource_type": "MENU",
                    "resource_code": "shape:menu",
                    "resource_name": "形状菜单",
                    **extra,
                },
                headers=_auth(token),
            )
            assert response.status_code == 400, response.text
            assert next(iter(extra)) in response.json()["message"]

        # 不带这两个列则必须成功 —— 否则"必须被拒"可能只是因为别的原因为被拒。
        ok = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json={
                "resource_type": "MENU",
                "resource_code": "shape:menu",
                "resource_name": "形状菜单",
                "icon": "menu",
            },
            headers=_auth(token),
        )
        assert ok.status_code == 200, ok.text

    async def test_button_requires_a_parent_page(self, api: AsyncClient, db_session) -> None:
        """BUTTON 没有 `parent_id` 必须被拒（按钮必须挂在某个页面上）。

        FIELD 同理由 `owner_resource_id` 归属页面。两条都是"表单少一个输入框
        就整类资源建不出来"的地方，所以在这里把后端口径写死：
        前端要能建 BUTTON / FIELD，就必须提供选父页面 / 归属页面的入口。
        """
        await _seed(db_session)
        token = await _login(api)

        response = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json={
                "resource_type": "BUTTON",
                "resource_code": "shape:btn",
                "resource_name": "形状按钮",
            },
            headers=_auth(token),
        )
        assert response.status_code == 400, response.text
        assert "parent_id" in response.json()["message"]

        field = await api.post(
            f"{ADMIN_PREFIX}/permission-resources",
            json={
                "resource_type": "FIELD",
                "resource_code": "shape:field",
                "resource_name": "形状字段",
                "field_key": "field:user.phone",
            },
            headers=_auth(token),
        )
        assert field.status_code == 400, field.text
        assert "owner_resource_id" in field.json()["message"]

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
        """`GET /permission-resources/tree?resourceType=MENU` 返回导航层级。

        ⚠️ 断言按**编码**定位节点，而不是 `len(nodes) == 1`：共享库里已经有
        十来个真实菜单资源，对全量数量下断言会让这条用例只在空库上通过。
        """
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
        parent_node = _find_node(_data(response), parent["id"])
        assert parent_node is not None
        assert [child["resource"]["resource_code"] for child in parent_node["children"]] == [
            "nav:system:user"
        ]
        # 只返回 MENU：同一次请求里 PATTERN 之外的类型一个都不该出现。
        assert all(node["resource"]["resource_type"] == "MENU" for node in _walk(_data(response)))

    async def test_tree_omitting_resource_type_covers_every_type(
        self, api: AsyncClient, db_session
    ) -> None:
        """省略 `resourceType` 时返回全类型树，且**跨类型父子必须真的连上**。

        这是本轮缺口的直接守卫。父子规则是跨类型的（`BUTTON → PAGE`、
        `API → PAGE`、`MENU → MENU`），按单类型取会让子节点因为
        "父不在同一批数据里"被**提升为根** —— 响应码仍是 200、
        结构看着也像一棵树，只有比对层级才看得出问题。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(f"{ADMIN_PREFIX}/permission-resources/tree", headers=_auth(token))
        assert response.status_code == 200, response.text
        nodes = _data(response)

        # 跨类型：BUTTON 与 FIELD 都必须挂在它们的 PAGE 下。
        # FIELD 的父边来自 `owner_resource_id`（DD-06），与 BUTTON 的
        # `parent_id` 是**两条不同的列** —— 只认 `parent_id` 的实现会让字段
        # 全部落到根层，界面上一眼就是"这几个没有任何分类"。
        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None, "全类型树里找不到 PAGE"
        assert _child_ids(page_node) == [
            _key(TREE_BUTTON_ID),
            _key(TREE_DISABLED_BUTTON_ID),
            _key(TREE_FIELD_ID),
        ], "BUTTON / FIELD 没有被挂在它们的 PAGE 下"
        # 子节点出现在根层 = "父不在同一批数据里"，正是单类型取法的症状。
        assert _key(TREE_BUTTON_ID) not in _root_ids(nodes)
        assert _key(TREE_FIELD_ID) not in _root_ids(nodes), "FIELD 掉到了根层 —— 归属丢失"
        # 同类型嵌套（MENU → MENU）在全类型树下同样要成立。
        menu_node = _find_node(nodes, TREE_MENU_ID)
        assert menu_node is not None
        assert _child_ids(menu_node) == [_key(TREE_SUB_MENU_ID)]

    async def test_field_hangs_under_its_owner_page(self, api: AsyncClient, db_session) -> None:
        """FIELD 的归属由 `owner_resource_id` 表达，树里必须挂在所属 PAGE 下。

        这是"四个字段权限在树里没有任何分类"那次的直接守卫：构树只认
        `parent_id` 时，FIELD 因为没有父被**提升为根** —— 响应仍是 200、
        结构仍像树，只在界面上表现为几个光秃秃的一级行。

        同时钉住两条边界：

        1. 归属页面**被软删**的字段不能消失、也不能报错，只能退化为根节点；
        2. 单类型树（`resourceType=FIELD`）里归属页面不在批次内，
           字段全部落在根层 —— 这是构树的固有语义，不是缺陷。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(f"{ADMIN_PREFIX}/permission-resources/tree", headers=_auth(token))
        assert response.status_code == 200, response.text
        nodes = _data(response)

        # 1. 有主的字段挂在页面下，不是根。
        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None
        assert _key(TREE_FIELD_ID) in _child_ids(page_node)
        assert _key(TREE_FIELD_ID) not in _root_ids(nodes)

        # 2. 归属页面已软删的字段：退化为根，但**不得丢失**。
        orphan = _find_node(nodes, TREE_ORPHAN_FIELD_ID)
        assert orphan is not None, "owner 已软删的 FIELD 被静默丢弃了"
        assert _key(TREE_ORPHAN_FIELD_ID) in _root_ids(nodes)
        assert _find_node(nodes, TREE_GONE_OWNER_PAGE_ID) is None, "已软删的页面不该出现"

        # 3. 单类型树的固有代价：owner 不在批次里 → 落在根层。
        single = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"resourceType": "FIELD"},
            headers=_auth(token),
        )
        assert single.status_code == 200, single.text
        single_nodes = _data(single)
        assert all(node["resource"]["resource_type"] == "FIELD" for node in _walk(single_nodes))
        assert _key(TREE_FIELD_ID) in _root_ids(single_nodes)

    async def test_tree_keyword_on_a_field_keeps_its_owner_page(
        self, api: AsyncClient, db_session
    ) -> None:
        """搜字段时，它所属的页面必须被当作**祖先**保留下来。

        筛选的"保留祖先"与构树必须是**同一条父边**。两边不一致时的症状很隐蔽：
        树是全类型树、字段确实挂对了，但用关键字搜字段时页面被裁掉 → 字段
        又变成根，"搜到了却看不出归属"。所以这条用例专门搜 FIELD 的编码。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"keyword": "cr-tree:page:phone"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        nodes = _data(response)

        assert _find_node(nodes, TREE_FIELD_ID) is not None
        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None, "字段的归属页面被裁掉了 —— 搜出来一个没有归属的字段"
        assert _child_ids(page_node) == [_key(TREE_FIELD_ID)]
        assert _find_node(nodes, TREE_BUTTON_ID) is None, "未命中的兄弟节点没有被裁掉"
        assert _find_node(nodes, TREE_OTHER_PAGE_ID) is None

    async def test_tree_with_resource_type_stays_single_type(
        self, api: AsyncClient, db_session
    ) -> None:
        """显式传 `resourceType` 时行为与从前一致：只返回该类型。

        同时也把单类型取法的**代价**钉在测试里 —— `resourceType=BUTTON` 时
        父页面不在范围内，按钮只能当根节点。这不是缺陷，是"按类型取树"的
        固有语义；写下来免得下次有人把它当成 bug 去"修"。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"resourceType": "PAGE"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        nodes = _data(response)

        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None
        assert page_node["children"] == [], "单类型树里不该出现别的类型"
        assert _find_node(nodes, TREE_BUTTON_ID) is None
        assert _find_node(nodes, TREE_MENU_ID) is None

    async def test_tree_keyword_keeps_ancestors_and_drops_non_matches(
        self, api: AsyncClient, db_session
    ) -> None:
        """关键词筛选保留命中项的**祖先**，并真把无关项筛掉。

        只保留命中项是错的做法：父节点被裁掉后，子节点会变成根，
        集合看着"筛选生效了"，但"这个按钮挂在哪个页面下"反而看不见了。
        只筛不删（忽略关键词）同样是错的 —— 那样 `TREE_OTHER_PAGE_ID` 会留在结果里。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"keyword": "cr-tree:page:create"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        nodes = _data(response)

        assert _find_node(nodes, TREE_BUTTON_ID) is not None
        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None, "祖先被裁掉了 —— 层级会因此丢失"
        assert _child_ids(page_node) == [_key(TREE_BUTTON_ID)]
        assert _find_node(nodes, TREE_OTHER_PAGE_ID) is None, "关键词没有真的筛掉无关项"

    async def test_tree_status_filter_keeps_ancestor_that_does_not_match(
        self, api: AsyncClient, db_session
    ) -> None:
        """状态筛选同样保留祖先，**即使祖先自身不满足该状态**。

        「祖先保留」按"可达性"而非"是否命中"判定：`status=DISABLED` 时那个
        ACTIVE 的父页面必须留下，否则禁用按钮会看一眼像是没有归属。
        同一父节点下未命中的兄弟节点则要被裁掉 —— 两者不能一起放过。
        """
        await _seed(db_session)
        await _seed_tree(db_session)
        token = await _login(api)

        response = await api.get(
            f"{ADMIN_PREFIX}/permission-resources/tree",
            params={"status": "DISABLED", "keyword": "cr-tree:page:delete"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        nodes = _data(response)

        assert _find_node(nodes, TREE_DISABLED_BUTTON_ID) is not None
        page_node = _find_node(nodes, TREE_PAGE_ID)
        assert page_node is not None, "ACTIVE 的父页面因不满足 status 被裁掉了"
        assert _child_ids(page_node) == [_key(TREE_DISABLED_BUTTON_ID)], (
            "未命中的兄弟节点没有被裁掉"
        )
        assert _find_node(nodes, TREE_BUTTON_ID) is None

    async def test_keyword_matches_the_same_rows_in_list_and_tree(
        self, api: AsyncClient, db_session
    ) -> None:
        """同一关键词在**列表**（SQL `ILIKE`）与**树**（内存匹配）里必须命中同一集合。

        这条是为"筛选有两套实现"专门加的：列表在 SQL 里筛，树必须取全量再在
        内存里裁（否则父节点被筛掉、层级丢失），于是同一条规则被写了两遍。
        两遍不一致时，用户会看到"列表里搜得到、树上搜不到"这种无法解释的现象
        —— 见 `app/repositories/permission.py` 的 `matches_keyword()`。

        搜索用**不同大小写**发起，一并把两边的"大小写不敏感"钉住：
        手写内存匹配最容易漏掉的就是 `.lower()`。
        """
        await _seed(db_session)
        token = await _login(api)

        by_code = await make_permission_resource(
            db_session,
            resource_id=SAME_KEY_A_ID,
            resource_type=PermissionResourceType.PAGE,
            resource_code=SAME_KEY_CODE,
            resource_name="CR 同口径甲",
            route_path="/cr-same-a",
            component_path="cr/same-a.vue",
        )
        by_name = await make_permission_resource(
            db_session,
            resource_id=SAME_KEY_B_ID,
            resource_type=PermissionResourceType.PAGE,
            resource_code="cr-same:beta",
            resource_name=SAME_KEY_NAME,
            route_path="/cr-same-b",
            component_path="cr/same-b.vue",
        )
        unrelated = await make_permission_resource(
            db_session,
            resource_id=UNRELATED_PAGE_ID,
            resource_type=PermissionResourceType.PAGE,
            resource_code="cr-other:gamma",
            resource_name="CR 无关丙",
            route_path="/cr-other-g",
            component_path="cr/other-g.vue",
        )

        # 只看本次建的三个：共享库里还有别的数据，不能对全量集合下断言。
        # `by_code` 按编码命中、`by_name` 按名称命中 —— 顺带证明两个字段都参与匹配。
        watched = {_key(by_code.id), _key(by_name.id), _key(unrelated.id)}
        expected = {_key(by_code.id), _key(by_name.id)}

        # **两个方向都要测**：
        # - 存大写、搜小写 → 需要把**待查文本**降大小写；
        # - 存小写、搜大写 → 需要把**关键词**降大小写。
        # 只测一个方向的话，漏掉另一半 `.lower()` 的实现也能全绿
        # （这是实测出来的：先只写了第一个方向，一个只摘掉关键词侧 `.lower()`
        # 的变异没被检出，用例其实是漏的）。
        for spelling in ("cr-same-key", "CR-SAME-KEY"):
            list_response = await api.get(
                f"{ADMIN_PREFIX}/permission-resources",
                params={"keyword": spelling, "pageSize": 100},
                headers=_auth(token),
            )
            tree_response = await api.get(
                f"{ADMIN_PREFIX}/permission-resources/tree",
                params={"keyword": spelling},
                headers=_auth(token),
            )
            assert list_response.status_code == 200, list_response.text
            assert tree_response.status_code == 200, tree_response.text

            list_hits = watched & {_key(item["id"]) for item in _data(list_response)["list"]}
            tree_hits = watched & {
                _key(node["resource"]["id"]) for node in _walk(_data(tree_response))
            }
            assert list_hits == expected, f"列表端点对 {spelling!r} 的匹配不符合预期"
            assert tree_hits == expected, f"树端点对 {spelling!r} 的匹配与列表不一致"
