"""会话管理端点测试（HTTP 层 / `08 §4`、`08 §5`、`10 §7`）。

覆盖点
-----
- 认证与授权：无令牌 401、无 API 权限 403、越范围 403、强制改密期 403；
- 响应契约：`{code, message, data}` 信封、BIGINT ID 序列化为字符串、
  分页字段 `pageNum` / `pageSize`、参数越界 422；
- 端到端安全性质：**踢下线后令牌立即不可用**（`10 §7`）——
  这是本阶段必须在真实 HTTP 请求 + 真实令牌上验的性质，
  服务层用例无法替代（服务层直接调用 `authenticate`，绕过了依赖装配）。

事务与依赖覆盖
------------
`app.dependency_overrides[get_db]` 指向测试会话（`db_session` 夹具的外层事务），
因此端点里的 `commit()` 不会逃出用例边界 —— 用例结束后统一回滚。
审计在 HTTP 路径上默认走 `NullAuditRecorder`（落库属 Phase 6），
因此本文件**不断言审计事件**，审计断言在服务层用例中完成。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.db.session import get_db
from app.models.user import AdminUser
from tests.test_session_management import (
    S_DISABLED,
    S_EXPIRED,
    S_IN_CHILD,
    S_OUT,
    S_REVOKED,
    S_SUPER,
    S_VALID,
    U_DEPT,
    U_IN_PARENT,
    U_OUT,
    U_SUPER,
    _seed,
)

pytestmark = pytest.mark.integration

PREFIX = "/api/v1/admin"


@pytest.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """把端点的 `get_db` 指向测试会话。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(response: Response) -> dict:
    return response.json()["data"]


