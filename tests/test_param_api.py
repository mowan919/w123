"""系统参数 HTTP 端点测试（Phase 7）。

与 `tests/test_system_param.py` 的分工：本文件验证**接线**
（状态码 / 信封 / ID 序列化 / `effective_value` 的计算字段 /
访问控制），服务层语义（回退、DISABLED、类型不符、审计）归该文件。

路由面（`INTERIM-7-04`）在 `tests/test_dict_api.py::TestRouteSurface` 中
与字典端点一起被正向钉住 —— 那是一次 `include_router` 的产物，
分开钉会让"挂错了前缀"这类错误有两处可以各自通过。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import PermissionResourceType, PermissionStatus
from app.services.system_param import MFA_REQUIRED_DEFAULT_KEY
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

DEPT_ID = 58001
ROLE_PARAM_ADMIN = 58011
ROLE_NO_PERM = 58012
RES_API_PARAM_MANAGE = 58021
#: 迁移 Seed 写入的 `mfa.required_default` 行主键（`05 §5` 的落地内容）。
SEEDED_MFA_PARAM_ID = 700001

USER_ID = 58101
NO_PERM_USER_ID = 58102
USERNAME = "param-api-admin"
NO_PERM_USERNAME = "param-api-noperm"
PASSWORD = "Param-API-Passw0rd!07"


@pytest.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
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
    return response.json()["data"]


async def _seed(session) -> None:
    await make_department(session, department_id=DEPT_ID, department_code="PARAM-API-DEPT")
    await make_role(session, role_id=ROLE_PARAM_ADMIN, role_code="PARAM_API_ADMIN")
    await make_role(session, role_id=ROLE_NO_PERM, role_code="PARAM_API_NONE")
    await make_permission_resource(
        session,
        resource_id=RES_API_PARAM_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="PARAM_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/params",
        status=PermissionStatus.ACTIVE,
    )
    await link_role_permission(session, role_id=ROLE_PARAM_ADMIN, resource_id=RES_API_PARAM_MANAGE)

    for user_id, username, role_id in (
        (USER_ID, USERNAME, ROLE_PARAM_ADMIN),
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
    response = await api.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return _data(response)["access_token"]


async def _create_param(
    api: AsyncClient, token: str, *, param_key: str = "session.idle_timeout", **overrides
) -> dict:
    payload = {
        "param_key": param_key,
        "param_name": "会话空闲超时",
        "param_type": "INT",
        "default_value": "1800",
        "description": "单位：秒",
        **overrides,
    }
    response = await api.post(f"{ADMIN_PREFIX}/params", json=payload, headers=_auth(token))
    assert response.status_code == 200, response.text
    return _data(response)


# ---------------------------------------------------------------------------
# 访问控制
# ---------------------------------------------------------------------------
class TestAccessControl:
    async def test_endpoints_require_authentication(self, api: AsyncClient) -> None:
        """合法请求体 + 无令牌 → 401（而不是 422 之类的副作用）。"""
        calls = (
            ("get", f"{ADMIN_PREFIX}/params", None),
            (
                "post",
                f"{ADMIN_PREFIX}/params",
                {
                    "param_key": "k",
                    "param_name": "K",
                    "param_type": "STRING",
                    "default_value": "v",
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

    async def test_endpoints_reject_users_without_param_manage(
        self, api: AsyncClient, db_session
    ) -> None:
        """已认证但无 `PARAM_MANAGE` → 403，且写操作不得产生任何行。"""
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)

        calls = (
            ("get", f"{ADMIN_PREFIX}/params", None),
            (
                "post",
                f"{ADMIN_PREFIX}/params",
                {
                    "param_key": "k",
                    "param_name": "K",
                    "param_type": "STRING",
                    "default_value": "v",
                },
            ),
            ("get", f"{ADMIN_PREFIX}/params/1", None),
            ("put", f"{ADMIN_PREFIX}/params/1", {"param_name": "K"}),
            ("delete", f"{ADMIN_PREFIX}/params/1", None),
        )
        for method, path, body in calls:
            response = await getattr(api, method)(
                path, headers=_auth(token), **({"json": body} if body else {})
            )
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

        from sqlalchemy import text

        count = (
            await db_session.execute(text("select count(*) from sys_params where param_key = 'k'"))
        ).scalar_one()
        assert count == 0, "被拒绝的写操作不得落库"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class TestParamHttp:
    async def test_crud_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)

        created = await _create_param(api, token)
        assert created["param_key"] == "session.idle_timeout"
        assert created["param_type"] == "INT"
        assert created["default_value"] == "1800"
        assert created["status"] == "ACTIVE"
        # 未显式设置当前值 → 生效值就是默认值
        assert created["param_value"] is None
        assert created["effective_value"] == "1800"

        fetched = await api.get(f"{ADMIN_PREFIX}/params/{created['id']}", headers=_auth(token))
        assert fetched.status_code == 200
        assert _data(fetched)["id"] == created["id"]

        updated = await api.put(
            f"{ADMIN_PREFIX}/params/{created['id']}",
            json={"param_name": "会话空闲超时（改）", "default_value": "900"},
            headers=_auth(token),
        )
        assert updated.status_code == 200
        assert _data(updated)["param_name"] == "会话空闲超时（改）"
        assert _data(updated)["effective_value"] == "900"

        deleted = await api.delete(f"{ADMIN_PREFIX}/params/{created['id']}", headers=_auth(token))
        assert deleted.status_code == 200
        assert _data(deleted)["status"] == "DISABLED"

        gone = await api.get(f"{ADMIN_PREFIX}/params/{created['id']}", headers=_auth(token))
        assert gone.status_code == 404
        assert gone.json()["code"] == 404001

    async def test_response_envelope_matches_spec(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/params",
            json={
                "param_key": "envelope.check",
                "param_name": "信封",
                "param_type": "STRING",
                "default_value": "v",
            },
            headers=_auth(token),
        )
        body = response.json()
        assert response.status_code == 200
        assert set(body) == {"code", "message", "data"}
        assert body["code"] == 0
        assert body["message"] == "success"

    async def test_business_id_is_a_json_string(self, api: AsyncClient, db_session) -> None:
        """`07 §2` / `00 §6`：BIGINT 业务 ID 在 JSON 中必须是字符串。"""
        await _seed(db_session)
        token = await _login(api)
        created = await _create_param(api, token)
        assert isinstance(created["id"], str)
        assert created["id"].isdigit()
        assert isinstance(created["created_at"], str)

        listed = await api.get(f"{ADMIN_PREFIX}/params", headers=_auth(token))
        for row in _data(listed)["list"]:
            assert isinstance(row["id"], str)

    async def test_list_uses_the_pagination_envelope(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        await _create_param(api, token, param_key="a.key", param_type="STRING", default_value="1")
        await _create_param(api, token, param_key="b.key", param_type="STRING", default_value="2")

        response = await api.get(
            f"{ADMIN_PREFIX}/params",
            params={"pageNum": 1, "pageSize": 1, "keyword": ".key"},
            headers=_auth(token),
        )
        assert response.status_code == 200
        data = _data(response)
        assert set(data) == {"list", "total", "pageNum", "pageSize"}
        assert data["total"] == 2
        assert data["pageSize"] == 1
        assert len(data["list"]) == 1

    async def test_seeded_mfa_default_param_is_readable(self, api: AsyncClient, db_session) -> None:
        """迁移 Seed 的参数行必须**通过 API 可读且形状正确**。

        这是"Phase 7 把 MFA system 级默认值迁入参数表"
        （`docs/DESIGN-DECISIONS.md` §12.1）在 HTTP 层的落地证据：
        行存在、类型是 BOOL、当前值未设置、生效值是 `false`。
        """
        await _seed(db_session)
        token = await _login(api)

        response = await api.get(
            f"{ADMIN_PREFIX}/params/{SEEDED_MFA_PARAM_ID}", headers=_auth(token)
        )
        assert response.status_code == 200, response.text
        data = _data(response)
        assert data["param_key"] == MFA_REQUIRED_DEFAULT_KEY
        assert data["param_type"] == "BOOL"
        assert data["param_value"] is None
        assert data["default_value"] == "false"
        assert data["effective_value"] == "false"
        assert data["status"] == "ACTIVE"

    async def test_effective_value_follows_the_current_value(
        self, api: AsyncClient, db_session
    ) -> None:
        """`effective_value = param_value ?? default_value` 由**服务端**计算。"""
        await _seed(db_session)
        token = await _login(api)
        created = await _create_param(api, token, param_type="BOOL", default_value="false")

        set_value = await api.put(
            f"{ADMIN_PREFIX}/params/{created['id']}",
            json={"param_value": "true"},
            headers=_auth(token),
        )
        assert _data(set_value)["param_value"] == "true"
        assert _data(set_value)["effective_value"] == "true"

    async def test_clear_value_resets_to_the_default(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        created = await _create_param(api, token, param_type="BOOL", default_value="false")
        await api.put(
            f"{ADMIN_PREFIX}/params/{created['id']}",
            json={"param_value": "true"},
            headers=_auth(token),
        )

        cleared = await api.put(
            f"{ADMIN_PREFIX}/params/{created['id']}",
            json={"clear_value": True},
            headers=_auth(token),
        )
        assert cleared.status_code == 200
        assert _data(cleared)["param_value"] is None
        assert _data(cleared)["effective_value"] == "false"

    async def test_clear_value_with_param_value_is_a_400(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api)
        created = await _create_param(api, token, param_type="BOOL", default_value="false")

        response = await api.put(
            f"{ADMIN_PREFIX}/params/{created['id']}",
            json={"clear_value": True, "param_value": "true"},
            headers=_auth(token),
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_duplicate_key_returns_409(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        await _create_param(api, token)

        again = await api.post(
            f"{ADMIN_PREFIX}/params",
            json={
                "param_key": "session.idle_timeout",
                "param_name": "重复",
                "param_type": "INT",
                "default_value": "60",
            },
            headers=_auth(token),
        )
        assert again.status_code == 409
        assert again.json()["code"] == 409001

    async def test_invalid_literal_returns_400(self, api: AsyncClient, db_session) -> None:
        """写入侧校验：与声明类型不符的默认值必须被挡在库外。"""
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/params",
            json={
                "param_key": "bad.bool",
                "param_name": "坏的布尔",
                "param_type": "BOOL",
                "default_value": "yes",
            },
            headers=_auth(token),
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_key_with_whitespace_returns_400(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.post(
            f"{ADMIN_PREFIX}/params",
            json={
                "param_key": "bad key",
                "param_name": "带空格的键",
                "param_type": "STRING",
                "default_value": "v",
            },
            headers=_auth(token),
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_missing_param_returns_404(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api)
        response = await api.get(f"{ADMIN_PREFIX}/params/999999", headers=_auth(token))
        assert response.status_code == 404
        assert response.json()["code"] == 404001

    async def test_key_and_type_are_rejected_in_the_update_body(
        self, api: AsyncClient, db_session
    ) -> None:
        """`param_key` / `param_type` 改不了 —— DTO 是 `extra="forbid"`。

        静默忽略会更糟：调用方会以为改成功了，而运行时仍在用旧的键 / 类型。
        """
        await _seed(db_session)
        token = await _login(api)
        created = await _create_param(api, token)

        for body in ({"param_key": "other.key"}, {"param_type": "BOOL"}):
            response = await api.put(
                f"{ADMIN_PREFIX}/params/{created['id']}", json=body, headers=_auth(token)
            )
            assert response.status_code == 422, body
            assert response.json()["code"] == 422001

        unchanged = await api.get(f"{ADMIN_PREFIX}/params/{created['id']}", headers=_auth(token))
        assert _data(unchanged)["param_key"] == "session.idle_timeout"
        assert _data(unchanged)["param_type"] == "INT"


# ---------------------------------------------------------------------------
# 公开面
# ---------------------------------------------------------------------------
class TestPublicSurface:
    """系统参数**没有**公开查询端点：参数清单本身暴露系统有哪些可调开关。"""

    def test_no_param_path_outside_the_admin_namespace(self, app: FastAPI) -> None:
        outside = {
            path for path in app.openapi()["paths"] if "/admin/" not in path and "param" in path
        }
        assert outside == set()

    async def test_public_param_path_does_not_exist(self, api: AsyncClient) -> None:
        response = await api.get(f"{PUBLIC_PREFIX}/params")
        assert response.status_code in {404, 405}


__all__ = ["TestAccessControl", "TestParamHttp", "TestPublicSurface"]
