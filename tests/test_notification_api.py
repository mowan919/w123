"""站内通知 HTTP 面测试（Phase 14 / `DESIGN-DECISIONS §32`）。

三个文件各管一层，刻意的分工：

| 文件 | 管什么 |
|---|---|
| `tests/test_notification_service.py` | 读口径（未读怎么算、受众怎么解析、分页怎么稳） |
| `tests/test_notification_delivery.py` | 接线（哪个业务动作真的投递、哪个不投） |
| **本文件** | HTTP 面（**路由存在性**、状态码、信封、ID 字符串化） |

为什么 HTTP 面必须单独有一组用例
------------------------------
本项目的验收里出现过两次同一形状的缺口（`FINDING-8-01`、`FINDING-10-01`）：

> **裁判项只判服务层 ⇒ HTTP 面不存在，永远判不出来。**

服务层用例全部自己构造 `CurrentActor` 直接调服务方法，因此
"端点没挂上 / 挂错了前缀 / 被带参路径抢了匹配"这三种错，
在服务层用例里**一个都不会红**。本文件因此有两条硬性用例：

1. `TestRouteSurface` —— 把通知域的**全部** `(方法, 路径)` 逐条钉住，
   既要"必须存在"，也要"不得有清单之外的"；
2. 每个端点都发一次**真实请求**，验状态码与信封。

认证怎么解决
-----------
不构造假的 Actor，而是**真登录**（`POST /auth/login` 拿 access token）。
理由：路由级的 API 权限绑定挂在依赖上，绕过认证就等于绕过了
"绑定到底生效没有"这件事 —— 而那正是本文件要验的。

共享库的固定 ID 纪律
------------------
本文件所有 `role_code` 都带 `NOTIFYAPI` 前缀。共享 PostgreSQL 上真实库里
已经有 `SUPER_ADMIN` 等角色（`scripts/seed_init.py` 写的），
再插一个同码的会撞 `uq_roles_role_code_active` —— 那是本项目在共享库上的
已知噪声（记作"既存红"），不该由本文件制造新的。

`NOTIFICATION_MANAGE` 权限资源是**唯一例外**：它本来就该存在
（迁移 / 种子已写入），所以本文件只**复用**它，不存在时才补建。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select

from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.main import create_app
from app.models import PermissionResource
from app.models.enums import (
    NotificationCategory,
    NotificationLevel,
    PermissionResourceType,
    PermissionStatus,
)
from app.models.notification import Notification
from tests.factories import (
    link_role_permission,
    link_user_role,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

SELF_PREFIX = "/api/v1/auth"
ADMIN_PREFIX = "/api/v1/admin"

# ---- 角色 ----
ROLE_ADMIN = 69111  # 持有 NOTIFICATION_MANAGE
ROLE_PLAIN = 69112  # 什么都不持有
# ---- 用户 ----
U_ADMIN = 69201
U_PLAIN = 69202
U_OTHER = 69203
# ---- 权限资源（本文件自己的段，仅"不存在时"使用） ----
RES_NOTIFICATION_MANAGE = 69121

PASSWORD = "Notify-Passw0rd!11"

#: 通知域的全部端点（`(方法, 完整路径)`）。
#:
#: 这份清单是**契约**，不是实现摘要：增删端点都必须改它，
#: 于是"某天有人把收件箱挪进 admin 域"这类改动会立刻可见。
ROUTE_SURFACE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{SELF_PREFIX}/notifications"),
        ("GET", f"{SELF_PREFIX}/notifications/unread-count"),
        ("POST", f"{SELF_PREFIX}/notifications/read-all"),
        ("POST", f"{SELF_PREFIX}/notifications/{{notification_id}}/read"),
        ("GET", f"{ADMIN_PREFIX}/notifications/announcements"),
        ("POST", f"{ADMIN_PREFIX}/notifications/announcements"),
        ("POST", f"{ADMIN_PREFIX}/notifications/announcements/{{announcement_id}}/revoke"),
    }
)


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------
async def _manage_resource_id(session) -> int:
    """取 `NOTIFICATION_MANAGE` API 资源的 ID（**存在则复用**）。

    为什么必须复用而不是新建：`permission_resources` 上有
    `uq_permission_resources_type_code_active`（部分唯一，`deleted_at is null`），
    而该资源已由迁移与 `scripts/seed_init.py` 写进库里。
    再插一条同名同类型的行会直接撞唯一约束 —— 本项目在共享库上
    成片变红就是这个原因。这里"存在则复用"既不制造新噪声，
    也保证判权依据确实是**线上那一条**资源。
    """
    existing = (
        (
            await session.execute(
                select(PermissionResource).where(
                    PermissionResource.resource_type == PermissionResourceType.API,
                    PermissionResource.resource_code == "NOTIFICATION_MANAGE",
                    PermissionResource.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing.id
    created = await make_permission_resource(
        session,
        resource_id=RES_NOTIFICATION_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="NOTIFICATION_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/notifications/announcements",
        status=PermissionStatus.ACTIVE,
    )
    return created.id


async def _seed(session) -> None:
    await make_role(session, role_id=ROLE_ADMIN, role_code="NOTIFYAPI_ADMIN")
    await make_role(
        session, role_id=ROLE_PLAIN, role_code="NOTIFYAPI_PLAIN", data_scope=DataScope.SELF
    )
    await link_role_permission(
        session, role_id=ROLE_ADMIN, resource_id=await _manage_resource_id(session)
    )

    for user_id, username, role_id in (
        (U_ADMIN, "notifyapi-admin", ROLE_ADMIN),
        (U_PLAIN, "notifyapi-plain", ROLE_PLAIN),
        (U_OTHER, "notifyapi-other", ROLE_PLAIN),
    ):
        await make_user(
            session,
            user_id=user_id,
            username=username,
            password=PASSWORD,
            password_changed_at=utc_now(),
        )
        await link_user_role(session, user_id=user_id, role_id=role_id)


async def _push(
    session,
    *,
    user_id: int,
    title: str = "一条站内消息",
    body: str | None = "正文",
    category: NotificationCategory = NotificationCategory.SYSTEM,
    event_code: str | None = "USER_ENABLED",
    link: str | None = "/profile",
    level: NotificationLevel = NotificationLevel.INFO,
    read_at: datetime | None = None,
) -> Notification:
    """**直接写库**造一条收件箱行（HTTP 用例只验读侧与状态码）。"""
    notification = Notification(
        user_id=user_id,
        category=category,
        event_code=event_code,
        title=title,
        body=body,
        link=link,
        level=level,
        read_at=read_at,
    )
    session.add(notification)
    await session.flush()
    return notification


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """把端点的 `get_db` 指向测试会话（外层事务，结束回滚）。"""

    async def _override_get_db() -> AsyncIterator[object]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _login(api: AsyncClient, username: str) -> dict[str, str]:
    response = await api.post(
        f"{SELF_PREFIX}/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _data(response: Response) -> dict:
    return response.json()["data"]


async def _headers_for(api: AsyncClient, db_session, username: str) -> dict[str, str]:
    await _seed(db_session)
    return await _login(api, username)


# ===========================================================================
# 1. 路由面（不连库）
# ===========================================================================
class TestRouteSurface:
    """通知域的 HTTP 面必须**逐条**存在，且不得有清单之外的。

    两条断言缺一不可：
    - 少了端点 → 功能不存在，而服务层用例全绿（`FINDING-8-01` 的形状）；
    - 多了端点 → 多出来的一定是没被这份清单检查过的入口，
      而"没被检查过"在本项目里就等于"可能没有授权声明"
      （`tests/test_route_authorization_guard.py` 也拦，但两条护栏的
      口径不同：那边只看 admin 域有没有声明权限位，这边看**存不存在**）。
    """

    @staticmethod
    def _openapi_routes() -> set[tuple[str, str]]:
        spec = create_app().openapi()
        return {
            (method.upper(), path)
            for path, methods in spec.get("paths", {}).items()
            for method in methods
            if "notification" in path
        }

    def test_every_declared_route_exists(self) -> None:
        missing = ROUTE_SURFACE - self._openapi_routes()
        assert not missing, f"以下端点不存在：{sorted(missing)}"

    def test_no_undocumented_notification_route(self) -> None:
        extra = self._openapi_routes() - ROUTE_SURFACE
        assert not extra, f"通知域出现了清单之外的端点，请更新 ROUTE_SURFACE：{sorted(extra)}"

    def test_inbox_is_in_the_auth_domain_not_the_admin_domain(self) -> None:
        """收件箱必须在 `/api/v1/auth` 之下（`§32` 已登记的取舍）。

        `/api/v1/admin` 的每个端点都要绑一个 API 权限位，而收件箱是
        "我自己的消息" —— 绑权限位要么让只读用户看不到自己的消息，
        要么让权限位失去意义。这条断言把那个取舍钉在路由面上，
        否则将来"顺手挪进 admin 域"不会有任何东西变红。
        """
        inbox = {
            (method, path)
            for method, path in ROUTE_SURFACE
            if "/notifications" in path and "/announcements" not in path
        }
        assert inbox, "清单里没有收件箱端点，本用例的前提失效了"
        assert all(path.startswith(SELF_PREFIX) for _method, path in inbox)


# ===========================================================================
# 2. 收件箱：认证
# ===========================================================================
class TestSelfAccessControl:
    async def test_all_inbox_endpoints_require_authentication(self, api: AsyncClient) -> None:
        """未认证一律 401（不得只靠前端隐藏入口，`08 §10`）。"""
        for method, path in (
            ("get", f"{SELF_PREFIX}/notifications"),
            ("get", f"{SELF_PREFIX}/notifications/unread-count"),
            ("post", f"{SELF_PREFIX}/notifications/read-all"),
            ("post", f"{SELF_PREFIX}/notifications/1/read"),
        ):
            response = await getattr(api, method)(path)
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001

    async def test_inbox_needs_no_permission_bit(self, api: AsyncClient, db_session) -> None:
        """**这是本域的核心访问控制断言**：没有任何权限位的用户照样能读自己的收件箱。

        与 admin 域的端点正好相反 —— 那些端点缺权限位必须 403。
        两条断言合起来才说明"收件箱不占权限位"不是漏配而是刻意的。
        """
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        response = await api.get(f"{SELF_PREFIX}/notifications", headers=headers)
        assert response.status_code == 200, response.text

    async def test_forced_password_change_blocks_inbox(self, api: AsyncClient, db_session) -> None:
        """强制改密期必须被拦（**403**，不是 401）。

        收件箱会显示"你的口令已被重置"这类消息，若它在强制改密期可读，
        就等于给了一条绕过改密墙的信息通道。
        """
        from app.models.user import AdminUser

        await _seed(db_session)
        headers = await _login(api, "notifyapi-plain")
        user = await db_session.get(AdminUser, U_PLAIN)
        assert user is not None
        user.must_change_password = True
        await db_session.flush()

        response = await api.get(f"{SELF_PREFIX}/notifications", headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == 403001


# ===========================================================================
# 3. 收件箱：契约
# ===========================================================================
class TestInboxContract:
    async def test_envelope_and_pagination_fields(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_PLAIN, title="第一条")
        headers = await _login(api, "notifyapi-plain")

        response = await api.get(f"{SELF_PREFIX}/notifications", headers=headers)

        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        assert payload["message"] == "success"
        body = payload["data"]
        assert set(body) == {"list", "total", "unread", "pageNum", "pageSize"}
        assert body["pageNum"] == 1 and body["pageSize"] == 20
        assert body["total"] == 1 and body["unread"] == 1

    async def test_ids_are_serialized_as_strings(self, api: AsyncClient, db_session) -> None:
        """`07 §2` / `00 §6`：BIGINT 业务 ID 在 JSON 里必须是**字符串**。

        前端 TS 的 `number` 装不下 64 位整数，漏转的下场是
        `9007199254740993` 被静默变成 `...992`、点开的却不是那条消息。
        """
        await _seed(db_session)
        row = await _push(db_session, user_id=U_PLAIN)
        headers = await _login(api, "notifyapi-plain")

        item = _data(await api.get(f"{SELF_PREFIX}/notifications", headers=headers))["list"][0]

        assert item["id"] == str(row.id)
        assert isinstance(item["id"], str)

    async def test_contract_has_no_is_read_and_no_recipient(
        self, api: AsyncClient, db_session
    ) -> None:
        """两个**刻意不下发**的字段。

        - `is_read`：`read_at` 是未读的唯一真相。多一个布尔就是第二份真相。
        - `user_id`：调用方只可能是收件人本人，回显"这条属于谁"只是多一个可比对的面。
        """
        await _seed(db_session)
        await _push(db_session, user_id=U_PLAIN)
        headers = await _login(api, "notifyapi-plain")

        item = _data(await api.get(f"{SELF_PREFIX}/notifications", headers=headers))["list"][0]

        assert "is_read" not in item
        assert "user_id" not in item
        assert item["read_at"] is None

    async def test_list_is_isolated_per_user(self, api: AsyncClient, db_session) -> None:
        """别人的消息**绝不出现在我的列表里**（收件箱隔离的 HTTP 面）。"""
        await _seed(db_session)
        mine = await _push(db_session, user_id=U_PLAIN, title="我的")
        await _push(db_session, user_id=U_OTHER, title="别人的")
        headers = await _login(api, "notifyapi-plain")

        body = _data(await api.get(f"{SELF_PREFIX}/notifications", headers=headers))

        assert [item["id"] for item in body["list"]] == [str(mine.id)]
        assert body["total"] == 1

    async def test_unread_only_filter(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_PLAIN, title="已读的", read_at=utc_now())
        await _push(db_session, user_id=U_PLAIN, title="未读的")
        headers = await _login(api, "notifyapi-plain")

        body = _data(await api.get(f"{SELF_PREFIX}/notifications?unreadOnly=true", headers=headers))

        assert [item["title"] for item in body["list"]] == ["未读的"]
        assert body["total"] == 1
        # 未读数与列表同源：过滤后 unread 仍是**全部**未读数（角标口径）。
        assert body["unread"] == 1

    async def test_unread_count_endpoint(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_PLAIN)
        await _push(db_session, user_id=U_PLAIN)
        await _push(db_session, user_id=U_PLAIN, read_at=utc_now())
        headers = await _login(api, "notifyapi-plain")

        body = _data(await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=headers))

        assert body == {"unread": 2}

    async def test_invalid_pagination_is_422(self, api: AsyncClient, db_session) -> None:
        """`pageSize` 上界由 schema 拦（100），不是服务层的 400。"""
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        response = await api.get(f"{SELF_PREFIX}/notifications?pageSize=101", headers=headers)
        assert response.status_code == 422
        assert response.json()["code"] == 422001

    async def test_unknown_query_parameter_is_422(self, api: AsyncClient, db_session) -> None:
        """`extra="forbid"`：`?userId=` 这种"顺手试一下"的参数必须被拒。

        宽松解析会让越权探测看起来像一次成功请求（200 + 空列表），
        既掩盖了探测，也让真正的前端拼错参数无处暴露。
        """
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        response = await api.get(f"{SELF_PREFIX}/notifications?userId=69201", headers=headers)
        assert response.status_code == 422


class TestMarkRead:
    async def test_mark_read_flips_read_at_and_drops_the_badge(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        row = await _push(db_session, user_id=U_PLAIN)
        headers = await _login(api, "notifyapi-plain")

        response = await api.post(f"{SELF_PREFIX}/notifications/{row.id}/read", headers=headers)

        assert response.status_code == 200
        assert _data(response)["read_at"] is not None
        assert _data(
            await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=headers)
        ) == {"unread": 0}

    async def test_mark_read_is_idempotent(self, api: AsyncClient, db_session) -> None:
        """重复标记不刷新首次已读时间（`read_at` 是"什么时候读的"，不是"最后点过"）。"""
        await _seed(db_session)
        row = await _push(db_session, user_id=U_PLAIN)
        headers = await _login(api, "notifyapi-plain")
        path = f"{SELF_PREFIX}/notifications/{row.id}/read"

        first = _data(await api.post(path, headers=headers))["read_at"]
        second = _data(await api.post(path, headers=headers))["read_at"]

        assert first == second

    async def test_cannot_mark_another_users_notification(
        self, api: AsyncClient, db_session
    ) -> None:
        """**越权面**：别人的通知返回 404，不是 403。

        403 会泄露"这个 ID 上确实存在一条别人的消息"，
        而那正是枚举他人消息的第一步。三种情况（不存在 / 不是我的 / 已删除）
        必须给出**同一个**回应。
        """
        await _seed(db_session)
        theirs = await _push(db_session, user_id=U_OTHER)
        headers = await _login(api, "notifyapi-plain")

        response = await api.post(f"{SELF_PREFIX}/notifications/{theirs.id}/read", headers=headers)

        assert response.status_code == 404
        assert response.json()["code"] == 404001
        # 且对方的行**没有被改动** —— 否则"报 404 但已经写进去了"会静默越权。
        assert theirs.read_at is None

    async def test_marking_a_missing_notification_is_404(
        self, api: AsyncClient, db_session
    ) -> None:
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        response = await api.post(f"{SELF_PREFIX}/notifications/699999/read", headers=headers)
        assert response.status_code == 404
        assert response.json()["code"] == 404001

    async def test_read_all_returns_the_affected_count(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_PLAIN)
        await _push(db_session, user_id=U_PLAIN)
        await _push(db_session, user_id=U_OTHER)  # 别人的不该被算进去
        headers = await _login(api, "notifyapi-plain")

        body = _data(await api.post(f"{SELF_PREFIX}/notifications/read-all", headers=headers))

        assert body == {"updated": 2}
        assert _data(
            await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=headers)
        ) == {"unread": 0}

    async def test_read_all_is_idempotent(self, api: AsyncClient, db_session) -> None:
        """没有未读时返回 `updated=0` 而不是报错（界面可能几乎同时点两条）。"""
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        body = _data(await api.post(f"{SELF_PREFIX}/notifications/read-all", headers=headers))
        assert body == {"updated": 0}

    async def test_static_path_is_not_swallowed_by_the_parameterized_one(
        self, api: AsyncClient, db_session
    ) -> None:
        """`/notifications/read-all` 不得被 `/notifications/{id}/read` 抢走。

        Phase 8 的 `/permission-resources/tree` 被当成 int 解析成 422，
        而两个装饰器**各自都"正确"** —— 只有真实请求能发现。
        """
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        assert (
            await api.post(f"{SELF_PREFIX}/notifications/read-all", headers=headers)
        ).status_code == 200
        assert (
            await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=headers)
        ).status_code == 200


# ===========================================================================
# 4. 公告：认证与授权
# ===========================================================================
class TestAnnouncementAccessControl:
    async def test_requires_authentication(self, api: AsyncClient) -> None:
        for method, path in (
            ("get", f"{ADMIN_PREFIX}/notifications/announcements"),
            ("post", f"{ADMIN_PREFIX}/notifications/announcements"),
            ("post", f"{ADMIN_PREFIX}/notifications/announcements/1/revoke"),
        ):
            response = await getattr(api, method)(path)
            assert response.status_code == 401, path
            assert response.json()["code"] == 401001

    async def test_without_permission_bit_is_forbidden(self, api: AsyncClient, db_session) -> None:
        """缺 `NOTIFICATION_MANAGE` → 403（三个端点一致）。

        与收件箱的"无权限位照样能读自己的"对照着看：
        这一对断言才是"权限位用在了对的地方"的证明。
        """
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        assert (
            await api.get(f"{ADMIN_PREFIX}/notifications/announcements", headers=headers)
        ).status_code == 403
        assert (
            await api.post(
                f"{ADMIN_PREFIX}/notifications/announcements",
                json={"title": "无权限"},
                headers=headers,
            )
        ).status_code == 403
        assert (
            await api.post(f"{ADMIN_PREFIX}/notifications/announcements/1/revoke", headers=headers)
        ).status_code == 403


# ===========================================================================
# 5. 公告：契约
# ===========================================================================
class TestAnnouncementContract:
    async def test_publish_fans_out_and_reports_recipient_count(
        self, api: AsyncClient, db_session
    ) -> None:
        await _seed(db_session)
        headers = await _login(api, "notifyapi-admin")

        response = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": "系统维护通知", "body": "今晚 22:00 起维护", "level": "WARNING"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = _data(response)
        assert isinstance(body["announcement"]["id"], str)
        # 收件人数是"发布那一刻"的事实，因此必然 >= 本文件播种的 3 个用户。
        assert body["recipient_count"] >= 3

    async def test_request_is_echoed_by_username_not_by_id(
        self, api: AsyncClient, db_session
    ) -> None:
        """响应带 `created_by_username`、**没有** `created_by`（`FINDING-28-01` 那一类）。

        列表页要显示"谁发的"，裸雪花 ID 在界面上只是一串数字。
        """
        await _seed(db_session)
        headers = await _login(api, "notifyapi-admin")
        await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": "发布人回显"},
            headers=headers,
        )

        item = _data(await api.get(f"{ADMIN_PREFIX}/notifications/announcements", headers=headers))[
            "list"
        ][0]

        assert item["created_by_username"] == "notifyapi-admin"
        assert "created_by" not in item

    async def test_role_audience_requires_a_role_id(self, api: AsyncClient, db_session) -> None:
        """`ROLE` 却不给角色 → 400（不是 500）。库层 CHECK 是最终保证。"""
        headers = await _headers_for(api, db_session, "notifyapi-admin")
        response = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": "漏了角色", "audience_type": "ROLE"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == 400001

    async def test_all_audience_forbids_a_role_id(self, api: AsyncClient, db_session) -> None:
        """`ALL` 却给了角色 → 400（"到底发给了谁"不能有两个答案）。"""
        headers = await _headers_for(api, db_session, "notifyapi-admin")
        response = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": "矛盾受众", "audience_type": "ALL", "audience_role_id": str(ROLE_PLAIN)},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_empty_title_is_rejected(self, api: AsyncClient, db_session) -> None:
        headers = await _headers_for(api, db_session, "notifyapi-admin")
        response = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": ""},
            headers=headers,
        )
        assert response.status_code == 422

    async def test_revoke_purges_the_mailbox(self, api: AsyncClient, db_session) -> None:
        """撤回后**收件箱里那些行也必须消失**，未读数随之归零。

        只删公告定义（留下孤立的收件箱行）会让用户继续看到一条
        点不开、也查不到出处的消息。
        """
        await _seed(db_session)
        admin = await _login(api, "notifyapi-admin")
        published = _data(
            await api.post(
                f"{ADMIN_PREFIX}/notifications/announcements",
                json={"title": "待撤回的公告"},
                headers=admin,
            )
        )
        announcement_id = published["announcement"]["id"]

        plain = await _login(api, "notifyapi-plain")
        assert (
            _data(await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=plain))[
                "unread"
            ]
            == 1
        )

        revoked = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements/{announcement_id}/revoke", headers=admin
        )

        assert revoked.status_code == 200
        assert _data(revoked)["purged"] >= 1
        assert (
            _data(await api.get(f"{SELF_PREFIX}/notifications/unread-count", headers=plain))[
                "unread"
            ]
            == 0
        )

    async def test_revoking_twice_is_404(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, "notifyapi-admin")
        announcement_id = _data(
            await api.post(
                f"{ADMIN_PREFIX}/notifications/announcements",
                json={"title": "撤回两次"},
                headers=headers,
            )
        )["announcement"]["id"]
        path = f"{ADMIN_PREFIX}/notifications/announcements/{announcement_id}/revoke"

        assert (await api.post(path, headers=headers)).status_code == 200
        second = await api.post(path, headers=headers)
        assert second.status_code == 404
        assert second.json()["code"] == 404001

    async def test_revoked_announcement_leaves_the_list(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, "notifyapi-admin")
        announcement_id = _data(
            await api.post(
                f"{ADMIN_PREFIX}/notifications/announcements",
                json={"title": "撤回后不该再出现"},
                headers=headers,
            )
        )["announcement"]["id"]

        await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements/{announcement_id}/revoke", headers=headers
        )
        titles = [
            item["title"]
            for item in _data(
                await api.get(f"{ADMIN_PREFIX}/notifications/announcements", headers=headers)
            )["list"]
        ]

        assert "撤回后不该再出现" not in titles

    async def test_non_admin_cannot_publish_even_with_valid_body(
        self, api: AsyncClient, db_session
    ) -> None:
        """**授权先于业务校验**：请求体完全合法，仍然必须 403。

        若实现把判权放在参数校验之后，"合法的请求体 + 无权限"会走到写库，
        而"非法的请求体 + 无权限"会返回 400 —— 攻击者据此就能探测出
        自己在哪一道门被拦下。
        """
        headers = await _headers_for(api, db_session, "notifyapi-plain")
        response = await api.post(
            f"{ADMIN_PREFIX}/notifications/announcements",
            json={"title": "完全合法", "body": "正文", "level": "INFO", "audience_type": "ALL"},
            headers=headers,
        )
        assert response.status_code == 403
        assert response.json()["code"] == 403001


# ===========================================================================
# 6. 公告列表的分页
# ===========================================================================
class TestAnnouncementPagination:
    async def test_page_size_bound_is_enforced_by_schema(
        self, api: AsyncClient, db_session
    ) -> None:
        headers = await _headers_for(api, db_session, "notifyapi-admin")
        response = await api.get(
            f"{ADMIN_PREFIX}/notifications/announcements?pageSize=101", headers=headers
        )
        assert response.status_code == 422

    async def test_second_page_is_empty_but_total_stays(self, api: AsyncClient, db_session) -> None:
        await _seed(db_session)
        headers = await _login(api, "notifyapi-admin")
        for index in range(2):
            await api.post(
                f"{ADMIN_PREFIX}/notifications/announcements",
                json={"title": f"公告 {index}"},
                headers=headers,
            )

        body = _data(
            await api.get(
                f"{ADMIN_PREFIX}/notifications/announcements?pageNum=1&pageSize=2", headers=headers
            )
        )
        assert len(body["list"]) == 2
        assert body["total"] >= 2

        empty = _data(
            await api.get(
                f"{ADMIN_PREFIX}/notifications/announcements?pageNum=99&pageSize=2", headers=headers
            )
        )
        assert empty["list"] == []
        assert empty["total"] == body["total"]
