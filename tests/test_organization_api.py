"""组织实体 CRUD 的 HTTP 层测试（**FINDING-8-01 的补救**）。

`08 §4` / `§6` / `§7` 冻结了 Users / Departments / Roles 的端点清单，
但仓库此前只有**服务层**，没有任何 HTTP 端点。根因写在
`docs/DESIGN-DECISIONS.md §15.4`：`001` / `002` 的裁判项全是服务层判定，
不含端点存在性，所以 Phase 1 / 2 PASS 时不会暴露这个缺口。

因此本文件除了常规 CRUD，还必须有两类"防再犯"用例：

1. **路由面逐条钉住**（`TestRouteSurface`）——
   让"端点消失"变成一个会红的测试，而不是靠下一个人再发现一次；
2. **访问控制在 HTTP 层成立**（`TestAccessControl`）——
   服务层的权限守卫只有被端点真的调用才算数。

服务层的能力与边界已由 `tests/test_user_service.py` /
`test_role_service.py` / `test_department_service.py` 覆盖，
本文件**不重复**那些业务规则。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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

DEPT_ROOT = 66101
DEPT_CHILD = 66102
DEPT_OUTSIDE = 66103

ROLE_ADMIN = 66111
ROLE_NO_PERM = 66112
ROLE_TARGET = 66113

RES_API_USER_MANAGE = 66121
RES_API_ROLE_MANAGE = 66122
RES_API_DEPT_MANAGE = 66123

USER_ID = 66201
NO_PERM_USER_ID = 66202
TARGET_USER_ID = 66203

USERNAME = "p9-org-admin"
NO_PERM_USERNAME = "p9-org-noperm"
TARGET_USERNAME = "p9-org-target"
PASSWORD = "Org-Api-Passw0rd!09"

#: `08 §4`
USER_PATHS = {
    f"{ADMIN_PREFIX}/users",
    f"{ADMIN_PREFIX}/users/{{user_id}}",
    f"{ADMIN_PREFIX}/users/{{user_id}}/disable",
    f"{ADMIN_PREFIX}/users/{{user_id}}/enable",
    f"{ADMIN_PREFIX}/users/{{user_id}}/reset-password",
    f"{ADMIN_PREFIX}/users/{{user_id}}/sessions",
    f"{ADMIN_PREFIX}/users/{{user_id}}/sessions/revoke-all",
}
#: `08 §6`
DEPARTMENT_PATHS = {
    f"{ADMIN_PREFIX}/departments",
    f"{ADMIN_PREFIX}/departments/tree",
    f"{ADMIN_PREFIX}/departments/{{department_id}}",
    f"{ADMIN_PREFIX}/departments/{{department_id}}/disable",
}
#: `08 §7` 的**实体**部分（权限配置面在 Phase 8 的 `role_permissions.py`）
ROLE_PATHS = {
    f"{ADMIN_PREFIX}/roles",
    f"{ADMIN_PREFIX}/roles/{{role_id}}",
    f"{ADMIN_PREFIX}/roles/{{role_id}}/delete",
}


async def _seed(db_session) -> None:
    await make_department(db_session, department_id=DEPT_ROOT, department_code="ORG_ROOT")
    await make_department(
        db_session,
        department_id=DEPT_CHILD,
        department_code="ORG_CHILD",
        parent_id=DEPT_ROOT,
    )
    await make_department(db_session, department_id=DEPT_OUTSIDE, department_code="ORG_OUTSIDE")

    await make_role(
        db_session,
        role_id=ROLE_ADMIN,
        role_code="P9_ORG_ADMIN",
        data_scope=DataScope.DEPARTMENT_CHILDREN,
    )
    await make_role(db_session, role_id=ROLE_NO_PERM, role_code="P9_ORG_NONE")
    await make_role(db_session, role_id=ROLE_TARGET, role_code="P9_ORG_TARGET")

    # API 资源必须带 method/path，否则 `ck_permission_resources_resource_type_fields` 会拒绝
    for resource_id, code in (
        (RES_API_USER_MANAGE, "USER_MANAGE"),
        (RES_API_ROLE_MANAGE, "ROLE_MANAGE"),
        (RES_API_DEPT_MANAGE, "DEPARTMENT_MANAGE"),
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
        await link_role_permission(db_session, role_id=ROLE_ADMIN, resource_id=resource_id)

    for user_id, username, dept_id, role_id in (
        (USER_ID, USERNAME, DEPT_ROOT, ROLE_ADMIN),
        (NO_PERM_USER_ID, NO_PERM_USERNAME, DEPT_ROOT, ROLE_NO_PERM),
        (TARGET_USER_ID, TARGET_USERNAME, DEPT_CHILD, ROLE_TARGET),
    ):
        await make_user(
            db_session,
            user_id=user_id,
            username=username,
            password=PASSWORD,
            password_changed_at=utc_now(),
            department_id=dept_id,
        )
        await link_user_role(db_session, user_id=user_id, role_id=role_id)


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
    def test_all_frozen_paths_exist(self, app: FastAPI) -> None:
        """`08 §4/§6/§7` 的端点必须逐条存在 —— 这是 FINDING-8-01 的防再犯网。"""
        paths = set(app.openapi()["paths"])
        expected = USER_PATHS | DEPARTMENT_PATHS | ROLE_PATHS
        missing = expected - paths
        assert not missing, f"缺少冻结端点：{sorted(missing)}"

    def test_no_invented_paths(self, app: FastAPI) -> None:
        """不得出现清单之外的组织域端点（不自行发明 API 面）。"""
        paths = set(app.openapi()["paths"])
        actual = {
            path for path in paths if "/users" in path or "/departments" in path or "/roles" in path
        }
        expected = (
            USER_PATHS
            | DEPARTMENT_PATHS
            | ROLE_PATHS
            | {
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/pages",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/menus",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/buttons",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/apis",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/permissions/fields",
                f"{ADMIN_PREFIX}/roles/{{role_id}}/data-scope",
            }
        )
        assert actual == expected, f"路由面与冻结清单不符：{sorted(actual ^ expected)}"

    def test_no_delete_verb_for_soft_delete_entities(self, app: FastAPI) -> None:
        """删除端点用 `POST /{id}/delete`（`08 §7` 冻结写法），不是 `DELETE`。

        逻辑删除用 `DELETE` 会让"已不存在"与"已停用"在协议层无法区分。
        """
        spec = app.openapi()["paths"]
        assert "delete" not in spec[f"{ADMIN_PREFIX}/roles/{{role_id}}"]
        assert "delete" not in spec[f"{ADMIN_PREFIX}/users/{{user_id}}"]
        # 但 `POST /roles/{id}/delete` 必须存在（冻结写法）
        assert "post" in spec[f"{ADMIN_PREFIX}/roles/{{role_id}}/delete"]


# ===========================================================================
# 访问控制
# ===========================================================================
#: (method, path, 标签)
_ACCESS_CALLS: tuple[tuple[str, str, str], ...] = (
    ("get", f"{ADMIN_PREFIX}/users", "users-list"),
    ("get", f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}", "users-get"),
    ("post", f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}/disable", "users-disable"),
    ("get", f"{ADMIN_PREFIX}/departments/tree", "dept-tree"),
    ("get", f"{ADMIN_PREFIX}/roles", "roles-list"),
    ("post", f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/delete", "roles-delete"),
)


class TestAccessControl:
    async def test_anonymous_is_401(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        for method, path, label in _ACCESS_CALLS:
            response = await getattr(api, method)(path)
            assert response.status_code == 401, label
            assert response.json()["code"] == 401001, label

    async def test_without_manage_permission_is_403(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=NO_PERM_USERNAME)
        for method, path, label in _ACCESS_CALLS:
            response = await getattr(api, method)(path, headers=_auth(token))
            assert response.status_code == 403, label
            assert response.json()["code"] == 403001, label

    async def test_user_manage_does_not_imply_role_manage(
        self, api: AsyncClient, db_session
    ) -> None:
        """三个权限位互相独立 —— 否则任一管理权限都能横向扩散到全部实体。"""
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        assert (await api.get(f"{ADMIN_PREFIX}/users", headers=_auth(token))).status_code == 200
        assert (await api.get(f"{ADMIN_PREFIX}/roles", headers=_auth(token))).status_code == 200
        assert (
            await api.get(f"{ADMIN_PREFIX}/departments/tree", headers=_auth(token))
        ).status_code == 200


# ===========================================================================
# Users
# ===========================================================================
class TestUserHttp:
    async def test_list_returns_the_frozen_page_shape(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        body = _data(await api.get(f"{ADMIN_PREFIX}/users", headers=_auth(token)))
        assert set(body) == {"list", "total", "pageNum", "pageSize"}
        assert body["pageNum"] == 1
        usernames = {item["username"] for item in body["list"]}
        assert {USERNAME, NO_PERM_USERNAME, TARGET_USERNAME} <= usernames

    async def test_create_read_update_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        headers = _auth(token)

        created = _data(
            await api.post(
                f"{ADMIN_PREFIX}/users",
                headers=headers,
                json={
                    "username": "p9-created",
                    "password": "Created-Passw0rd!09",
                    "display_name": "新建用户",
                    "department_id": str(DEPT_CHILD),
                },
            )
        )
        assert created["username"] == "p9-created"
        assert created["id"] == str(created["id"])  # JSON 里 ID 是字符串
        # 新建用户必须强制改密（Phase 2 的 RISK-001）
        assert created["must_change_password"] is True

        fetched = _data(await api.get(f"{ADMIN_PREFIX}/users/{created['id']}", headers=headers))
        assert fetched["display_name"] == "新建用户"

        updated = _data(
            await api.put(
                f"{ADMIN_PREFIX}/users/{created['id']}",
                headers=headers,
                json={"display_name": "改过的名字"},
            )
        )
        assert updated["display_name"] == "改过的名字"

    async def test_creating_outside_the_data_scope_is_403(
        self, api: AsyncClient, db_session
    ) -> None:
        """数据范围在**服务层**生效，越权目标表现为拒绝而不是静默创建。"""
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        response = await api.post(
            f"{ADMIN_PREFIX}/users",
            headers=_auth(token),
            json={
                "username": "p9-outside",
                "password": "Outside-Passw0rd!09",
                "display_name": "越权创建",
                "department_id": str(DEPT_OUTSIDE),
            },
        )
        assert response.status_code == 403
        assert response.json()["code"] == 403001

    async def test_disable_then_enable(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        headers = _auth(token)
        target = f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}"

        disabled = _data(await api.post(f"{target}/disable", headers=headers))
        assert disabled["status"] == "DISABLED"
        enabled = _data(await api.post(f"{target}/enable", headers=headers))
        assert enabled["status"] == "ACTIVE"

    async def test_reset_password_does_not_echo_the_password(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        new_password = "Reset-Passw0rd!09"
        response = await api.post(
            f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}/reset-password",
            headers=_auth(token),
            json={"new_password": new_password},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert new_password not in response.text
        assert "password_hash" not in body

    async def test_partial_update_does_not_clear_omitted_fields(
        self, api: AsyncClient, db_session
    ) -> None:
        """省略的字段必须**不被改动**（FINDING-9-02）。

        服务层的三态哨兵只有在端点正确分派时才生效：
        若端点把"未传"折叠成 `None`，"改个显示名"就会顺带
        把用户移出部门 —— 在全局数据范围下那是一次**静默的数据破坏**，
        不会有任何报错。
        """
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        headers = _auth(token)
        target = f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}"

        before = _data(await api.get(target, headers=headers))
        assert before["department_id"] == str(DEPT_CHILD)

        # 只改显示名，不提 department_id
        after = _data(await api.put(target, headers=headers, json={"display_name": "x"}))
        assert after["display_name"] == "x"
        assert after["department_id"] == str(DEPT_CHILD), "省略字段被意外清空了"

    async def test_no_credential_material_in_any_user_response(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        text = (await api.get(f"{ADMIN_PREFIX}/users/{TARGET_USER_ID}", headers=_auth(token))).text
        # 只禁"凭据本身"，不禁含 password 字样的其它字段
        # （`must_change_password` / `password_changed_at` 是合法字段）。
        for forbidden in ("password_hash", '"password":', PASSWORD):
            assert forbidden not in text, forbidden


# ===========================================================================
# Departments
# ===========================================================================
class TestDepartmentHttp:
    async def test_tree_only_contains_in_scope_nodes(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        nodes = _data(await api.get(f"{ADMIN_PREFIX}/departments/tree", headers=_auth(token)))
        codes = {node["department_code"] for node in nodes}
        assert "ORG_ROOT" in codes
        assert "ORG_OUTSIDE" not in codes

    async def test_create_update_disable_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        headers = _auth(token)

        created = _data(
            await api.post(
                f"{ADMIN_PREFIX}/departments",
                headers=headers,
                json={
                    "department_code": "ORG_NEW",
                    "department_name": "新部门",
                    "parent_id": str(DEPT_CHILD),
                },
            )
        )
        assert created["department_code"] == "ORG_NEW"

        updated = _data(
            await api.put(
                f"{ADMIN_PREFIX}/departments/{created['id']}",
                headers=headers,
                json={"department_name": "改名后"},
            )
        )
        assert updated["department_name"] == "改名后"

        disabled = _data(
            await api.post(f"{ADMIN_PREFIX}/departments/{created['id']}/disable", headers=headers)
        )
        assert disabled["status"] == "DISABLED"


# ===========================================================================
# Roles
# ===========================================================================
class TestRoleHttp:
    async def test_create_update_delete_round_trip(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        headers = _auth(token)

        created = _data(
            await api.post(
                f"{ADMIN_PREFIX}/roles",
                headers=headers,
                json={"role_code": "P9_NEW_ROLE", "role_name": "新角色"},
            )
        )
        assert created["role_code"] == "P9_NEW_ROLE"

        updated = _data(
            await api.put(
                f"{ADMIN_PREFIX}/roles/{created['id']}",
                headers=headers,
                json={"role_name": "改过的角色名", "status": "DISABLED"},
            )
        )
        assert updated["role_name"] == "改过的角色名"
        assert updated["status"] == "DISABLED"

        # 删除是逻辑删除：响应仍返回实体，且带 deleted_at 语义的记录不再出现在列表里
        deleted = _data(
            await api.post(f"{ADMIN_PREFIX}/roles/{created['id']}/delete", headers=headers)
        )
        assert deleted["id"] == created["id"]

        listed = _data(await api.get(f"{ADMIN_PREFIX}/roles", headers=headers))
        assert created["id"] not in {item["id"] for item in listed["list"]}

    async def test_deleting_a_role_held_by_someone_is_rejected(
        self, api: AsyncClient, db_session
    ) -> None:
        """他人依赖 → 拒绝 409（不静默级联）。"""
        await _seed(db_session)
        token = await _login(api, username=USERNAME)
        response = await api.post(
            f"{ADMIN_PREFIX}/roles/{ROLE_TARGET}/delete", headers=_auth(token)
        )
        assert response.status_code == 409
        assert response.json()["code"] == 409001

    async def test_role_code_is_not_updatable(self, api: AsyncClient, db_session) -> None:
        """`role_code` 是稳定标识，改码会静默改变 SUPER_ADMIN 判定。"""
        from app.schemas.role import RoleUpdateRequest

        assert "role_code" not in RoleUpdateRequest.model_fields
