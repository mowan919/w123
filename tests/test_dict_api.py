"""字典 / 系统参数的 HTTP 端点测试（Phase 7）。

分层说明
-------
本文件验证**接线**，不验证业务判定：

| 关注点 | 归谁 |
|---|---|
| 唯一性 / 软删除感知 / 级联 / 审计内容 | `tests/test_dict_service.py` |
| 参数的取值语义（回退 / DISABLED / 类型不符） | `tests/test_system_param.py` |
| **路由面 / 状态码 / 信封 / ID 序列化 / 访问控制** | 本文件 |

分开的理由：混在一起时失败原因会变模糊 —— "409 是因为唯一性判定错了，
还是因为路由没接上？"

覆盖点
-----
1. **路由面**：Phase 7 新增的端点**恰好**是 Spec 规定的那几个
   （`05 §4` / `08 §9` 的字典端点 + INTERIM-7-04 推导的参数端点），
   公开查询**不在** admin 域内。
2. **访问控制**：admin 域端点必须认证 + 持有 `DICT_MANAGE`；
   公开查询必须**已认证**（JUDGMENT-7-03）但不需要 `DICT_MANAGE`。
3. **权限分离**：`DICT_MANAGE` **不**隐含 `PARAM_MANAGE`
   （`05 §5` 要求字典与参数分离）—— 在 HTTP 层再钉一次。
4. **信封与序列化**：`{code, message, data}`；分页 `{list,total,pageNum,pageSize}`；
   字典项列表**不**分页；BIGINT 业务 ID 在 JSON 中是**字符串**（`07 §2`）。
5. **状态码**：400 / 403 / 404 / 409 / 422 各自可被触发，且不是 500。

事务与依赖覆盖
------------
`app.dependency_overrides[get_db]` 指向 `db_session`（外层事务 + SAVEPOINT），
端点里的 `commit()` 因此不会逃出用例边界。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

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
PUBLIC_PREFIX = "/api/v1"
AUTH_PREFIX = "/api/v1/auth"

DEPT_ID = 56001
ROLE_DICT_ADMIN = 56011
ROLE_NO_PERM = 56012
RES_API_DICT_MANAGE = 56021

USER_ID = 56101
NO_PERM_USER_ID = 56102
USERNAME = "dict-api-admin"
NO_PERM_USERNAME = "dict-api-noperm"
PASSWORD = "Dict-API-Passw0rd!07"

#: `08 §9` 的字典端点 + INTERIM-7-04 的参数端点（挂载于 `/api/v1/admin`）。
ADMIN_PATHS = {
    f"{ADMIN_PREFIX}/dicts",
    f"{ADMIN_PREFIX}/dicts/{{dict_type_id}}",
    f"{ADMIN_PREFIX}/dicts/{{dict_type_id}}/items",
    f"{ADMIN_PREFIX}/dicts/{{dict_type_id}}/items/{{item_id}}",
    f"{ADMIN_PREFIX}/params",
    f"{ADMIN_PREFIX}/params/{{param_id}}",
}

#: `05 §4` 的公开查询端点（**不在** admin 域）。
PUBLIC_DICT_PATH = f"{PUBLIC_PREFIX}/dicts/{{dict_code}}"


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


def _data(response: Response):
    """取出成功信封里的 `data`。"""
    return response.json()["data"]


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------
async def _seed(session) -> None:
    """一个持有 `DICT_MANAGE`（但**不**持有 `PARAM_MANAGE`）的用户 + 一个无权限用户。"""
    await make_department(session, department_id=DEPT_ID, department_code="DICT-API-DEPT")
    await make_role(session, role_id=ROLE_DICT_ADMIN, role_code="DICT_API_ADMIN")
    await make_role(session, role_id=ROLE_NO_PERM, role_code="DICT_API_NONE")
    await make_permission_resource(
        session,
        resource_id=RES_API_DICT_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="DICT_MANAGE",
        # API 行必须给出 method + path：`permission_resources` 有形状检查约束
        # （`ck_permission_resources_resource_type_fields`）。
        api_method="GET",
        api_path="/api/v1/admin/dicts",
        status=PermissionStatus.ACTIVE,
    )
    await link_role_permission(session, role_id=ROLE_DICT_ADMIN, resource_id=RES_API_DICT_MANAGE)

    for user_id, username, role_id in (
        (USER_ID, USERNAME, ROLE_DICT_ADMIN),
        (NO_PERM_USER_ID, NO_PERM_USERNAME, ROLE_NO_PERM),
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
    """登录并返回访问令牌。

    刻意走**真实登录**而不是伪造令牌：端点的授权依赖是
    `get_current_actor`，它自己要重建操作者上下文（含角色、数据范围）。
    绕过登录就等于把被测链路换掉了。
    """
    response = await api.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return _data(response)["access_token"]


async def _create_type(
    api: AsyncClient, token: str, *, dict_code: str = "user_status", **overrides
) -> dict:
    """建一个字典类型（默认字段取自 Spec `05 §2`）。"""
    payload = {
        "dict_code": dict_code,
        "dict_name": "用户状态",
        "description": "用户账号状态枚举",
        **overrides,
    }
    response = await api.post(f"{ADMIN_PREFIX}/dicts", json=payload, headers=_auth(token))
    assert response.status_code == 200, response.text
    return _data(response)


async def _create_item(
    api: AsyncClient, token: str, dict_type_id: str, *, item_value: str = "ACTIVE", **overrides
) -> dict:
    """建一个字典项。"""
    payload = {
        "item_label": "启用",
        "item_value": item_value,
        "item_code": item_value.lower(),
        "sort_order": 10,
        **overrides,
    }
    response = await api.post(
        f"{ADMIN_PREFIX}/dicts/{dict_type_id}/items", json=payload, headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------------------------
# 路由面
# ---------------------------------------------------------------------------
class TestRouteSurface:
    """Phase 7 新增的端点集必须与 Spec 逐一对应，既不缺也不多。"""

    def test_dictionary_and_param_paths_exist_exactly_as_specified(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        assert paths >= ADMIN_PATHS, f"缺少端点：{ADMIN_PATHS - paths}"

        actual = {path for path in paths if "/dicts" in path or "/params" in path}
        assert actual == ADMIN_PATHS | {PUBLIC_DICT_PATH}, f"路由面与规范不符：{actual}"

    def test_public_query_lives_outside_the_admin_namespace(self, app: FastAPI) -> None:
        """`05 §4` / `08 §9` 都把它写成 `/api/v1/dicts/{dictCode}`。

        如果它被挂到 `/admin` 下，"公开查询"就名不副实了 ——
        前端必须持有管理权限才能渲染下拉框。
        """
        paths = set(app.openapi()["paths"])
        assert PUBLIC_DICT_PATH in paths
        assert f"{ADMIN_PREFIX}/dicts/{{dict_code}}" not in paths

    def test_public_query_is_read_only(self, app: FastAPI) -> None:
        """公开域下只能读，且只引入这一个资源。

        `05 §4` 把公开查询定义为**查询**；若这里出现 `post`/`put`/`delete`，
        说明有人在公开域开了写入口 —— 那是未经授权的安全面扩张。
        顺便反向钉住"公开域只新增了这一个路径"。
        """
        paths = app.openapi()["paths"]
        assert set(paths[PUBLIC_DICT_PATH]) == {"get"}
        outside_admin = {path for path in paths if "/admin/" not in path}
        assert {path for path in outside_admin if "dict" in path} == {PUBLIC_DICT_PATH}

    def test_existing_phase_six_paths_are_untouched(self, app: FastAPI) -> None:
        """反向钉住：Phase 7 不得顺手改动既有资源域。

        只钉**真实存在**的既有端点：`/admin/roles` 与 `/admin/users` 的
        CRUD 因 CONFLICT-001（权限资源契约缺失）仍处于 BLOCKED，
        仓库里本来就没有它们 —— 把它们写进"必须存在"会凭空造出需求。
        """
        paths = set(app.openapi()["paths"])
        for path in (
            f"{ADMIN_PREFIX}/sessions",
            f"{ADMIN_PREFIX}/users/{{user_id}}/sessions/revoke-all",
            f"{AUTH_PREFIX}/login",
            f"{AUTH_PREFIX}/mfa/setup",
        ):
            assert path in paths, path


# ---------------------------------------------------------------------------
# 访问控制
# ---------------------------------------------------------------------------
class TestAccessControl:
    """`08 §10`：后端必须判权，不得只靠前端隐藏。"""

    async def test_admin_endpoints_require_authentication(self, api: AsyncClient) -> None:
        """每个 admin 域端点都必须拒绝未认证请求。

        刻意送上合法请求体：否则 401 可能只是因为"请求体不合法先报了 422"，
        这条用例在"认证依赖被误删"时依然会通过（假阳性）。
        """
        calls = (
            ("get", f"{ADMIN_PREFIX}/dicts", None),
            ("post", f"{ADMIN_PREFIX}/dicts", {"dict_code": "x", "dict_name": "X"}),
            ("get", f"{ADMIN_PREFIX}/dicts/1", None),
            ("put", f"{ADMIN_PREFIX}/dicts/1", {"dict_name": "X"}),
            ("delete", f"{ADMIN_PREFIX}/dicts/1", None),
            ("get", f"{ADMIN_PREFIX}/dicts/1/items", None),
            (
                "post",
                f"{ADMIN_PREFIX}/dicts/1/items",
                {"item_label": "L", "item_value": "V", "item_code": "c"},
            ),
            ("put", f"{ADMIN_PREFIX}/dicts/1/items/2", {"item_label": "L"}),
            ("delete", f"{ADMIN_PREFIX}/dicts/1/items/2", None),
            ("get", f"{ADMIN_PREFIX}/params", None),
            (
                "post",
                f"{ADMIN_PREFIX}/params",
                {
                    "param_key": "k",
                    "param_name": "K",
                    "param_type": "STRING",
                    "default_value": "x",
                },
            ),
            ("get", f"{ADMIN_PREFIX}/params/1", None),
            ("put", f"{ADMIN_PREFIX}/params/1", {"param_name": "K"}),
            ("delete", f"{ADMIN_PREFIX}/params/1", None),
        )
        for method, path, body in calls:
            response = await getattr(api, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001, path

    async def test_public_query_requires_authentication(self, api: AsyncClient, db_session) -> None:
        """JUDGMENT-7-03：Spec 未授权匿名访问，因此"公开"= 已认证即可读。

        这条断言是**安全边界的一部分**：若有人把 `get_current_actor`
        依赖从公开查询上摘掉，它会立刻失败。
        """
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token)

        anonymous = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status")
        assert anonymous.status_code == 401
        assert anonymous.json()["code"] == 401001

    async def test_admin_endpoints_reject_users_without_dict_manage(
        self, api: AsyncClient, db_session
    ) -> None:
        """已认证但无 `DICT_MANAGE` → 403（不是 401，也不是 200）。"""
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)

        calls = (
            ("get", f"{ADMIN_PREFIX}/dicts", None),
            ("post", f"{ADMIN_PREFIX}/dicts", {"dict_code": "x", "dict_name": "X"}),
            ("get", f"{ADMIN_PREFIX}/dicts/1", None),
            ("put", f"{ADMIN_PREFIX}/dicts/1", {"dict_name": "X"}),
            ("delete", f"{ADMIN_PREFIX}/dicts/1", None),
            ("get", f"{ADMIN_PREFIX}/dicts/1/items", None),
            (
                "post",
                f"{ADMIN_PREFIX}/dicts/1/items",
                {"item_label": "L", "item_value": "V", "item_code": "c"},
            ),
            ("put", f"{ADMIN_PREFIX}/dicts/1/items/2", {"item_label": "L"}),
            ("delete", f"{ADMIN_PREFIX}/dicts/1/items/2", None),
        )
        for method, path, body in calls:
            response = await getattr(api, method)(
                path, headers=_auth(token), **({"json": body} if body else {})
            )
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

    async def test_public_query_accepts_any_authenticated_user(
        self, api: AsyncClient, db_session
    ) -> None:
        """无 `DICT_MANAGE` 的普通登录用户**可以**读公开字典。

        这条与上一条成对存在：只钉"拒绝"不够，还要钉"不该拒的没被拒" ——
        否则把公开查询误挂到 `DICT_MANAGE` 上时无人发现，
        而真实后果是"普通用户的下拉框全空"。
        """
        await _seed(db_session)
        admin_token = await _login(api)
        await _create_type(api, admin_token)

        plain_token = await _login(api, username=NO_PERM_USERNAME)
        response = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status", headers=_auth(plain_token))
        assert response.status_code == 200
        assert _data(response)["dict_code"] == "user_status"

    async def test_dict_manage_does_not_imply_param_manage(
        self, api: AsyncClient, db_session
    ) -> None:
        """`05 §5`：字典与系统参数必须**分离**。

        参数承载运行时安全策略（例如 system 级 MFA 默认值），
        因此"能改字典"不得隐含"能改参数"。
        """
        await _seed(db_session)
        token = await _login(api)

        for method, path, body in (
            ("get", f"{ADMIN_PREFIX}/params", None),
            (
                "post",
                f"{ADMIN_PREFIX}/params",
                {
                    "param_key": "k",
                    "param_name": "K",
                    "param_type": "STRING",
                    "default_value": "x",
                },
            ),
            ("get", f"{ADMIN_PREFIX}/params/1", None),
            ("put", f"{ADMIN_PREFIX}/params/1", {"param_name": "K"}),
            ("delete", f"{ADMIN_PREFIX}/params/1", None),
        ):
            response = await getattr(api, method)(
                path, headers=_auth(token), **({"json": body} if body else {})
            )
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path


# ---------------------------------------------------------------------------
# 字典类型（HTTP）
# ---------------------------------------------------------------------------
class TestDictTypeHttp:
    async def test_crud_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)

        created = await _create_type(api, token)
        assert created["dict_code"] == "user_status"
        assert created["dict_name"] == "用户状态"
        assert created["status"] == "ACTIVE"

        fetched = await api.get(f"{ADMIN_PREFIX}/dicts/{created['id']}", headers=_auth(token))
        assert fetched.status_code == 200
        assert _data(fetched)["id"] == created["id"]

        updated = await api.put(
            f"{ADMIN_PREFIX}/dicts/{created['id']}",
            json={"dict_name": "用户状态（改）", "status": "DISABLED"},
            headers=_auth(token),
        )
        assert updated.status_code == 200
        assert _data(updated)["dict_name"] == "用户状态（改）"
        assert _data(updated)["status"] == "DISABLED"

        deleted = await api.delete(f"{ADMIN_PREFIX}/dicts/{created['id']}", headers=_auth(token))
        assert deleted.status_code == 200
        assert _data(deleted)["deleted_item_count"] == 0

        # 逻辑删除后不可再读（`07 §3`）
        gone = await api.get(f"{ADMIN_PREFIX}/dicts/{created['id']}", headers=_auth(token))
        assert gone.status_code == 404
        assert gone.json()["code"] == 404001

    async def test_response_envelope_matches_spec(self, api: AsyncClient, db_session) -> None:
        """`08 §2`：成功响应 `{code: 0, message: "success", data: {...}}`。"""
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/dicts",
            json={"dict_code": "envelope_check", "dict_name": "信封"},
            headers=_auth(token),
        )
        body = response.json()
        assert response.status_code == 200
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 0
        assert body["message"] == "success"

    async def test_business_id_is_a_json_string(self, api: AsyncClient, db_session) -> None:
        """`07 §2` / `00 §6`：BIGINT 业务 ID 在 API JSON 中**必须是字符串**。

        前端 JS 的 Number 只有 53 位精度，Snowflake 是 64 位 ——
        下发数字会让 ID 在浏览器里被静默改写。
        """
        await _seed(db_session)
        token = await _login(api)
        created = await _create_type(api, token)

        assert isinstance(created["id"], str)
        assert created["id"].isdigit()
        assert isinstance(created["created_at"], str)

        item = await _create_item(api, token, created["id"])
        assert isinstance(item["id"], str)
        assert isinstance(item["dict_type_id"], str)

    async def test_list_uses_the_pagination_envelope(self, api: AsyncClient, db_session) -> None:
        """人类裁定的分页协议：请求 `pageNum`/`pageSize`，响应四个字段。"""
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token, dict_code="a_dict")
        await _create_type(api, token, dict_code="b_dict", dict_name="第二个")

        response = await api.get(
            f"{ADMIN_PREFIX}/dicts", params={"pageNum": 1, "pageSize": 10}, headers=_auth(token)
        )
        assert response.status_code == 200
        data = _data(response)
        assert set(data) == {"list", "total", "pageNum", "pageSize"}
        assert data["total"] == 2
        assert data["pageNum"] == 1
        assert data["pageSize"] == 10
        assert {row["dict_code"] for row in data["list"]} == {"a_dict", "b_dict"}

    async def test_keyword_and_status_filters_are_applied(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token, dict_code="keep_me", dict_name="保留")
        await _create_type(api, token, dict_code="drop_me", dict_name="丢掉", status="DISABLED")

        by_keyword = await api.get(
            f"{ADMIN_PREFIX}/dicts", params={"keyword": "保留"}, headers=_auth(token)
        )
        assert [row["dict_code"] for row in _data(by_keyword)["list"]] == ["keep_me"]

        by_status = await api.get(
            f"{ADMIN_PREFIX}/dicts", params={"status": "DISABLED"}, headers=_auth(token)
        )
        assert [row["dict_code"] for row in _data(by_status)["list"]] == ["drop_me"]

    async def test_duplicate_code_returns_409(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token)

        again = await api.post(
            f"{ADMIN_PREFIX}/dicts",
            json={"dict_code": "user_status", "dict_name": "重复"},
            headers=_auth(token),
        )
        assert again.status_code == 409
        assert again.json()["code"] == 409001

    async def test_dictionary_code_is_not_updatable(self, api: AsyncClient, db_session) -> None:
        """`dict_code` 是对外稳定标识，修改请求体里出现它应当被拒。

        `DictTypeUpdateRequest` 是 `extra="forbid"`，因此 422 ——
        比"静默忽略"好：静默忽略会让调用方以为改成功了。
        """
        await _seed(db_session)
        token = await _login(api)
        created = await _create_type(api, token)

        response = await api.put(
            f"{ADMIN_PREFIX}/dicts/{created['id']}",
            json={"dict_code": "changed"},
            headers=_auth(token),
        )
        assert response.status_code == 422
        assert response.json()["code"] == 422001

        unchanged = await api.get(f"{ADMIN_PREFIX}/dicts/{created['id']}", headers=_auth(token))
        assert _data(unchanged)["dict_code"] == "user_status"

    async def test_missing_type_returns_404(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.get(f"{ADMIN_PREFIX}/dicts/999999", headers=_auth(token))
        assert response.status_code == 404
        assert response.json()["code"] == 404001

    async def test_blank_code_returns_400(self, api: AsyncClient, db_session) -> None:
        """服务层的字段校验必须经由 HTTP 如实表达为 400。

        `" "` 能通过 DTO 的 `min_length=1`，因此这条请求会走到
        `DictService._assert_text_lengths` 才被拒 —— 这正是要覆盖的路径。
        （若把该检查删掉，空白编码会被写进库，公开查询则永远查不到它。）
        """
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/dicts",
            json={"dict_code": "   ", "dict_name": "空白编码"},
            headers=_auth(token),
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_page_size_beyond_the_dto_bound_is_rejected_at_the_edge(
        self, api: AsyncClient, db_session
    ) -> None:
        """分页上界有两道防线：DTO 的 `le=100`（边界）与服务层（业务约束）。

        HTTP 调用方先撞上 DTO，因此这里断言 **422** 而不是服务层的 400；
        服务层那条 400 由 `tests/test_dict_service.py` 覆盖
        （它保护的是不经 HTTP 的调用方，例如内部定时任务或运维脚本）。
        """
        await _seed(db_session)
        token = await _login(api)
        response = await api.get(
            f"{ADMIN_PREFIX}/dicts", params={"pageSize": 101}, headers=_auth(token)
        )
        assert response.status_code == 422
        assert response.json()["code"] == 422001


# ---------------------------------------------------------------------------
# 字典项（HTTP）
# ---------------------------------------------------------------------------
class TestDictItemHttp:
    async def test_item_crud_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)

        item = await _create_item(api, token, dict_type["id"], is_default=True)
        assert item["dict_type_id"] == dict_type["id"]
        assert item["is_default"] is True

        listed = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token)
        )
        assert listed.status_code == 200
        assert [row["id"] for row in _data(listed)["items"]] == [item["id"]]

        updated = await api.put(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items/{item['id']}",
            json={"item_label": "已启用", "sort_order": 3},
            headers=_auth(token),
        )
        assert updated.status_code == 200
        assert _data(updated)["item_label"] == "已启用"
        assert _data(updated)["sort_order"] == 3

        deleted = await api.delete(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items/{item['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 200
        # 逻辑删除：行仍在，但状态被置为 DISABLED 且不再是默认项
        assert _data(deleted)["status"] == "DISABLED"
        assert _data(deleted)["is_default"] is False

        after = await api.get(f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token))
        assert _data(after)["items"] == []

    async def test_item_list_is_not_paginated(self, api: AsyncClient, db_session) -> None:
        """`05 §4` 没给字典项分页参数，因此响应体**没有**分页字段。

        若复用了分页字段名，调用方会以为 `total` 只是"没返回"。
        """
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="A")

        response = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token)
        )
        data = _data(response)
        assert set(data) == {"items"}
        assert "total" not in data and "pageNum" not in data

    async def test_items_include_disabled_ones_by_default(
        self, api: AsyncClient, db_session
    ) -> None:
        """管理界面必须能看到被停用的项，否则"它为什么不见了"无法排查。"""
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="ON")
        await _create_item(
            api, token, dict_type["id"], item_value="OFF", status="DISABLED", item_label="停用"
        )

        all_items = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token)
        )
        assert {row["item_value"] for row in _data(all_items)["items"]} == {"ON", "OFF"}

        active_only = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items",
            params={"status": "ACTIVE"},
            headers=_auth(token),
        )
        assert {row["item_value"] for row in _data(active_only)["items"]} == {"ON"}

    async def test_items_are_ordered_by_sort_order_then_id(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        for label, value, order in (("丙", "C", 5), ("甲", "A", 1), ("乙", "B", 2)):
            await _create_item(
                api, token, dict_type["id"], item_value=value, item_label=label, sort_order=order
            )

        listed = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token)
        )
        assert [row["item_value"] for row in _data(listed)["items"]] == ["A", "B", "C"]

    async def test_duplicate_item_value_returns_409(self, api: AsyncClient, db_session) -> None:
        """`05 §3`：同字典内 `item_value` 唯一。"""
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="ACTIVE")

        response = await api.post(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items",
            json={"item_label": "重复", "item_value": "ACTIVE", "item_code": "dup"},
            headers=_auth(token),
        )
        assert response.status_code == 409
        assert response.json()["code"] == 409001

    async def test_item_from_another_dictionary_is_404(self, api: AsyncClient, db_session) -> None:
        """归属校验：用 A 字典的路径改 B 字典的项必须 404。

        否则审计里记的 `dict_type_id` 与实际被改对象不一致 —— 审计失真。
        """
        await _seed(db_session)
        token = await _login(api)
        left = await _create_type(api, token, dict_code="left_dict", dict_name="左")
        right = await _create_type(api, token, dict_code="right_dict", dict_name="右")
        item = await _create_item(api, token, left["id"], item_value="X")

        mismatched = await api.put(
            f"{ADMIN_PREFIX}/dicts/{right['id']}/items/{item['id']}",
            json={"item_label": "越界"},
            headers=_auth(token),
        )
        assert mismatched.status_code == 404
        assert mismatched.json()["code"] == 404001

        # 原对象完好
        listed = await api.get(f"{ADMIN_PREFIX}/dicts/{left['id']}/items", headers=_auth(token))
        assert _data(listed)["items"][0]["item_label"] == "启用"

    async def test_deleting_the_type_cascades_items_over_http(
        self, api: AsyncClient, db_session
    ) -> None:
        """删除类型时级联逻辑删除项，且数量如实出现在响应里。"""
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="A")
        await _create_item(api, token, dict_type["id"], item_value="B")

        deleted = await api.delete(f"{ADMIN_PREFIX}/dicts/{dict_type['id']}", headers=_auth(token))
        assert deleted.status_code == 200
        assert _data(deleted)["deleted_item_count"] == 2

        # 同一编码可以重建，且**不会**长出旧项（`07 §3`）
        rebuilt = await _create_type(api, token)
        assert rebuilt["id"] != dict_type["id"]
        items = await api.get(f"{ADMIN_PREFIX}/dicts/{rebuilt['id']}/items", headers=_auth(token))
        assert _data(items)["items"] == []

    async def test_only_one_default_item_survives(self, api: AsyncClient, db_session) -> None:
        """至多一个默认项（INTERIM-7-03）：后者胜，且服务端计算结果。

        这里刻意**不**断言 409 —— Spec 未规定"第二个默认项"该报错还是该顶替，
        实现取"顶替"（改动面最小、不会让管理员卡在中间状态）。
        """
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="A", is_default=True)
        await _create_item(api, token, dict_type["id"], item_value="B", is_default=True)

        listed = await api.get(
            f"{ADMIN_PREFIX}/dicts/{dict_type['id']}/items", headers=_auth(token)
        )
        defaults = [row["item_value"] for row in _data(listed)["items"] if row["is_default"]]
        assert defaults == ["B"]


# ---------------------------------------------------------------------------
# 公开查询（`05 §4`）
# ---------------------------------------------------------------------------
class TestPublicQueryHttp:
    async def test_returns_only_active_items(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        await _create_item(api, token, dict_type["id"], item_value="ON", item_label="启用")
        await _create_item(
            api, token, dict_type["id"], item_value="OFF", item_label="停用", status="DISABLED"
        )

        response = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status", headers=_auth(token))
        assert response.status_code == 200
        data = _data(response)
        assert data["dict_code"] == "user_status"
        assert [item["item_value"] for item in data["items"]] == ["ON"]

    async def test_response_omits_internal_ids(self, api: AsyncClient, db_session) -> None:
        """公开响应不下发内部主键 —— 少一条"把主键当业务键用"的误用路径。"""
        await _seed(db_session)
        token = await _login(api)
        dict_type = await _create_type(api, token)
        item = await _create_item(api, token, dict_type["id"], item_value="ON")

        response = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status", headers=_auth(token))
        data = _data(response)
        assert set(data) == {"dict_code", "dict_name", "description", "items"}
        assert set(data["items"][0]) == {
            "item_label",
            "item_value",
            "item_code",
            "sort_order",
            "is_default",
            "description",
        }
        # 逐字节扫描响应原文：内部 ID 不得以字符串形式泄漏
        # （只查字段名会漏掉"塞进 description 里"这类写法）。
        text = response.text
        assert dict_type["id"] not in text
        assert item["id"] not in text

    async def test_disabled_dictionary_is_indistinguishable_from_missing(
        self, api: AsyncClient, db_session
    ) -> None:
        """停用与不存在都返回同一个 404（不暴露"它存在但被停用"）。"""
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token, status="DISABLED")

        disabled = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status", headers=_auth(token))
        missing = await api.get(f"{PUBLIC_PREFIX}/dicts/no_such_code", headers=_auth(token))
        assert disabled.status_code == missing.status_code == 404
        assert disabled.json() == missing.json()

    async def test_deleted_dictionary_returns_404(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        created = await _create_type(api, token)
        await api.delete(f"{ADMIN_PREFIX}/dicts/{created['id']}", headers=_auth(token))

        response = await api.get(f"{PUBLIC_PREFIX}/dicts/user_status", headers=_auth(token))
        assert response.status_code == 404
        assert response.json()["code"] == 404001

    async def test_public_query_does_not_leak_the_dictionary_list(
        self, api: AsyncClient, db_session
    ) -> None:
        """公开端点必须给出具体编码，无法用来枚举系统里有哪些字典。"""
        await _seed(db_session)
        token = await _login(api)
        await _create_type(api, token)

        # `/api/v1/dicts` 本身不是一个端点（那只在 admin 域下存在）
        response = await api.get(f"{PUBLIC_PREFIX}/dicts", headers=_auth(token))
        assert response.status_code in {404, 405}


__all__ = [
    "TestAccessControl",
    "TestDictItemHttp",
    "TestDictTypeHttp",
    "TestPublicQueryHttp",
    "TestRouteSurface",
]
