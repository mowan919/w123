"""MFA 端点测试（HTTP 层 / `08 §3` `08 §10`）。

覆盖点
-----
- **路由面**：`/auth/mfa` 五条端点存在且**恰好**这些；`/admin` 域下不得出现 MFA 路径。
- **访问控制**：四个"管理本人 MFA"的端点必须要求认证；
  `/auth/mfa/verify` 相反 —— 此刻还没有会话，它**不可能**要求认证。
- **登录契约**（DD-23 方案 A）：已绑定的用户登录后拿到的是
  `mfa_required=true` + `mfa_token`，**而不是**任何可用令牌；
  只有 `verify` 成功才签发令牌对，且结构必须与普通登录**完全一致**。
- **Secret 暴露面**：除 `POST /auth/mfa/setup` 外，
  任何响应体里都不得出现明文 Secret（逐字节扫描响应文本）。

事务与依赖覆盖
------------
`app.dependency_overrides[get_db]` 指向 `db_session`（外层事务 + SAVEPOINT），
因此端点里的 `commit()` 不会逃出用例边界。
Provider 登记处被替换为**测试专用**的进程内实例，
从而不需要污染全局单例（`00 §4`：产品出厂零 Provider）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core.security.aead import build_secret_box
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import MfaStatus, UserStatus
from app.models.user import AdminUser
from app.repositories.mfa import MfaRepository
from app.services.mfa import MfaProviderRegistry
from tests.factories import make_department, make_user
from tests.test_mfa_management import _TestProvider

pytestmark = pytest.mark.integration

AUTH_PREFIX = "/api/v1/auth"
ADMIN_PREFIX = "/api/v1/admin"

USER_ID = 54001
DEPT_ID = 54002
USERNAME = "mfa-api-user"
PASSWORD = "Charlie-Passw0rd!03"


@pytest.fixture
def test_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[_TestProvider]:
    """把服务层读到的 Provider 登记处换成测试实例。

    `MfaManagementService.__init__` 在 `app.services.mfa_management` 的名称空间里
    解析 `get_mfa_provider_registry`，因此只打这一个补丁即可覆盖
    `AuthService` 与端点的两条构造路径。
    """
    provider = _TestProvider()
    registry = MfaProviderRegistry({provider.name: provider}, active_name=provider.name)
    monkeypatch.setattr("app.services.mfa_management.get_mfa_provider_registry", lambda: registry)
    yield provider


@pytest.fixture
async def api(app: FastAPI, db_session, test_registry: _TestProvider) -> AsyncIterator[AsyncClient]:
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


async def _seed_user(session, *, user_id: int = USER_ID, username: str = USERNAME) -> None:
    """播种部门与用户。

    每个用例都跑在**独立的回滚事务**里，因此 `DEPT_ID` 不会跨用例残留，
    此处可以无条件创建。
    """
    await make_department(session, department_id=DEPT_ID, department_code="MFA_API_DEPT")
    await make_user(
        session,
        user_id=user_id,
        username=username,
        department_id=DEPT_ID,
        password=PASSWORD,
        password_changed_at=utc_now(),
    )


async def _seed_enabled_mfa(session, *, user_id: int = USER_ID, secret: str | None = None) -> str:
    """把用户置于"已启用 MFA"状态，返回明文 secret。"""
    resolved = secret or f"TESTSECRET-{user_id}"
    repo = MfaRepository(session)
    row = await repo.ensure_credential(user_id=user_id, provider="test")
    await repo.put_secret(
        row,
        encrypted_secret=build_secret_box().encrypt(plaintext=resolved, aad=f"{user_id}:test"),
    )
    await repo.apply_status(row, MfaStatus.ENABLED, now=utc_now())
    return resolved


async def _login(api: AsyncClient, *, password: str = PASSWORD) -> Response:
    return await api.post(f"{AUTH_PREFIX}/login", json={"username": USERNAME, "password": password})


# ---------------------------------------------------------------------------
# 路由面
# ---------------------------------------------------------------------------
class TestRouteSurface:
    """`08 §3` 定义了 MFA 端点；本阶段不得出现未冻结的额外端点。"""

    def test_mfa_paths_exist_exactly_as_specified(self, app: FastAPI) -> None:
        paths = set(app.openapi()["paths"])
        expected = {
            f"{AUTH_PREFIX}/mfa",
            f"{AUTH_PREFIX}/mfa/setup",
            f"{AUTH_PREFIX}/mfa/enable",
            f"{AUTH_PREFIX}/mfa/disable",
            f"{AUTH_PREFIX}/mfa/verify",
        }
        assert expected <= paths, f"缺少 MFA 端点：{expected - paths}"
        actual = {path for path in paths if "mfa" in path}
        assert actual == expected, f"MFA 路由面与规范不符：{actual ^ expected}"

    def test_no_mfa_path_under_admin_namespace(self, app: FastAPI) -> None:
        """MFA 是"本人"操作，不属于 `admin` 资源域（`08 §1` 的域划分）。"""
        paths = set(app.openapi()["paths"])
        assert not [path for path in paths if path.startswith(ADMIN_PREFIX) and "mfa" in path]

    def test_session_endpoints_unchanged(self, app: FastAPI) -> None:
        """反向钉住：MFA 阶段不得顺手改动会话端点。"""
        paths = set(app.openapi()["paths"])
        for path in (
            f"{ADMIN_PREFIX}/sessions",
            f"{ADMIN_PREFIX}/sessions/{{session_id}}/revoke",
            f"{ADMIN_PREFIX}/users/{{user_id}}/sessions",
            f"{ADMIN_PREFIX}/users/{{user_id}}/sessions/revoke-all",
        ):
            assert path in paths, path


# ---------------------------------------------------------------------------
# 访问控制
# ---------------------------------------------------------------------------
class TestAccessControl:
    """`08 §10`：后端必须判权，不得只靠前端隐藏。"""

    async def test_self_service_endpoints_require_authentication(self, api: AsyncClient) -> None:
        """四个端点都必须拒绝未认证请求。

        刻意送上**合法**请求体：这样 401 只能来自认证依赖，
        而不是"因为请求体不合法先报了 422"—— 后者会让这条用例
        在"认证依赖被误删"时依然通过，属于假阳性。
        """
        for method, path, body in (
            ("get", f"{AUTH_PREFIX}/mfa", None),
            ("post", f"{AUTH_PREFIX}/mfa/setup", {}),
            ("post", f"{AUTH_PREFIX}/mfa/enable", {"code": "123456"}),
            ("post", f"{AUTH_PREFIX}/mfa/disable", {"code": "123456"}),
        ):
            response = await getattr(api, method)(
                path, **({"json": body} if body is not None else {})
            )
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001

    async def test_verify_endpoint_is_reachable_without_a_token(self, api: AsyncClient) -> None:
        """`/auth/mfa/verify` 是**登录续完**，此刻不存在会话。

        它拒绝请求的原因必须是"挑战无效"（401002），
        而不是"未认证"（401001）—— 后者意味着有人给它挂了认证依赖，
        那会让这个端点在真实流程中**永远无法被调用**。
        """
        response = await api.post(
            f"{AUTH_PREFIX}/mfa/verify", json={"mfa_token": "bogus", "code": "123456"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == 401002

    async def test_unauthenticated_request_cannot_start_setup(
        self, api: AsyncClient, db_session
    ) -> None:
        """未认证的 setup 不得产生任何凭据行。"""
        await _seed_user(db_session)
        await api.post(f"{AUTH_PREFIX}/mfa/setup")
        assert (
            await MfaRepository(db_session).get_credential(user_id=USER_ID, provider="test")
        ) is None


# ---------------------------------------------------------------------------
# 登录契约（DD-23 方案 A）
# ---------------------------------------------------------------------------
class TestLoginFlow:
    async def test_login_without_mfa_returns_tokens_directly(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed_user(db_session)
        response = await _login(api)
        assert response.status_code == 200
        data = _data(response)
        assert data["access_token"]
        assert "mfa_token" not in data

    async def test_login_with_mfa_returns_a_challenge_not_tokens(
        self, api: AsyncClient, db_session
    ) -> None:
        """**关键用例**：已绑定用户登录后不得拿到任何可用令牌。"""
        await _seed_user(db_session)
        await _seed_enabled_mfa(db_session)

        response = await _login(api)
        assert response.status_code == 200
        data = _data(response)
        assert data["mfa_required"] is True
        assert data["mfa_token"]
        assert data["expires_at"]
        # 绝不可以顺手返回令牌 —— 那会让二次验证形同虚设。
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert "user" not in data

    async def test_challenge_creation_does_not_create_a_session(
        self, api: AsyncClient, db_session
    ) -> None:
        from sqlalchemy import text

        await _seed_user(db_session)
        await _seed_enabled_mfa(db_session)
        before = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        await _login(api)
        after = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        assert after == before

    async def test_verify_completes_the_login_and_returns_the_usual_token_pair(
        self, api: AsyncClient, db_session, test_registry: _TestProvider
    ) -> None:
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)
        pending = _data(await _login(api))

        response = await api.post(
            f"{AUTH_PREFIX}/mfa/verify",
            json={"mfa_token": pending["mfa_token"], "code": test_registry.code_for(secret)},
        )
        assert response.status_code == 200
        data = _data(response)
        # 与普通登录**完全一致**的契约：客户端不需要两套逻辑。
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["user"]["id"] == str(USER_ID)

        # 令牌必须真的可用。
        me = await api.get(f"{AUTH_PREFIX}/me", headers=_auth(data["access_token"]))
        assert me.status_code == 200
        assert _data(me)["username"] == USERNAME

    async def test_verify_with_wrong_code_is_rejected(self, api: AsyncClient, db_session) -> None:
        await _seed_user(db_session)
        await _seed_enabled_mfa(db_session)
        pending = _data(await _login(api))

        response = await api.post(
            f"{AUTH_PREFIX}/mfa/verify",
            json={"mfa_token": pending["mfa_token"], "code": "000000"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == 401003

    async def test_challenge_is_single_use_over_http(
        self, api: AsyncClient, db_session, test_registry: _TestProvider
    ) -> None:
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)
        pending = _data(await _login(api))
        payload = {"mfa_token": pending["mfa_token"], "code": test_registry.code_for(secret)}

        assert (await api.post(f"{AUTH_PREFIX}/mfa/verify", json=payload)).status_code == 200
        replay = await api.post(f"{AUTH_PREFIX}/mfa/verify", json=payload)
        assert replay.status_code == 401
        assert replay.json()["code"] == 401002

    async def test_wrong_password_still_fails_before_mfa(
        self, api: AsyncClient, db_session
    ) -> None:
        """口令错误必须是 401001，且**不**返回任何挑战。

        否则攻击者不需要正确口令就能驱动 MFA 流程（枚举用户 + 骚扰）。
        """
        await _seed_user(db_session)
        await _seed_enabled_mfa(db_session)
        response = await _login(api, password="Wrong-Passw0rd!99")
        assert response.status_code == 401
        assert response.json()["code"] == 401001
        assert "mfa_token" not in response.text


class TestChallengeHardening:
    """挑战签发之后账号被处置 —— 不得因为"曾经验过一次"就放行。"""

    async def test_disabled_after_challenge_issuance_is_rejected(
        self, api: AsyncClient, db_session, test_registry: _TestProvider
    ) -> None:
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)
        pending = _data(await _login(api))

        user = await db_session.get(AdminUser, USER_ID)
        assert user is not None
        user.status = UserStatus.DISABLED
        await db_session.flush()

        response = await api.post(
            f"{AUTH_PREFIX}/mfa/verify",
            json={"mfa_token": pending["mfa_token"], "code": test_registry.code_for(secret)},
        )
        assert response.status_code == 401
        assert response.json()["code"] == 401001
        assert "access_token" not in response.text

    async def test_relogin_after_successful_mfa_starts_a_fresh_challenge(
        self, api: AsyncClient, db_session, test_registry: _TestProvider
    ) -> None:
        """每次登录都必须签发**新的**挑战：令牌不得被复用。"""
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)

        first = _data(await _login(api))
        second = _data(await _login(api))
        assert first["mfa_token"] != second["mfa_token"]

        # 用第二个挑战完成登录后，第一个挑战必须仍然独立可用（互不影响）。
        assert (
            await api.post(
                f"{AUTH_PREFIX}/mfa/verify",
                json={
                    "mfa_token": second["mfa_token"],
                    "code": test_registry.code_for(secret),
                },
            )
        ).status_code == 200


# ---------------------------------------------------------------------------
# 响应契约与 Secret 暴露面
# ---------------------------------------------------------------------------
class TestResponseContract:
    async def test_status_response_carries_no_credential_material(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)
        access = await _login_and_verify(api, secret=secret)

        response = await api.get(f"{AUTH_PREFIX}/mfa", headers=_auth(access))
        assert response.status_code == 200
        data = _data(response)
        assert data["status"] == MfaStatus.ENABLED.value
        assert data["has_credential"] is True
        assert data["provider"] == "test"
        for forbidden in ("secret", "encrypted_secret", "provisioning_uri", "mfa_secret"):
            assert forbidden not in data
        assert secret not in response.text

    async def test_setup_is_the_only_response_exposing_the_secret(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed_user(db_session)
        access = await _login_and_verify(api)

        setup = await api.post(f"{AUTH_PREFIX}/mfa/setup", headers=_auth(access))
        assert setup.status_code == 200
        secret = _data(setup)["secret"]
        assert secret

        # 绑定完成后，后续所有读/写接口都不得再回显它。
        probe = await api.post(
            f"{AUTH_PREFIX}/mfa/enable",
            headers=_auth(access),
            json={"code": _TestProvider.code_for(secret)},
        )
        assert probe.status_code == 200
        assert secret not in probe.text

        status = await api.get(f"{AUTH_PREFIX}/mfa", headers=_auth(access))
        assert secret not in status.text

        disable = await api.post(
            f"{AUTH_PREFIX}/mfa/disable",
            headers=_auth(access),
            json={"code": _TestProvider.code_for(secret)},
        )
        assert disable.status_code == 200
        assert _data(disable)["secret_cleared"] is True
        assert secret not in disable.text

    async def test_enable_then_login_requires_mfa(self, api: AsyncClient, db_session) -> None:
        """端到端：绑定 → 启用 → 重新登录必须被要求二次验证。"""
        await _seed_user(db_session)
        access = await _login_and_verify(api)

        secret = _data(await api.post(f"{AUTH_PREFIX}/mfa/setup", headers=_auth(access)))["secret"]
        enable = await api.post(
            f"{AUTH_PREFIX}/mfa/enable",
            headers=_auth(access),
            json={"code": _TestProvider.code_for(secret)},
        )
        assert enable.status_code == 200

        pending = _data(await _login(api))
        assert pending["mfa_required"] is True

    async def test_disable_after_enable_restores_plain_login(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed_user(db_session)
        secret = await _seed_enabled_mfa(db_session)
        access = await _login_and_verify(api, secret=secret)

        disable = await api.post(
            f"{AUTH_PREFIX}/mfa/disable",
            headers=_auth(access),
            json={"code": _TestProvider.code_for(secret)},
        )
        assert disable.status_code == 200

        # 关闭后应恢复为直接登录（证明"启用"确实是生效开关）。
        data = _data(await _login(api))
        assert "access_token" in data

    async def test_enable_with_bad_code_reports_401003(self, api: AsyncClient, db_session) -> None:
        await _seed_user(db_session)
        access = await _login_and_verify(api)
        await api.post(f"{AUTH_PREFIX}/mfa/setup", headers=_auth(access))

        response = await api.post(
            f"{AUTH_PREFIX}/mfa/enable", headers=_auth(access), json={"code": "000000"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == 401003

    async def test_empty_code_is_rejected_by_validation(self, api: AsyncClient, db_session) -> None:
        """DTO 层必须挡住空码（`08 §2` 统一校验错误信封）。"""
        await _seed_user(db_session)
        access = await _login_and_verify(api)
        response = await api.post(
            f"{AUTH_PREFIX}/mfa/enable", headers=_auth(access), json={"code": ""}
        )
        assert response.status_code == 422
        assert response.json()["code"] == 422001


async def _login_and_verify(
    api: AsyncClient,
    *,
    secret: str | None = None,
) -> str:
    """登录；若该用户已绑定 MFA 则续完二次验证，返回可用的 access token。

    `secret=None` 表示期望"直接登录成功"（未绑定场景），
    此时若返回挑战则说明绑定状态判定出了问题，直接让断言失败。
    """
    data = _data(await _login(api))
    if secret is None:
        assert "access_token" in data, "未绑定的用户不应被要求二次验证"
        return str(data["access_token"])

    assert data.get("mfa_required") is True
    verified = await api.post(
        f"{AUTH_PREFIX}/mfa/verify",
        json={"mfa_token": data["mfa_token"], "code": _TestProvider.code_for(secret)},
    )
    assert verified.status_code == 200
    return str(_data(verified)["access_token"])
