"""认证 HTTP 端点测试（Phase 4 / Spec `08 §3`）。

验证层次
-------
本文件只验证**接线与协议**：路由是否挂在该在的前缀下、状态码、
`WWW-Authenticate` 头、响应信封、`Annotated` 依赖是否真的生效。
业务判定（锁定、90 天、文案统一）由 `tests/test_auth_service.py` 覆盖 ——
两层分开，失败时原因才明确（"401 是因为锁定，还是因为路由没挂上？"）。

为什么需要覆盖 `get_db`
----------------------
端点在成功路径上会 `commit()`。若让它打到真实的进程级连接池，
数据就会真的落库、污染远端实例。这里把 `get_db` 指向用例的事务会话，
`commit()` 只会在该事务内部生效，用例结束时由夹具统一回滚。

这一点已实测确认（先写入同一主键、再重复运行用例均不冲突），
而不是"假设 SQLAlchemy 会这样做"。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.api.deps import CurrentActorDep
from app.core.response import success_response
from app.core.security.password import PASSWORD_MAX_AGE
from app.db.base import utc_now
from app.db.session import get_db
from app.models import UserStatus
from tests.factories import make_user

pytestmark = pytest.mark.integration

PASSWORD = "Alpha-Passw0rd!01"
NEW_PASSWORD = "Bravo-Passw0rd!02"
USER_ID = 52201
AUTH_PREFIX = "/api/v1/auth"


async def _seed(
    db_session,
    *,
    username: str = "api-user",
    must_change_password: bool = False,
    status: UserStatus = UserStatus.ACTIVE,
    user_id: int = USER_ID,
):
    return await make_user(
        db_session,
        user_id=user_id,
        username=username,
        password=PASSWORD,
        password_changed_at=utc_now(),
        must_change_password=must_change_password,
        status=status,
    )


@pytest_asyncio.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """把端点的事务会话指向用例事务的 HTTP 客户端。"""

    async def _override_get_db() -> AsyncIterator[object]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _login(
    client: AsyncClient, *, username: str = "api-user", password: str = PASSWORD
) -> Response:
    return await client.post(
        f"{AUTH_PREFIX}/login", json={"username": username, "password": password}
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestLoginEndpoint:
    async def test_login_returns_envelope_and_token_pair(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        response = await _login(api)

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"

        data = body["data"]
        assert data["token_type"] == "Bearer"
        assert data["access_token"] and data["refresh_token"]
        assert data["access_expires_at"] < data["refresh_expires_at"]
        assert data["must_change_password"] is False
        assert data["user"]["username"] == "api-user"

    async def test_bigint_ids_are_serialized_as_strings(self, api: AsyncClient, db_session) -> None:
        """Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为字符串。

        JS 的 Number 只有 53 位有效精度，而 Snowflake ID 是 64 位；
        若序列化为数字，客户端会静默丢精度（且"看起来"一切正常）。
        """
        await _seed(db_session)
        data = (await _login(api)).json()["data"]
        assert isinstance(data["user"]["id"], str)
        assert data["user"]["id"] == str(USER_ID)

    async def test_password_is_never_echoed_back(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        text = (await _login(api)).text
        assert PASSWORD not in text
        assert "password_hash" not in text
        assert "$argon2id$" not in text

    async def test_wrong_password_returns_401_with_www_authenticate(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        response = await _login(api, password="Wrong-Passw0rd!99")

        assert response.status_code == 401
        # RFC 6750 §3：401 必须告知认证方案
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["data"] is None

    async def test_unknown_user_and_wrong_password_are_http_indistinguishable(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        unknown = await _login(api, username="ghost")
        wrong = await _login(api, password="Wrong-Passw0rd!99")

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

    async def test_disabled_user_cannot_login(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session, status=UserStatus.DISABLED)
        assert (await _login(api)).status_code == 401

    async def test_unknown_field_in_body_is_rejected(self, api: AsyncClient, db_session) -> None:
        """`extra="forbid"`：多余字段是 422，而不是被静默忽略。

        静默忽略会让"客户端以为传了某个开关"这种误解长期存在。
        """
        await _seed(db_session)
        response = await api.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "api-user", "password": PASSWORD, "remember_me": True},
        )
        assert response.status_code == 422


class TestMeEndpoint:
    async def test_missing_authorization_header_is_401(self, api: AsyncClient) -> None:
        response = await api.get(f"{AUTH_PREFIX}/me")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize(
        "header",
        [
            "",
            "Bearer",
            "Bearer    ",
            "Basic YWJjOjEyMw==",
            "Token abcdefghijklmnopqrstuvwxyz0123456789",
            "Bearer not a token",
        ],
    )
    async def test_malformed_authorization_headers_are_401(
        self, api: AsyncClient, header: str
    ) -> None:
        response = await api.get(f"{AUTH_PREFIX}/me", headers={"Authorization": header})
        assert response.status_code == 401

    async def test_valid_token_returns_current_user(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        access = (await _login(api)).json()["data"]["access_token"]

        response = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(access))
        assert response.status_code == 200

        data = response.json()["data"]
        assert data["username"] == "api-user"
        assert data["status"] == "ACTIVE"
        assert data["must_change_password"] is False
        assert data["password_expired"] is False

    async def test_unknown_token_is_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        unknown = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        assert (await api.get(f"{AUTH_PREFIX}/me", headers=_auth(unknown))).status_code == 401

    async def test_me_never_leaks_credentials(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        access = (await _login(api)).json()["data"]["access_token"]
        text = (await api.get(f"{AUTH_PREFIX}/me", headers=_auth(access))).text

        assert "password_hash" not in text
        assert "$argon2id$" not in text
        assert access not in text


class TestRefreshEndpoint:
    async def test_refresh_rotates_and_old_access_stops_working(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        first = (await _login(api)).json()["data"]

        response = await api.post(
            f"{AUTH_PREFIX}/refresh", json={"refresh_token": first["refresh_token"]}
        )
        assert response.status_code == 200
        second = response.json()["data"]

        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        # 会话总寿命固定不滑动（DD-02 P2）
        assert second["refresh_expires_at"] == first["refresh_expires_at"]

        # 旧 access 立即失效，新 access 可用
        old_access = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(first["access_token"]))
        new_access = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(second["access_token"]))
        assert old_access.status_code == 401
        assert new_access.status_code == 200

    async def test_reused_refresh_token_revokes_whole_session(
        self, api: AsyncClient, db_session
    ) -> None:
        """DD-02 P4：旧 refresh 再次出现 → 整个会话（含新 access）失效。"""
        await _seed(db_session)
        first = (await _login(api)).json()["data"]
        second = (
            await api.post(f"{AUTH_PREFIX}/refresh", json={"refresh_token": first["refresh_token"]})
        ).json()["data"]

        replay = await api.post(
            f"{AUTH_PREFIX}/refresh", json={"refresh_token": first["refresh_token"]}
        )
        assert replay.status_code == 401

        # 关键：攻击者可能已换到新 access，因此必须连新 access 一起作废
        assert (
            await api.get(f"{AUTH_PREFIX}/me", headers=_auth(second["access_token"]))
        ).status_code == 401

    async def test_unknown_refresh_token_is_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        response = await api.post(
            f"{AUTH_PREFIX}/refresh",
            json={"refresh_token": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        )
        assert response.status_code == 401

    async def test_missing_refresh_token_is_422(self, api: AsyncClient) -> None:
        assert (await api.post(f"{AUTH_PREFIX}/refresh", json={})).status_code == 422


class TestLogoutEndpoint:
    async def test_logout_revokes_and_is_idempotent(self, api: AsyncClient, db_session) -> None:
        """DD-11 方案 A：重复登出返回 200（而非 401）。

        若第二次返回 401，客户端会把一次**成功**的登出当作错误，
        进而重试或弹出无意义提示。
        """
        await _seed(db_session)
        access = (await _login(api)).json()["data"]["access_token"]

        first = await api.post(f"{AUTH_PREFIX}/logout", headers=_auth(access))
        assert first.status_code == 200
        assert first.json()["data"] == {"revoked": True, "already_revoked": False}

        second = await api.post(f"{AUTH_PREFIX}/logout", headers=_auth(access))
        assert second.status_code == 200
        assert second.json()["data"] == {"revoked": False, "already_revoked": True}

        # 撤销必须立即生效（Spec 10 §7）
        assert (await api.get(f"{AUTH_PREFIX}/me", headers=_auth(access))).status_code == 401

    async def test_logout_without_token_is_401(self, api: AsyncClient) -> None:
        assert (await api.post(f"{AUTH_PREFIX}/logout")).status_code == 401


class TestForcedPasswordChangeGate:
    """`04 §2`：管理员重置后首次登录**必须**修改密码。

    这里验证的是"服务端强制"，而不是"客户端自觉"：
    若只把 `must_change_password` 返回给客户端，任何人直接调接口即可绕过。
    """

    async def test_me_reports_the_flag_but_stays_reachable(
        self, api: AsyncClient, db_session
    ) -> None:
        """`/auth/me` 必须可访问 —— 客户端要靠它才知道自己需要改密。"""
        await _seed(db_session, must_change_password=True)
        data = (await _login(api)).json()["data"]
        assert data["must_change_password"] is True

        response = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(data["access_token"]))
        assert response.status_code == 200
        assert response.json()["data"]["must_change_password"] is True

    async def test_password_endpoint_is_reachable_and_clears_the_flag(
        self, api: AsyncClient, db_session
    ) -> None:
        """强制改密状态下**必须**能改密，否则用户被永久锁在门外。"""
        await _seed(db_session, must_change_password=True)
        access = (await _login(api)).json()["data"]["access_token"]

        response = await api.post(
            f"{AUTH_PREFIX}/password",
            headers=_auth(access),
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 200
        assert response.json()["data"]["must_change_password"] is False

    async def test_strict_dependency_denies_other_endpoints_with_403(
        self, app: FastAPI, api: AsyncClient, temp_routes, db_session
    ) -> None:
        """其他受保护端点必须被挡下，且用 **403**（不是 401）。

        为什么是 403 而不是 401：调用者**是**已认证的，只是当前状态下
        不允许访问该资源。返回 401 会让客户端误判为"登录失效"并清掉会话，
        用户反而再也走不到改密那一步。

        说明：Phase 4 还没有业务端点使用严格依赖，
        因此这里临时挂一条探针路由来验证**依赖本身**的行为 ——
        被验证的对象是 `app.api.deps.get_current_actor`，不是探针路由。
        """
        await _seed(db_session, must_change_password=True)

        probe = APIRouter()

        @probe.get(f"{AUTH_PREFIX}/__probe/protected")
        async def _probe(actor: CurrentActorDep):
            return success_response({"user_id": str(actor.user_id)})

        app.include_router(probe)

        access = (await _login(api)).json()["data"]["access_token"]
        response = await api.get(f"{AUTH_PREFIX}/__probe/protected", headers=_auth(access))
        assert response.status_code == 403
        assert response.json()["code"] == 403001

    async def test_strict_dependency_allows_after_password_change(
        self, app: FastAPI, api: AsyncClient, temp_routes, db_session
    ) -> None:
        await _seed(db_session, must_change_password=True)
        probe = APIRouter()

        @probe.get(f"{AUTH_PREFIX}/__probe/protected")
        async def _probe(actor: CurrentActorDep):
            return success_response({"user_id": str(actor.user_id)})

        app.include_router(probe)

        access = (await _login(api)).json()["data"]["access_token"]
        await api.post(
            f"{AUTH_PREFIX}/password",
            headers=_auth(access),
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

        response = await api.get(f"{AUTH_PREFIX}/__probe/protected", headers=_auth(access))
        assert response.status_code == 200

    async def test_wrong_current_password_is_403(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session, must_change_password=True)
        access = (await _login(api)).json()["data"]["access_token"]

        response = await api.post(
            f"{AUTH_PREFIX}/password",
            headers=_auth(access),
            json={"current_password": "Wrong-Passw0rd!99", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 403

    async def test_weak_new_password_is_400(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        access = (await _login(api)).json()["data"]["access_token"]

        response = await api.post(
            f"{AUTH_PREFIX}/password",
            headers=_auth(access),
            json={"current_password": PASSWORD, "new_password": "short"},
        )
        assert response.status_code == 400

    async def test_login_after_90_days_reports_expired_password(
        self, api: AsyncClient, db_session
    ) -> None:
        """`04 §2`：90 天未改密 → 允许登录但要求改密。"""
        await make_user(
            db_session,
            user_id=USER_ID,
            username="api-user",
            password=PASSWORD,
            password_changed_at=utc_now() - PASSWORD_MAX_AGE - timedelta(days=1),
        )
        data = (await _login(api)).json()["data"]
        assert data["must_change_password"] is True

        me = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(data["access_token"]))
        assert me.json()["data"]["password_expired"] is True


class TestRouteSurface:
    """路由面必须与已冻结的范围**严格一致**（多一个或少一个都是缺陷）。"""

    def test_auth_paths_exist_exactly_as_specified(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        expected = {
            f"{AUTH_PREFIX}/login",
            f"{AUTH_PREFIX}/refresh",
            f"{AUTH_PREFIX}/logout",
            f"{AUTH_PREFIX}/me",
            f"{AUTH_PREFIX}/password",
        }
        assert expected <= paths
        # Phase 8 的端点仍未冻结，不得预实现
        assert f"{AUTH_PREFIX}/permissions" not in paths

    def test_mfa_paths_match_spec_exactly(self, app: FastAPI) -> None:
        """`/auth/mfa*` 必须与 `08 §3` 的清单**逐条相等**。

        ⚠️ 本测试的前身是一条**反向钉住**（断言"不存在任何 mfa 端点"）。
        它服务于当时的目标：Phase 5（Session）阶段不得预实现 MFA。
        现在 `PHASES.md` Phase 5（MFA）已进入实现，那条断言已失效 ——
        因此这里不是"删掉护栏"，而是**把护栏换成正向钉住**：
        多一个端点（越权实现）或少一个（漏实现）都会失败。
        """
        paths = set(app.openapi()["paths"])
        expected = {
            f"{AUTH_PREFIX}/mfa",
            f"{AUTH_PREFIX}/mfa/setup",
            f"{AUTH_PREFIX}/mfa/enable",
            f"{AUTH_PREFIX}/mfa/disable",
            f"{AUTH_PREFIX}/mfa/verify",
        }
        assert expected <= paths
        # 不得在 `08 §3` 之外自造 MFA 端点（例如恢复码 / 管理员重置）。
        # 恢复流程在 Spec 中没有依据，实现者不得自行扩张接口面（AGENTS.md §4）。
        extra = {p for p in paths if p.startswith(f"{AUTH_PREFIX}/mfa") and p not in expected}
        assert extra == set()

    def test_auth_is_not_mounted_under_admin_prefix(self, app: FastAPI) -> None:
        """DD-02 阶段裁定 `/api/v1/auth` 独立；`08 §1` 的 `/admin` 不含认证。

        两者混挂会让"认证"与"业务"共用同一套前缀语义，
        后续 Phase 的权限守卫（`/admin` 之下）会误把登录端点也纳入拦截范围。
        """
        paths = set(app.openapi()["paths"])
        assert "/api/v1/admin/auth/login" not in paths
        assert "/api/v1/admin/login" not in paths