# ---------------------------------------------------------------------------
# 认证与授权
# ---------------------------------------------------------------------------
class TestAccessControl:
    async def test_requires_authentication(self, api: AsyncClient) -> None:
        """四条端点都必须拒绝未认证请求（`08 §10`：不得只靠前端隐藏）。"""
        for method, path in (
            ("get", f"{PREFIX}/sessions"),
            ("post", f"{PREFIX}/sessions/1/revoke"),
            ("get", f"{PREFIX}/users/1/sessions"),
            ("post", f"{PREFIX}/users/1/sessions/revoke-all"),
        ):
            response = await getattr(api, method)(path)
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001
            assert response.headers["WWW-Authenticate"] == "Bearer"

    async def test_without_api_permission_is_forbidden(self, api: AsyncClient, db_session) -> None:
        """非超管必须在有效权限集合中持有 `SESSION_MANAGE`（`08 §10`）。"""
        fixture = await _seed(db_session)
        response = await api.get(
            f"{PREFIX}/sessions",
            headers=_auth(fixture.sessions["no_perm_own"].access_token),
        )
        assert response.status_code == 403
        assert response.json()["code"] == 403001

    async def test_forced_password_change_blocks_session_endpoints(
        self, api: AsyncClient, db_session
    ) -> None:
        """强制改密期必须被 `get_current_actor` 拦在 403（**不是** 401）。"""
        fixture = await _seed(db_session)
        user = await db_session.get(AdminUser, U_DEPT)
        assert user is not None
        user.must_change_password = True
        await db_session.flush()

        response = await api.get(
            f"{PREFIX}/sessions", headers=_auth(fixture.sessions["dept_own"].access_token)
        )
        assert response.status_code == 403

    async def test_out_of_scope_user_is_forbidden(self, api: AsyncClient, db_session) -> None:
        """越范围必须是 403（而不是空列表），否则无法区分"越权"与"确实没有"。"""
        fixture = await _seed(db_session)
        headers = _auth(fixture.sessions["dept_own"].access_token)

        denied = await api.get(f"{PREFIX}/users/{U_OUT}/sessions", headers=headers)
        assert denied.status_code == 403

        missing = await api.get(f"{PREFIX}/users/599999/sessions", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["data"] is None

    async def test_super_admin_cannot_be_kicked(self, api: AsyncClient, db_session) -> None:
        """裁判 §13/§14：全范围管理员也踢不动 SUPER_ADMIN，其会话必须毫发无伤。"""
        fixture = await _seed(db_session)
        response = await api.post(
            f"{PREFIX}/sessions/{S_SUPER}/revoke",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert response.status_code == 403

        # 超管自己的会话仍可用（拒绝必须是"什么都没做"）
        alive = await api.get(
            "/api/v1/auth/me", headers=_auth(fixture.sessions["super"].access_token)
        )
        assert alive.status_code == 200
        assert alive.json()["data"]["id"] == str(U_SUPER)

        revoke_all = await api.post(
            f"{PREFIX}/users/{U_SUPER}/sessions/revoke-all",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert revoke_all.status_code == 403


# ---------------------------------------------------------------------------
# 响应契约
# ---------------------------------------------------------------------------
class TestResponseContract:
    async def test_envelope_and_string_ids(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        response = await api.get(
            f"{PREFIX}/sessions",
            headers=_auth(fixture.sessions["global_own"].access_token),
            params={"pageNum": 1, "pageSize": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"

        data = body["data"]
        assert data["pageNum"] == 1
        assert data["pageSize"] == 2
        assert len(data["list"]) == 2
        assert data["total"] >= 2

        row = data["list"][0]
        # `07 §2`：BIGINT 业务 ID 一律为字符串
        assert isinstance(row["id"], str)
        assert isinstance(row["user_id"], str)
        # 响应里不得出现任何令牌字段（`10 §4`）
        assert not any("token" in key for key in row)

        for field in (
            "login_at",
            "last_active_at",
            "ip",
            "user_agent",
            "device",
            "access_expires_at",
            "refresh_expires_at",
            "revoked_at",
            "revoke_reason",
            "online",
            "username",
            "display_name",
        ):
            assert field in row, field

    async def test_online_filter(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        headers = _auth(fixture.sessions["global_own"].access_token)

        online = await api.get(
            f"{PREFIX}/sessions", headers=headers, params={"online": "true", "pageSize": 100}
        )
        all_rows = await api.get(f"{PREFIX}/sessions", headers=headers, params={"pageSize": 100})

        online_ids = {row["id"] for row in _data(online)["list"]}
        all_ids = {row["id"] for row in _data(all_rows)["list"]}

        assert str(S_VALID) in online_ids
        assert str(S_REVOKED) not in online_ids
        assert str(S_EXPIRED) not in online_ids
        assert str(S_DISABLED) not in online_ids  # 用户被禁用 → 会话不可用 → 不在线
        assert online_ids < all_ids
        assert all(row["online"] is True for row in _data(online)["list"])

    async def test_user_sessions_endpoint(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        response = await api.get(
            f"{PREFIX}/users/{U_IN_PARENT}/sessions",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert response.status_code == 200
        rows = _data(response)["list"]
        assert {row["id"] for row in rows} == {str(S_VALID), str(S_REVOKED), str(S_EXPIRED)}
        assert all(row["user_id"] == str(U_IN_PARENT) for row in rows)

    async def test_invalid_paging_is_rejected(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        headers = _auth(fixture.sessions["global_own"].access_token)
        for params in ({"pageSize": 1000}, {"pageNum": 0}, {"pageNum": "abc"}):
            response = await api.get(f"{PREFIX}/sessions", headers=headers, params=params)
            assert response.status_code == 422, params

    async def test_unknown_session_is_not_found(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        response = await api.post(
            f"{PREFIX}/sessions/599999/revoke",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert response.status_code == 404
        assert response.json()["data"] is None


# ---------------------------------------------------------------------------
# 踢下线（端到端）
# ---------------------------------------------------------------------------
class TestRevokeOverHttp:
    async def test_revoke_invalidates_token_immediately(self, api: AsyncClient, db_session) -> None:
        """`10 §7` 的端到端验证：踢下线后令牌**立即**不可用。"""
        fixture = await _seed(db_session)
        victim = fixture.sessions["valid"].access_token

        before = await api.get("/api/v1/auth/me", headers=_auth(victim))
        assert before.status_code == 200

        revoked = await api.post(
            f"{PREFIX}/sessions/{S_VALID}/revoke",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert revoked.status_code == 200
        assert _data(revoked)["revoked"] is True
        assert _data(revoked)["already_revoked"] is False

        after = await api.get("/api/v1/auth/me", headers=_auth(victim))
        assert after.status_code == 401
        assert after.json()["code"] == 401001

    async def test_revoke_is_idempotent(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        headers = _auth(fixture.sessions["global_own"].access_token)

        first = await api.post(f"{PREFIX}/sessions/{S_VALID}/revoke", headers=headers)
        second = await api.post(f"{PREFIX}/sessions/{S_VALID}/revoke", headers=headers)
        assert _data(first)["revoked"] is True
        assert _data(second)["revoked"] is False
        assert _data(second)["already_revoked"] is True
        assert _data(second)["id"] == str(S_VALID)

    async def test_revoke_all_endpoint(self, api: AsyncClient, db_session) -> None:
        fixture = await _seed(db_session)
        response = await api.post(
            f"{PREFIX}/users/{U_IN_PARENT}/sessions/revoke-all",
            headers=_auth(fixture.sessions["global_own"].access_token),
        )
        assert response.status_code == 200
        data = _data(response)
        assert data["user_id"] == str(U_IN_PARENT)
        assert data["revoked_count"] == 1

        after = await api.get(
            "/api/v1/auth/me", headers=_auth(fixture.sessions["valid"].access_token)
        )
        assert after.status_code == 401

    async def test_department_admin_kicks_only_in_scope(self, api: AsyncClient, db_session) -> None:
        """裁判 §12：Department Admin 只能踢管理范围内用户。"""
        fixture = await _seed(db_session)
        headers = _auth(fixture.sessions["dept_own"].access_token)

        ok = await api.post(f"{PREFIX}/sessions/{S_IN_CHILD}/revoke", headers=headers)
        assert ok.status_code == 200

        denied = await api.post(f"{PREFIX}/sessions/{S_OUT}/revoke", headers=headers)
        assert denied.status_code == 403


# ---------------------------------------------------------------------------
# 路由面（反向钉住"不预实现后续 Phase"）
# ---------------------------------------------------------------------------
class TestRouteSurface:
    """本阶段只允许 `08 §4` / `08 §5` 列出的四条会话端点。

    反向断言的意义：若后续有人在**本阶段范围之外**顺手加了
    `GET /sessions/{id}`（详情）或 `GET /sessions/online`（在线用户专用端点），
    或把用户 CRUD 提前挂上，这些断言会立刻失败 ——
    比人工 review 更可靠地防止预实现与接口面漂移。
    """

    async def test_session_paths_exist_exactly_as_specified(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        assert {
            f"{PREFIX}/sessions",
            f"{PREFIX}/sessions/{{session_id}}/revoke",
            f"{PREFIX}/users/{{user_id}}/sessions",
            f"{PREFIX}/users/{{user_id}}/sessions/revoke-all",
        } <= paths

        # 不得存在未在 `08 §5` 列出的会话端点（在线用户查询用查询参数实现）
        extra_session_paths = {
            path
            for path in paths
            if path.startswith(f"{PREFIX}/sessions/") and not path.endswith("/revoke")
        }
        assert extra_session_paths == set()

        # 用户 CRUD 已由 FINDING-8-01 的补救交付补齐（`08 §4`）。
        # 断言从"不得存在"改为"必须恰为冻结清单" ——
        # 这不是放宽：清单仍然逐条固定，多一条少一条都会失败。
        user_crud_paths = {
            path for path in paths if path.startswith(f"{PREFIX}/users") and "sessions" not in path
        }
        assert user_crud_paths == {
            f"{PREFIX}/users",
            f"{PREFIX}/users/{{user_id}}",
            f"{PREFIX}/users/{{user_id}}/disable",
            f"{PREFIX}/users/{{user_id}}/enable",
            f"{PREFIX}/users/{{user_id}}/reset-password",
        }, user_crud_paths

    async def test_mfa_endpoints_are_confined_to_auth_domain(self, app: FastAPI) -> None:
        """MFA 端点不得混入 admin 资源域。

        ⚠️ 本测试的前身是一条**反向钉住**（断言"不存在任何 mfa 端点"），
        服务于当时的目标：Session 阶段不得预实现 MFA。
        现在 `PHASES.md` Phase 5（MFA）已进入实现，该断言已失效。

        但"MFA 属于认证域、不属于 `/api/v1/admin` 资源域"这条边界**仍然成立**，
        所以此处换成正向断言：MFA 只能出现在 `/api/v1/auth` 之下。
        若将来有人把 MFA 挂到 `/admin`，会立刻失败。
        """
        paths = set(app.openapi()["paths"])
        assert not any(path.startswith("/api/v1/admin") and "mfa" in path for path in paths)
        # 且认证域下确实已经有 MFA（防止"本应实现却没有实现"）。
        assert any("mfa" in path for path in paths if "/auth/" in path)
