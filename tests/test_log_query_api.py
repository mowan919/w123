"""审计日志与链路追踪的查询测试（**FINDING-10-01 的补救**）。

`08 §8` 冻结了 `GET /audit/logs*`、`GET /traces*` 四条端点，
但仓库此前**一条都没有**。根因与 FINDING-8-01 同源：
Phase 6 的裁判（`006-logging-audit.md`，35 项）全是**落库**判定，
没有任何一项问"能不能查出来"，于是那次 PASS 不会暴露它。

因此本文件必须有两类"防再犯"用例：

1. **路由面逐条钉住**（`TestRouteSurface`）——
   让"端点消失"变成会红的测试；
2. **权限位互不隐含**（`TestAccessControl`）——
   `AUDIT_READ` 与 `TRACE_READ` 是两个位，
   查审计不等于能看链路正文（链路含应用日志正文，信息面更宽）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import PermissionResourceType, PermissionStatus
from app.models.logs import (
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)
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

DEPT_ID = 67101

ROLE_AUDITOR = 67111
ROLE_NO_PERM = 67112

RES_AUDIT_READ = 67121
RES_TRACE_READ = 67122

USER_ID = 67201
NO_PERM_USER_ID = 67202

USERNAME = "p10-auditor"
NO_PERM_USERNAME = "p10-noperm"
PASSWORD = "Log-Query-Passw0rd!10"

TRACE_A = "trace-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01"
TRACE_B = "trace-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb02"
REQ_A = "req-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01"

AUDIT_ROW_1 = 67211
AUDIT_ROW_2 = 67212
AUDIT_ROW_3 = 67213

#: `08 §8` 的冻结路径
FROZEN_PATHS = {
    f"{ADMIN_PREFIX}/audit/logs",
    f"{ADMIN_PREFIX}/audit/logs/{{audit_log_id}}",
    f"{ADMIN_PREFIX}/traces",
    f"{ADMIN_PREFIX}/traces/{{trace_id}}",
}


async def _seed(db_session) -> None:
    await make_department(db_session, department_id=DEPT_ID, department_code="P10_DEPT")
    await make_role(
        db_session,
        role_id=ROLE_AUDITOR,
        role_code="P10_AUDITOR",
        data_scope=DataScope.ALL,
    )
    await make_role(db_session, role_id=ROLE_NO_PERM, role_code="P10_NONE")

    for resource_id, code in (
        (RES_AUDIT_READ, "AUDIT_READ"),
        (RES_TRACE_READ, "TRACE_READ"),
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
        await link_role_permission(db_session, role_id=ROLE_AUDITOR, resource_id=resource_id)

    for user_id, username, role_id in (
        (USER_ID, USERNAME, ROLE_AUDITOR),
        (NO_PERM_USER_ID, NO_PERM_USERNAME, ROLE_NO_PERM),
    ):
        await make_user(
            db_session,
            user_id=user_id,
            username=username,
            password=PASSWORD,
            password_changed_at=utc_now(),
            department_id=DEPT_ID,
        )
        await link_user_role(db_session, user_id=user_id, role_id=role_id)


async def _add_audit_log(
    db_session,
    *,
    audit_log_id: int,
    trace_id: str = TRACE_A,
    action: str = "USER_UPDATE",
    operator_id: int = USER_ID,
    operator_username: str = USERNAME,
    resource_type: str = "USER",
    resource_id: int | None = 1,
    result: str = "SUCCESS",
    created_at=None,
) -> AuditLog:
    row = AuditLog(
        id=audit_log_id,
        trace_id=trace_id,
        request_id=REQ_A,
        operator_id=operator_id,
        operator_username=operator_username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_data=None,
        after_data={"display_name": "changed"},
        result=result,
        error_code=None,
        ip="203.0.113.7",
        user_agent="pytest",
        created_at=created_at or utc_now(),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_trace_spread(db_session) -> None:
    """在**五张表**上各放一条同 trace 的日志。

    为什么必须覆盖五张表：`GET /traces/{traceId}` 的整个价值就是
    "一次请求在五类日志里的全貌"。只放一张表的用例会通过，
    但掩盖了"某张表忘了查"这种真实缺陷。
    """
    now = utc_now()
    db_session.add(
        AccessLog(
            id=67221,
            trace_id=TRACE_A,
            request_id=REQ_A,
            operator_id=USER_ID,
            method="PUT",
            path="/api/v1/admin/users/1",
            status_code=200,
            duration_ms=12,
            ip="203.0.113.7",
            user_agent="pytest",
            created_at=now,
        )
    )
    db_session.add(
        SecurityLog(
            id=67222,
            trace_id=TRACE_A,
            request_id=REQ_A,
            operator_id=USER_ID,
            operator_username=USERNAME,
            event="AUTH_LOGIN_SUCCESS",
            resource_type="SESSION",
            resource_id=None,
            result="SUCCESS",
            error_code=None,
            reason=None,
            ip="203.0.113.7",
            user_agent="pytest",
            created_at=now,
        )
    )
    db_session.add(
        OperationLog(
            id=67223,
            trace_id=TRACE_A,
            request_id=REQ_A,
            operator_id=USER_ID,
            operator_username=USERNAME,
            action="USER_UPDATE",
            resource_type="USER",
            resource_id=1,
            result="SUCCESS",
            error_code=None,
            ip="203.0.113.7",
            user_agent="pytest",
            created_at=now,
        )
    )
    db_session.add(
        ApplicationLog(
            id=67224,
            trace_id=TRACE_A,
            request_id=REQ_A,
            level="INFO",
            logger="app.services.user",
            message="user updated",
            created_at=now,
        )
    )
    # 另一条 trace：用于验证列表接口能区分不同链路
    db_session.add(
        AccessLog(
            id=67225,
            trace_id=TRACE_B,
            request_id="req-b",
            operator_id=NO_PERM_USER_ID,
            method="GET",
            path="/api/v1/admin/audit/logs",
            status_code=403,
            duration_ms=3,
            ip="203.0.113.8",
            user_agent="pytest",
            created_at=now + timedelta(seconds=1),
        )
    )
    await db_session.flush()


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


async def _login(api: AsyncClient, username: str) -> str:
    response = await api.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(response) -> dict:
    return response.json()["data"]


# ===========================================================================
# 路由面
# ===========================================================================
class TestRouteSurface:
    def test_frozen_paths_exist(self, app: FastAPI) -> None:
        """`08 §8` 的四条端点必须逐条存在 —— FINDING-10-01 的防再犯网。"""
        paths = set(app.openapi()["paths"])
        missing = FROZEN_PATHS - paths
        assert not missing, f"缺少冻结端点：{sorted(missing)}"

    def test_no_invented_paths(self, app: FastAPI) -> None:
        """不得出现清单之外的审计 / 链路端点（不自行发明 API 面）。"""
        paths = set(app.openapi()["paths"])
        actual = {path for path in paths if "/audit" in path or "/traces" in path}
        assert actual == FROZEN_PATHS, f"路由面与冻结清单不符：{sorted(actual ^ FROZEN_PATHS)}"


# ===========================================================================
# 访问控制
# ===========================================================================
class TestAccessControl:
    async def test_anonymous_is_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        for path in (
            f"{ADMIN_PREFIX}/audit/logs",
            f"{ADMIN_PREFIX}/traces",
        ):
            response = await api.get(path)
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001, path

    async def test_without_permission_is_403(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)
        for path in (
            f"{ADMIN_PREFIX}/audit/logs",
            f"{ADMIN_PREFIX}/audit/logs/{AUDIT_ROW_1}",
            f"{ADMIN_PREFIX}/traces",
            f"{ADMIN_PREFIX}/traces/{TRACE_A}",
        ):
            response = await api.get(path, headers=_auth(token))
            assert response.status_code == 403, path
            assert response.json()["code"] == 403001, path

    async def test_audit_read_does_not_imply_trace_read(self, api: AsyncClient, db_session) -> None:
        """两个权限位互相独立。

        为什么这条断言值得单独写：`GET /traces/{id}` 会返回
        **应用日志正文**，其信息面比审计表宽得多。若"能查审计"隐含了
        "能看链路"，那么任何一个只读审计权限的账号都能读到
        全部应用日志 —— 那是一次静默的权限放大。
        """
        await _seed(db_session)
        # 造一个**只有** AUDIT_READ 的角色
        await make_role(db_session, role_id=67113, role_code="P10_AUDIT_ONLY")
        await link_role_permission(db_session, role_id=67113, resource_id=RES_AUDIT_READ)
        await make_user(
            db_session,
            user_id=67203,
            username="p10-audit-only",
            password=PASSWORD,
            password_changed_at=utc_now(),
            department_id=DEPT_ID,
        )
        await link_user_role(db_session, user_id=67203, role_id=67113)

        token = await _login(api, username="p10-audit-only")
        assert (
            await api.get(f"{ADMIN_PREFIX}/audit/logs", headers=_auth(token))
        ).status_code == 200
        assert (await api.get(f"{ADMIN_PREFIX}/traces", headers=_auth(token))).status_code == 403


# ===========================================================================
# 审计日志
# ===========================================================================
class TestAuditLogHttp:
    async def test_list_returns_the_frozen_page_shape(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _add_audit_log(db_session, audit_log_id=AUDIT_ROW_1)
        token = await _login(api, username=USERNAME)

        body = _data(await api.get(f"{ADMIN_PREFIX}/audit/logs", headers=_auth(token)))
        assert set(body) == {"list", "total", "pageNum", "pageSize"}
        assert body["pageNum"] == 1
        assert body["pageSize"] == 20
        assert body["total"] >= 1
        first = body["list"][0]
        # `06 §2` 的 15 个字段一个不少，且 ID 在 JSON 里是字符串
        assert set(first) == {
            "id",
            "trace_id",
            "request_id",
            "operator_id",
            "operator_username",
            "action",
            "resource_type",
            "resource_id",
            "before_data",
            "after_data",
            "result",
            "error_code",
            "ip",
            "user_agent",
            "created_at",
        }
        assert first["id"] == str(AUDIT_ROW_1)

    async def test_filters_narrow_the_result(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _add_audit_log(db_session, audit_log_id=AUDIT_ROW_1, action="USER_UPDATE")
        await _add_audit_log(db_session, audit_log_id=AUDIT_ROW_2, action="ROLE_DELETE")
        await _add_audit_log(
            db_session, audit_log_id=AUDIT_ROW_3, action="USER_UPDATE", result="FAILURE"
        )
        token = await _login(api, username=USERNAME)
        headers = _auth(token)

        by_action = _data(
            await api.get(
                f"{ADMIN_PREFIX}/audit/logs", headers=headers, params={"action": "ROLE_DELETE"}
            )
        )
        assert by_action["total"] == 1
        assert by_action["list"][0]["action"] == "ROLE_DELETE"

        by_result = _data(
            await api.get(
                f"{ADMIN_PREFIX}/audit/logs",
                headers=headers,
                params={"action": "USER_UPDATE", "result": "FAILURE"},
            )
        )
        assert by_result["total"] == 1
        assert by_result["list"][0]["result"] == "FAILURE"

        by_operator = _data(
            await api.get(
                f"{ADMIN_PREFIX}/audit/logs",
                headers=headers,
                params={"operator_id": str(USER_ID)},
            )
        )
        assert by_operator["total"] == 3

    async def test_invalid_time_range_is_rejected(self, api: AsyncClient, db_session) -> None:
        """时间区间自相矛盾必须**报错**，不能安静返回 0 行。

        理由见 `LogQueryService._validate_range`：排障现场把
        "时间写反了"当成"没发生过"是最贵的误判。

        状态码取 400（`BAD_REQUEST` / 400001）而不是 422，与
        `SessionManagementService._validate_paging` 同口径：
        422 由 Pydantic 表达"参数**形状**不对"（例如 `pageSize=0`），
        而"两个参数各自合法、组合起来自相矛盾"是请求**语义**问题。
        """
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        response = await api.get(
            f"{ADMIN_PREFIX}/audit/logs",
            headers=_auth(token),
            params={
                "created_from": "2026-01-02T00:00:00Z",
                "created_to": "2026-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_detail_is_404_for_unknown_id(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        response = await api.get(f"{ADMIN_PREFIX}/audit/logs/{AUDIT_ROW_1}", headers=_auth(token))
        assert response.status_code == 404
        assert response.json()["code"] == 404001

    async def test_detail_returns_the_row(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _add_audit_log(db_session, audit_log_id=AUDIT_ROW_1)
        token = await _login(api, username=USERNAME)
        body = _data(
            await api.get(f"{ADMIN_PREFIX}/audit/logs/{AUDIT_ROW_1}", headers=_auth(token))
        )
        assert body["id"] == str(AUDIT_ROW_1)
        assert body["after_data"] == {"display_name": "changed"}


# ===========================================================================
# 链路
# ===========================================================================
class TestTraceHttp:
    async def test_list_groups_by_trace(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _seed_trace_spread(db_session)
        token = await _login(api, username=USERNAME)

        body = _data(await api.get(f"{ADMIN_PREFIX}/traces", headers=_auth(token)))
        assert set(body) == {"list", "total", "pageNum", "pageSize"}
        traces = {item["trace_id"]: item for item in body["list"]}
        assert TRACE_A in traces
        assert TRACE_B in traces
        # TRACE_B 更晚出现，因此排在前面（按最近出现时间倒序）
        ids = [item["trace_id"] for item in body["list"]]
        assert ids.index(TRACE_B) < ids.index(TRACE_A)

        summary = traces[TRACE_A]
        assert set(summary["counts"]) == {
            "access",
            "audit",
            "security",
            "operation",
            "application",
        }
        assert summary["counts"]["access"] == 1
        assert summary["counts"]["application"] == 1
        assert summary["total_entries"] == sum(summary["counts"].values())

    async def test_detail_replays_every_log_type(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _seed_trace_spread(db_session)
        await _add_audit_log(db_session, audit_log_id=AUDIT_ROW_1)
        token = await _login(api, username=USERNAME)

        body = _data(await api.get(f"{ADMIN_PREFIX}/traces/{TRACE_A}", headers=_auth(token)))
        assert body["trace_id"] == TRACE_A
        kinds = {entry["log_type"] for entry in body["entries"]}
        assert kinds == {"access", "audit", "security", "operation", "application"}
        assert len(body["entries"]) == 5

        access = next(entry for entry in body["entries"] if entry["log_type"] == "access")
        assert access["name"] == "PUT /api/v1/admin/users/1"
        assert access["result"] == "200"
        assert access["detail"]["duration_ms"] == 12

        application = next(entry for entry in body["entries"] if entry["log_type"] == "application")
        assert application["name"] == "INFO app.services.user"
        assert application["detail"]["message"] == "user updated"

    async def test_detail_is_404_for_unknown_trace(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        response = await api.get(
            f"{ADMIN_PREFIX}/traces/trace-does-not-exist", headers=_auth(token)
        )
        assert response.status_code == 404
        assert response.json()["code"] == 404001
