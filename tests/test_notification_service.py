"""站内通知服务测试（Phase 14 / `DESIGN-DECISIONS §32`）。

Spec 里没有这一域（`docs/spec/` 全 17 个文档对「消息 / 通知 / 公告」零提及），
因此本文件对照的是 `§32` 记录的三项人类裁定与随之定下的口径：

```text
1、前端页面新增站内通知，如果有消息需要展示消息角标 在右上角个人中心那个位置
```
→ 裁定：**后端真存储** + **系统事件与管理员公告都要** + **下拉面板 + 查看全部**。

裁判条目与本文件的对应关系
--------------------------
| 口径 | 用例 |
|---|---|
| 收件箱只读自己的（任何入口都不接受 user_id 参数） | `TestInboxIsolation` |
| 未读 = `read_at is null and deleted_at is null`（唯一判据） | `TestUnreadDefinition` |
| 已读幂等：重复标记不刷新首次时间 | `TestMarkRead` |
| 别人的 / 不存在的 / 已删除的 → 同一个 404 | `TestMarkRead` |
| 公告受众：ACTIVE 且未删除 | `TestAnnounceAudience` |
| ROLE 受众按**直接分配**判定，不含继承 | `TestAnnounceAudience` |
| 扇出的 N 行共用同一 `created_at`，排序必须带 `id` | `TestFanoutOrdering` |
| 撤回连同收件箱行一起消失，未读数归零 | `TestRevoke` |
| 审计记 `body_length` 而**不是**正文 | `TestAuditRecordsFactsNotBodies` |
| 系统事件只能来自目录，不允许自定义标题 | `TestSystemEventDelivery` |

HTTP 层（路由面 / 状态码 / 信封 / ID 序列化）在 `tests/test_notification_api.py`；
系统事件与业务服务的接线在 `tests/test_notification_delivery.py`。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.audit import AuditAction
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.db.base import utc_now
from app.models import AdminUser, PermissionResource
from app.models.enums import (
    AnnouncementAudience,
    NotificationCategory,
    NotificationLevel,
    PermissionResourceType,
    PermissionStatus,
    UserStatus,
)
from app.models.notification import TITLE_LENGTH, Announcement, Notification
from app.services.notification import (
    MAX_PAGE_SIZE,
    SYSTEM_EVENTS,
    NotificationService,
    NullNotificationPublisher,
    SystemEventSpec,
)
from tests.conftest import RecordingAuditRecorder
from tests.factories import (
    link_role_inheritance,
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

DEPT_ID = 61001
DEPT_OTHER = 61002

ROLE_MANAGE = 61011
ROLE_NONE = 61012
#: 公告受众测试用：被继承的角色（继承者不该出现在名单里）。
ROLE_OPS = 61013
ROLE_OPS_PARENT = 61014

RES_API_NOTIFICATION_MANAGE = 61021

U_ADMIN = 61101
U_NONE = 61102
U_OPS = 61103
U_OPS_BY_INHERITANCE = 61104
U_DISABLED = 61105

#: 一个"看起来敏感"的正文，用于钉住"审计只记长度、不记正文"。
SECRET_LIKE_BODY = "临时口令 Tmp-9f21c7 请勿外传"


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------
async def _manage_resource_id(session) -> int:
    """取 `NOTIFICATION_MANAGE` 的 API 资源 ID（存在则复用，不存在才建）。

    ⚠️ 这条"存在则复用"不是洁癖，是本项目共享库上一个反复出现的坑：
    `permission_resources` 上有 `uq_permission_resources_type_code_active`
    的部分唯一约束，而 `NOTIFICATION_MANAGE` 这个资源**已经由**
    迁移 / `scripts/seed_init.py` 写进库里。再 `make_permission_resource`
    建一条同名同类型的行会直接撞唯一约束 ——
    `tests/test_user_service.py` / `tests/test_dict_service.py` 在共享库上
    成片变红就是这个原因（本项目记作"既存红"）。

    这里改成本文件自己的资源 ID 段（`RES_API_NOTIFICATION_MANAGE`）只在
    "库里没有"时才用，既不改动别人的数据，也不再制造新的既存红。
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
        resource_id=RES_API_NOTIFICATION_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="NOTIFICATION_MANAGE",
        api_method="GET",
        api_path="/api/v1/admin/notifications/announcements",
        status=PermissionStatus.ACTIVE,
    )
    return created.id


async def _seed(session) -> None:
    """两个部门、四个角色、五个用户。

    `U_OPS_BY_INHERITANCE` **通过继承**拿到 `ROLE_OPS`：它是"权限上算"
    但不是"组织上属于"的典型样本，ROLE 受众必须把它排除在外。
    """
    await make_department(session, department_id=DEPT_ID, department_code="NOTIFY-DEPT")
    await make_department(session, department_id=DEPT_OTHER, department_code="NOTIFY-OTHER")

    await make_role(session, role_id=ROLE_MANAGE, role_code="NOTIFY_ADMIN")
    await make_role(session, role_id=ROLE_NONE, role_code="NOTIFY_NONE")
    await make_role(session, role_id=ROLE_OPS, role_code="NOTIFY_OPS")
    await make_role(session, role_id=ROLE_OPS_PARENT, role_code="NOTIFY_OPS_PARENT")

    await link_role_permission(
        session, role_id=ROLE_MANAGE, resource_id=await _manage_resource_id(session)
    )

    # `U_OPS_BY_INHERITANCE` 直接持有父角色，通过继承拿到 `ROLE_OPS` 的权限。
    await link_role_inheritance(session, parent_role_id=ROLE_OPS, child_role_id=ROLE_OPS_PARENT)

    for user_id, username, role_id, status in (
        (U_ADMIN, "notify-admin", ROLE_MANAGE, UserStatus.ACTIVE),
        (U_NONE, "notify-none", ROLE_NONE, UserStatus.ACTIVE),
        (U_OPS, "notify-ops", ROLE_OPS, UserStatus.ACTIVE),
        (U_OPS_BY_INHERITANCE, "notify-ops-inherited", ROLE_OPS_PARENT, UserStatus.ACTIVE),
        (U_DISABLED, "notify-disabled", ROLE_NONE, UserStatus.DISABLED),
    ):
        await make_user(
            session,
            user_id=user_id,
            username=username,
            department_id=DEPT_ID,
            status=status,
        )
        await link_user_role(session, user_id=user_id, role_id=role_id)


def _admin() -> CurrentActor:
    return CurrentActor(
        user_id=U_ADMIN,
        username="notify-admin",
        role_codes=frozenset({"NOTIFY_ADMIN"}),
        data_scope=DataScope.ALL,
        ip="10.3.0.1",
        user_agent="pytest-notify/1.0",
    )


def _none() -> CurrentActor:
    return CurrentActor(
        user_id=U_NONE,
        username="notify-none",
        role_codes=frozenset({"NOTIFY_NONE"}),
        data_scope=DataScope.SELF,
        ip="10.3.0.2",
        user_agent="pytest-notify/1.0",
    )


def _ops() -> CurrentActor:
    return CurrentActor(
        user_id=U_OPS,
        username="notify-ops",
        role_codes=frozenset({"NOTIFY_OPS"}),
        data_scope=DataScope.SELF,
        ip="10.3.0.3",
        user_agent="pytest-notify/1.0",
    )


def _super() -> CurrentActor:
    return CurrentActor(
        user_id=U_NONE,
        username="notify-none",
        role_codes=frozenset({SUPER_ADMIN_ROLE_CODE}),
        data_scope=DataScope.ALL,
        ip="10.3.0.4",
        user_agent="pytest-notify/1.0",
    )


def _service(session, *, audit: RecordingAuditRecorder | None = None) -> NotificationService:
    return NotificationService(session, audit=audit)


async def _push(
    session,
    *,
    user_id: int,
    title: str = "一条消息",
    body: str | None = None,
    category: NotificationCategory = NotificationCategory.SYSTEM,
    event_code: str | None = "SESSION_SUPERSEDED",
    link: str | None = "/profile",
    level: NotificationLevel = NotificationLevel.INFO,
    read_at: datetime | None = None,
    deleted_at: datetime | None = None,
    created_at: datetime | None = None,
    announcement_id: int | None = None,
) -> Notification:
    """**直接写库**构造一条收件箱行。

    刻意绕开服务层：本文件要验的是读取侧的口径（未读怎么算、谁能读到），
    而"库里已经存在一条已读 / 已删除的行"恰恰是读取侧必须处理的状态。
    """
    notification = Notification(
        user_id=user_id,
        category=category,
        event_code=event_code,
        announcement_id=announcement_id,
        title=title,
        body=body,
        link=link,
        level=level,
        read_at=read_at,
        deleted_at=deleted_at,
        **({} if created_at is None else {"created_at": created_at}),
    )
    session.add(notification)
    await session.flush()
    return notification


# ---------------------------------------------------------------------------
# 收件箱隔离
# ---------------------------------------------------------------------------
class TestInboxIsolation:
    """收件箱是"我的"数据：任何入口都不接受收件人参数。"""

    async def test_list_returns_only_my_rows(self, db_session) -> None:
        await _seed(db_session)
        mine = await _push(db_session, user_id=U_OPS, title="我的")
        await _push(db_session, user_id=U_NONE, title="别人的")
        await _push(db_session, user_id=U_ADMIN, title="别人的2")

        page = await _service(db_session).list_mine(actor=_ops())

        assert [row.id for row in page.items] == [mine.id]
        assert page.total == 1

    async def test_list_has_no_recipient_parameter(self) -> None:
        """签名里**不得**出现"按 user_id 查收件箱"的参数。

        这条断言看起来像在测签名，实际在守一条口径：一个收件人参数
        就是一条越权读入口，而它没有任何正当用途（管理端要看的是公告）。
        """
        import inspect

        signature = inspect.signature(NotificationService.list_mine)
        assert "user_id" not in signature.parameters
        assert "recipient_user_id" not in signature.parameters

    async def test_unread_count_is_per_user(self, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_OPS)
        await _push(db_session, user_id=U_OPS)
        await _push(db_session, user_id=U_NONE)

        service = _service(db_session)
        assert await service.unread_count(actor=_ops()) == 2
        assert await service.unread_count(actor=_none()) == 1
        assert await service.unread_count(actor=_admin()) == 0

    async def test_deleted_rows_are_invisible(self, db_session) -> None:
        """逻辑删除（撤回公告 / 保留期清理）后立刻从收件箱消失。"""
        await _seed(db_session)
        await _push(db_session, user_id=U_OPS, title="在")
        await _push(db_session, user_id=U_OPS, title="没了", deleted_at=utc_now())

        page = await _service(db_session).list_mine(actor=_ops())

        assert [row.title for row in page.items] == ["在"]
        assert await _service(db_session).unread_count(actor=_ops()) == 1


# ---------------------------------------------------------------------------
# 未读的定义
# ---------------------------------------------------------------------------
class TestUnreadDefinition:
    """未读的唯一判据是 `read_at is null and deleted_at is null`。

    刻意**不**下发 `is_read` 布尔：`read_at` 比布尔多一个"什么时候读的"，
    两个字段不一致时无人能判谁对。
    """

    async def test_read_rows_leave_the_badge_but_stay_in_the_list(self, db_session) -> None:
        await _seed(db_session)
        unread = await _push(db_session, user_id=U_OPS, title="未读")
        await _push(db_session, user_id=U_OPS, title="已读", read_at=utc_now())

        service = _service(db_session)
        page = await service.list_mine(actor=_ops())
        assert {row.id for row in page.items} >= {unread.id}
        assert len(page.items) == 2
        # 角标只算未读，但列表仍然给出全部 —— "读过的消息"要能回看。
        assert page.unread == 1
        assert await service.unread_count(actor=_ops()) == 1

    async def test_unread_only_filter(self, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_OPS, title="未读")
        await _push(db_session, user_id=U_OPS, title="已读", read_at=utc_now())

        page = await _service(db_session).list_mine(actor=_ops(), unread_only=True)

        assert [row.title for row in page.items] == ["未读"]
        # ⚠️ `total` 随筛选变，`unread` **不随**筛选变：
        # 角标表示"一共有多少没看"，与列表当前筛了什么都无关。
        assert page.total == 1
        assert page.unread == 1

    async def test_category_filter(self, db_session) -> None:
        await _seed(db_session)
        announcement = await _make_announcement(db_session)
        await _push(db_session, user_id=U_OPS, title="系统", category=NotificationCategory.SYSTEM)
        await _push(
            db_session,
            user_id=U_OPS,
            title="公告",
            category=NotificationCategory.ANNOUNCEMENT,
            event_code=None,
            announcement_id=announcement.id,
        )

        page = await _service(db_session).list_mine(
            actor=_ops(), category=NotificationCategory.ANNOUNCEMENT
        )

        assert [row.title for row in page.items] == ["公告"]
        assert page.total == 1


# ---------------------------------------------------------------------------
# 标记已读
# ---------------------------------------------------------------------------
class TestMarkRead:
    async def test_marks_only_my_row_and_records_the_first_time(self, db_session) -> None:
        await _seed(db_session)
        row = await _push(db_session, user_id=U_OPS)
        assert row.read_at is None

        marked = await _service(db_session).mark_read(actor=_ops(), notification_id=row.id)

        assert marked.read_at is not None
        first_read_at = marked.read_at

        # 幂等：第二次标记**不得**刷新时间。视图层每次打开面板都会重放一次
        # 标记请求，若每次都刷新，"这条是什么时候读的"这个事实就没了。
        again = await _service(db_session).mark_read(actor=_ops(), notification_id=row.id)
        assert again.read_at == first_read_at

    async def test_other_users_row_is_404_not_403(self, db_session) -> None:
        """区分"不存在"与"存在但不是你的"等于泄漏他人消息 ID 的存在性。"""
        await _seed(db_session)
        foreign = await _push(db_session, user_id=U_NONE)

        with pytest.raises(NotFoundError):
            await _service(db_session).mark_read(actor=_ops(), notification_id=foreign.id)

    async def test_missing_and_deleted_are_the_same_404(self, db_session) -> None:
        await _seed(db_session)
        deleted = await _push(db_session, user_id=U_OPS, deleted_at=utc_now())

        service = _service(db_session)
        with pytest.raises(NotFoundError):
            await service.mark_read(actor=_ops(), notification_id=999_999_999)
        with pytest.raises(NotFoundError):
            await service.mark_read(actor=_ops(), notification_id=deleted.id)

    async def test_mark_all_read_counts_only_mine_and_unread(self, db_session) -> None:
        await _seed(db_session)
        await _push(db_session, user_id=U_OPS)
        await _push(db_session, user_id=U_OPS)
        await _push(db_session, user_id=U_OPS, read_at=utc_now())
        await _push(db_session, user_id=U_OPS, deleted_at=utc_now())
        other = await _push(db_session, user_id=U_NONE)

        updated = await _service(db_session).mark_all_read(actor=_ops())

        assert updated == 2
        service = _service(db_session)
        assert await service.unread_count(actor=_ops()) == 0
        # 别人的那一条不能被顺带标记 —— 跨用户的 `update` 是这里最危险的写法。
        assert await service.unread_count(actor=_none()) == 1
        refreshed = await db_session.get(Notification, other.id)
        assert refreshed is not None and refreshed.read_at is None

    async def test_mark_all_read_with_no_unread_returns_zero(self, db_session) -> None:
        await _seed(db_session)
        assert await _service(db_session).mark_all_read(actor=_ops()) == 0


# ---------------------------------------------------------------------------
# 分页协议
# ---------------------------------------------------------------------------
class TestPagination:
    async def test_rejects_out_of_range_page(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)

        with pytest.raises(BadRequestError):
            await service.list_mine(actor=_ops(), page_num=0)
        with pytest.raises(BadRequestError):
            await service.list_mine(actor=_ops(), page_size=0)
        with pytest.raises(BadRequestError):
            await service.list_mine(actor=_ops(), page_size=MAX_PAGE_SIZE + 1)

    async def test_page_metadata_is_echoed_back(self, db_session) -> None:
        await _seed(db_session)
        for index in range(3):
            await _push(db_session, user_id=U_OPS, title=f"第{index}条")

        page = await _service(db_session).list_mine(actor=_ops(), page_num=2, page_size=2)

        assert page.page_num == 2
        assert page.page_size == 2
        assert page.total == 3
        # 第 2 页只有 1 条（共 3 条、每页 2 条）。
        assert len(page.items) == 1


# ---------------------------------------------------------------------------
# 公告：受众解析
# ---------------------------------------------------------------------------
class TestAnnounceAudience:
    """受众解析的两条口径。

    ⚠️ 这里刻意**不**断言"发给了 N 个人"这种精确数字：`ALL` 会在真实库上
    解析出**所有** ACTIVE 未删除用户（种子数据 + 其它用例留下的人），
    而 `db_session` 跑在一个会被回滚的外层事务里 ——
    数字取决于共享库里当前有什么，是一个会随机变红的断言。
    改为断言**成员关系**（该在的在、不该在的不在）与
    "返回的条数 == 真实写出的行数"，这两条在任何库状态下都成立，
    而且正好是这两条口径的正面/反面。
    """

    async def test_all_reaches_only_active_undeleted_users(self, db_session) -> None:
        """被禁用的用户收不到公告：他登录不进来，只会让"已送达 N 人"虚高。"""
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_admin(),
            title="全员公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        recipients = set(await _recipient_ids(db_session, result.announcement.id))
        assert {U_ADMIN, U_NONE, U_OPS, U_OPS_BY_INHERITANCE} <= recipients
        assert U_DISABLED not in recipients
        # 声明的收件人数必须与真实写出的行数一致 —— 它是给人看的数字，
        # 与库里的行数不一致就是一次静默的谎报。
        assert result.announcement.recipient_count == len(recipients)

    async def test_role_audience_excludes_inherited_members(self, db_session) -> None:
        """继承是**权限**关系，不是组织归属。

        `U_OPS_BY_INHERITANCE` 通过继承拿到了 `ROLE_OPS` 的权限，
        但它不是 `ROLE_OPS` 的人 —— "他继承了这个角色的权限"不等于
        "他是这个角色的人"。若将来裁定要算，改动只在一处
        （`resolve_audience_user_ids`），届时这条用例必须一起改。
        """
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_admin(),
            title="运维公告",
            body=None,
            level=NotificationLevel.WARNING,
            audience_type=AnnouncementAudience.ROLE,
            audience_role_id=ROLE_OPS,
        )

        recipients = await _recipient_ids(db_session, result.announcement.id)
        assert recipients == [U_OPS]
        assert U_OPS_BY_INHERITANCE not in recipients
        assert result.recipient_count == 1

    async def test_role_audience_skips_disabled_members(self, db_session) -> None:
        await _seed(db_session)
        user = await db_session.get(AdminUser, U_OPS)
        assert user is not None
        user.status = UserStatus.DISABLED
        await db_session.flush()

        result = await _service(db_session).announce(
            actor=_admin(),
            title="运维公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ROLE,
            audience_role_id=ROLE_OPS,
        )

        # "发给了 0 人"是合法状态（没人可发），不是错误 ——
        # 它必须能发生并被如实记录，否则发布者会以为消息已经送达。
        assert result.recipient_count == 0
        assert await _rows_of_announcement(db_session, result.announcement.id) == []

    async def test_audience_must_be_self_consistent(self, db_session) -> None:
        """ROLE 没给角色 / ALL 给了角色 → 400（可读报错，而不是 500）。"""
        await _seed(db_session)
        service = _service(db_session)

        with pytest.raises(BadRequestError):
            await service.announce(
                actor=_admin(),
                title="t",
                body=None,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ROLE,
                audience_role_id=None,
            )
        with pytest.raises(BadRequestError):
            await service.announce(
                actor=_admin(),
                title="t",
                body=None,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=ROLE_OPS,
            )

    async def test_requires_manage_permission(self, db_session) -> None:
        await _seed(db_session)

        with pytest.raises(PermissionDeniedError):
            await _service(db_session).announce(
                actor=_none(),
                title="越权公告",
                body=None,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=None,
            )

    async def test_super_admin_can_manage(self, db_session) -> None:
        """超管不需要显式授权那个 API 权限位（`08 §6` 的超管语义）。"""
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_super(),
            title="超管公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        recipients = await _recipient_ids(db_session, result.announcement.id)
        assert U_OPS in recipients


# ---------------------------------------------------------------------------
# 公告：内容校验
# ---------------------------------------------------------------------------
class TestAnnounceValidation:
    async def test_rejects_blank_title(self, db_session) -> None:
        await _seed(db_session)

        with pytest.raises(BadRequestError):
            await _service(db_session).announce(
                actor=_admin(),
                title="   ",
                body=None,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=None,
            )

    async def test_title_is_stripped_before_persisting(self, db_session) -> None:
        """标题首尾空格必须在这里去掉，而不是指望调用方。

        `UQ` 之类的约束不会因此报错，但列表里"系统维护通知"与
        "系统维护通知 "看起来一样、按名查找时却是两条。
        """
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_admin(),
            title="  系统维护通知  ",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        assert result.announcement.title == "系统维护通知"

    async def test_rejects_over_long_title_and_body(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)

        with pytest.raises(BadRequestError):
            await service.announce(
                actor=_admin(),
                title="长" * 201,
                body=None,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=None,
            )
        with pytest.raises(BadRequestError):
            await service.announce(
                actor=_admin(),
                title="标题",
                body="长" * 4001,
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=None,
            )

    async def test_fanout_links_to_the_message_center(self, db_session) -> None:
        """扇出的 `link` 是**前端路由**（消息中心），不是后端 API 路径。

        写错不会报错 —— 只会让人点了公告之后落到 404。
        """
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_admin(),
            title="公告",
            body="正文",
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        rows = await _rows_of_announcement(db_session, result.announcement.id)
        assert rows, "应当至少扇出一条收件箱行"
        assert {row.link for row in rows} == {"/notifications"}
        assert {row.category for row in rows} == {NotificationCategory.ANNOUNCEMENT}
        assert {row.title for row in rows} == {"公告"}
        # 公告行**不带** `event_code`：那是系统消息的字段，库层有 CHECK 约束。
        assert {row.event_code for row in rows} == {None}


# ---------------------------------------------------------------------------
# 扇出排序
# ---------------------------------------------------------------------------
class TestFanoutOrdering:
    async def test_all_rows_share_one_published_at(self, db_session) -> None:
        """扇出的 N 行共用同一个 `created_at`。

        刻意如此：它们确实是同一时刻发出的。代价是只按时间排序不构成全序，
        因此读路径必须补 `id desc`（下一条用例）。
        """
        await _seed(db_session)

        result = await _service(db_session).announce(
            actor=_admin(),
            title="公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        rows = await _rows_of_announcement(db_session, result.announcement.id)
        assert len({row.created_at for row in rows}) == 1

    async def test_paging_is_stable_across_pages(self, db_session) -> None:
        """分页不得出现"第 2 页又出现第 1 页看过的那条"。

        ⚠️ 这条用例**证明不了** `id` 兜底存在：`_push` 逐条写库，
        时间戳（微秒）各不相同，于是"只按 `created_at desc` 排序"
        在这里恰好也是一个全序。真正需要 `id` 的是**同刻**的行 ——
        那正是扇出的形状，由下一条用例 `test_ties_use_id_not_heap_order` 守。
        """
        await _seed(db_session)
        for index in range(5):
            await _push(db_session, user_id=U_OPS, title=f"第{index}条")

        service = _service(db_session)
        first = await service.list_mine(actor=_ops(), page_num=1, page_size=2)
        second = await service.list_mine(actor=_ops(), page_num=2, page_size=2)
        third = await service.list_mine(actor=_ops(), page_num=3, page_size=2)

        ids = [row.id for row in (*first.items, *second.items, *third.items)]
        assert len(ids) == 5
        assert len(set(ids)) == 5, f"翻页出现重复行：{ids}"
        # 全序是"新的在前"：id 必须严格递减（Snowflake 单调递增）。
        assert ids == sorted(ids, reverse=True)

    async def test_ties_use_id_not_heap_order(self, db_session) -> None:
        """同 `created_at` 的行必须按 `id` 排，**不能**听天由命。

        这是 `id` 兜底唯一的直接证据。要让"缺 `id`"真的出错，
        必须把"数据库碰巧给出的顺序"和"id 顺序"**错开**：

        1. 写 5 条 `created_at` **完全相同**的行（扇出的形状）；
        2. 把 `id` **最小**的那条 UPDATE 一次 —— MVCC 会把新元组版本
           追加到页尾，于是**堆序 ≠ id 序**（堆里是 2,3,4,5,1）；
        3. 只按 `created_at desc` 排序时，两种最可能的计划都会把它读成
           `1,5,4,3,2`（反向索引扫描）或 `2,3,4,5,1`（顺序扫描），
           两种都不是"严格递减的 id"，断言立刻失败。

        为什么不能只靠上一条用例：那里的时间戳互不相同，
        没有并列就没有排序键的第二次比较，"补不补 id"完全观察不到。
        """
        await _seed(db_session)
        shared = utc_now()
        rows = [
            await _push(db_session, user_id=U_OPS, title=f"同刻 {index}", created_at=shared)
            for index in range(5)
        ]
        assert len({row.created_at for row in rows}) == 1, "前提失效：这五行必须同刻"

        smallest = min(rows, key=lambda row: row.id)
        smallest.title = f"{smallest.title}（被改过）"
        await db_session.flush()

        page = await _service(db_session).list_mine(actor=_ops(), page_num=1, page_size=10)
        ids = [row.id for row in page.items]

        assert len(ids) == 5
        assert ids == sorted(ids, reverse=True), f"并列时没有按 id 兜底：{ids}"


# ---------------------------------------------------------------------------
# 撤回
# ---------------------------------------------------------------------------
class TestRevoke:
    async def test_revoke_hides_announcement_and_purges_inboxes(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        result = await service.announce(
            actor=_admin(),
            title="误发的公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        purged = await service.revoke_announcement(
            actor=_admin(), announcement_id=result.announcement.id
        )

        assert purged == result.recipient_count
        # 公告不再出现在列表里。
        page = await service.list_announcements(actor=_admin())
        assert result.announcement.id not in {item.id for item in page.items}
        # 扇出的每一行都被逻辑删除；服务层的读路径因此看不到它们。
        rows = await _rows_of_announcement(db_session, result.announcement.id)
        assert rows, "扇出的行应当仍在库里（逻辑删除，不是物理删除）"
        assert all(row.deleted_at is not None for row in rows)
        assert await service.unread_count(actor=_ops()) == 0
        inbox = await service.list_mine(actor=_ops())
        assert all(row.announcement_id != result.announcement.id for row in inbox.items)

    async def test_double_revoke_is_404(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        result = await service.announce(
            actor=_admin(),
            title="公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        await service.revoke_announcement(actor=_admin(), announcement_id=result.announcement.id)
        with pytest.raises(NotFoundError):
            await service.revoke_announcement(
                actor=_admin(), announcement_id=result.announcement.id
            )

    async def test_revoke_unknown_is_404(self, db_session) -> None:
        await _seed(db_session)

        with pytest.raises(NotFoundError):
            await _service(db_session).revoke_announcement(
                actor=_admin(), announcement_id=999_999_999
            )

    async def test_revoke_requires_manage_permission(self, db_session) -> None:
        await _seed(db_session)

        with pytest.raises(PermissionDeniedError):
            await _service(db_session).revoke_announcement(actor=_ops(), announcement_id=1)


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
class TestAuditRecordsFactsNotBodies:
    """审计 append-only 保留 2 年，写进去撤不回来。

    公告的发布 / 撤回是治理动作，必须留痕；但**正文不进审计**，
    理由与系统参数的"审计不记值"完全相同（`DESIGN-DECISIONS §13`）。
    """

    async def test_announce_audit_has_length_not_body(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()

        await _service(db_session, audit=recorder).announce(
            actor=_admin(),
            title="公告",
            body=SECRET_LIKE_BODY,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        event = recorder.find(AuditAction.NOTIFICATION_ANNOUNCE)
        assert event is not None
        after = event.after_data
        assert after["body_length"] == len(SECRET_LIKE_BODY)
        # 整条审计事件（含 before/after）里都不得出现正文内容。
        assert SECRET_LIKE_BODY not in str(after)
        assert "body" not in after

    async def test_revoke_audit_records_purged_count(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)
        result = await service.announce(
            actor=_admin(),
            title="公告",
            body=None,
            level=NotificationLevel.INFO,
            audience_type=AnnouncementAudience.ALL,
            audience_role_id=None,
        )

        await service.revoke_announcement(actor=_admin(), announcement_id=result.announcement.id)

        event = recorder.find(AuditAction.NOTIFICATION_REVOKE)
        assert event is not None
        assert event.after_data["purged"] == result.recipient_count
        assert event.before_data["title"] == "公告"

    async def test_system_messages_are_not_audited(self, db_session) -> None:
        """系统消息由治理动作派生，而那个动作已经被审计了。

        逐条记审计只会让审计表里一半是"系统给人发了条消息"。
        """
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        await service.publish_system_event(
            recipient_user_id=U_OPS,
            event=SYSTEM_EVENTS["USER_DISABLED"],
            body="账号已被禁用。",
        )

        assert recorder.events == []

    async def test_reading_my_inbox_is_not_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)
        row = await _push(db_session, user_id=U_OPS)

        await service.list_mine(actor=_ops())
        await service.unread_count(actor=_ops())
        await service.mark_read(actor=_ops(), notification_id=row.id)
        await service.mark_all_read(actor=_ops())

        assert recorder.events == []


# ---------------------------------------------------------------------------
# 系统事件投递
# ---------------------------------------------------------------------------
class TestSystemEventDelivery:
    async def test_writes_a_system_row_with_catalog_fields(self, db_session) -> None:
        await _seed(db_session)
        spec = SYSTEM_EVENTS["SESSION_SUPERSEDED"]

        row = await _service(db_session).publish_system_event(
            recipient_user_id=U_OPS,
            event=spec,
            body="同一个账号在新位置登录。",
        )

        assert row is not None
        assert row.user_id == U_OPS
        assert row.category == NotificationCategory.SYSTEM
        assert row.event_code == spec.code
        assert row.title == spec.title
        assert row.link == spec.link
        assert row.level == spec.level
        assert row.read_at is None
        # 系统消息**不带** `announcement_id`：库层 CHECK 约束要求
        # `(category='ANNOUNCEMENT') = (announcement_id IS NOT NULL)`。
        assert row.announcement_id is None

    async def test_catalog_keys_match_codes(self) -> None:
        """目录的键必须与 `code` 一致 —— 不一致时按事件码查会 KeyError。"""
        for key, spec in SYSTEM_EVENTS.items():
            assert key == spec.code

    async def test_every_event_has_a_title_and_a_link_prefix(self) -> None:
        for spec in SYSTEM_EVENTS.values():
            assert spec.title.strip() != ""
            if spec.link is not None:
                assert spec.link.startswith("/"), spec.code

    async def test_null_publisher_has_no_side_effect(self) -> None:
        """`NullNotificationPublisher` 不写任何东西，且签名与端口一致。"""
        publisher = NullNotificationPublisher()

        result = await publisher.publish_system_event(
            recipient_user_id=1, event=SYSTEM_EVENTS["USER_ENABLED"], body=None
        )

        assert result is None

    async def test_title_is_truncated_but_body_is_not(self, db_session) -> None:
        """标题按 `TITLE_LENGTH` 截断，正文**不截断**。

        两者不对称是刻意的：标题取自 `SYSTEM_EVENTS` 目录里的固定文案，
        截断是安全的（截掉的是写错的多余部分）；正文由调用点带着上下文给出，
        静默截断会得到一句说到一半的话，比报错更糟。
        因此正文的长度责任在调用点，库层也不设 VARCHAR 上限。
        """
        await _seed(db_session)
        long_title = "长" * (TITLE_LENGTH + 50)
        spec = SystemEventSpec(
            code="PROBE",
            title=long_title,
            link=None,
            level=NotificationLevel.INFO,
        )

        row = await _service(db_session).publish_system_event(
            recipient_user_id=U_OPS, event=spec, body="正文" * 20
        )

        assert row is not None
        assert len(row.title) == TITLE_LENGTH
        assert row.title == long_title[:TITLE_LENGTH]
        assert row.body == "正文" * 20
        # `link=None` 的事件不写跳转（而不是写空串）：空串在前端是
        # "可跳转但目标为空"，会让点击变成一次无效导航。
        assert row.link is None


# ---------------------------------------------------------------------------
# 库层约束（服务层预校验之外的最后一道门）
# ---------------------------------------------------------------------------
class TestDatabaseConstraints:
    """服务层预校验只负责"可读报错"，最终保证在数据库上。

    用**保存点**把失败限制在自己的作用域里（照抄 `tests/test_dict_service.py`
    的做法）：直接让外层的 `db_session` 失败会让夹具回滚时抛出
    `SAWarning: transaction already deassociated from connection`，
    一条与用例无关的噪声混进整套输出。
    """

    async def test_announcement_row_rejects_role_without_role_id(self, db_session) -> None:
        await _seed(db_session)
        nested = await db_session.begin_nested()
        db_session.add(
            Announcement(
                title="自相矛盾的公告",
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ROLE,
                audience_role_id=None,
                recipient_count=0,
                created_by_username="notify-admin",
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()

    async def test_announcement_row_rejects_all_with_a_role_id(self, db_session) -> None:
        """`ALL + 角色` 同样非法：它会让"到底发给了谁"有两个答案。"""
        await _seed(db_session)
        nested = await db_session.begin_nested()
        db_session.add(
            Announcement(
                title="自相矛盾的公告",
                level=NotificationLevel.INFO,
                audience_type=AnnouncementAudience.ALL,
                audience_role_id=ROLE_OPS,
                recipient_count=0,
                created_by_username="notify-admin",
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()

    async def test_notification_row_rejects_announcement_without_source(self, db_session) -> None:
        """公告行必须有来源公告，否则这行永远无法被撤回（一条悬挂的通知）。"""
        await _seed(db_session)
        nested = await db_session.begin_nested()
        db_session.add(
            Notification(
                user_id=U_OPS,
                category=NotificationCategory.ANNOUNCEMENT,
                event_code=None,
                announcement_id=None,
                title="没有出处的公告",
                level=NotificationLevel.INFO,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()

    async def test_notification_row_rejects_system_without_event_code(self, db_session) -> None:
        await _seed(db_session)
        nested = await db_session.begin_nested()
        db_session.add(
            Notification(
                user_id=U_OPS,
                category=NotificationCategory.SYSTEM,
                event_code=None,
                announcement_id=None,
                title="没有事件的系统消息",
                level=NotificationLevel.INFO,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()

    async def test_notification_row_rejects_unknown_level(self, db_session) -> None:
        """枚举列是 VARCHAR + CHECK，非法取值在库层就进不去。

        `execute()` 会立刻把这条 INSERT 送下去（autobegin 之后就是真实往返），
        所以异常在 `execute` 处就抛，而不是等到 `flush()` —— 断言包住
        `execute` 而不是 `flush`，否则失败原因会是"异常类型对但抛得太早"。
        """
        await _seed(db_session)
        nested = await db_session.begin_nested()
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into notifications "
                    "(id, user_id, category, event_code, title, level, created_at, updated_at) "
                    "values (:id, :user_id, 'SYSTEM', 'PROBE', 't', 'NOT_A_LEVEL', now(), now())"
                ),
                {"id": 619999001, "user_id": U_OPS},
            )
        await nested.rollback()


# ---------------------------------------------------------------------------
# 库结构（迁移产物）
# ---------------------------------------------------------------------------
class TestPersistedSchema:
    """迁移 `phase14_notifications` 的产物必须真的落在库里。

    服务层预校验只负责"可读报错"，最终保证在数据库上 —— 而"约束到底建了没有"
    是任何服务层用例都验不出来的（它在 Python 里拦住了一切非法输入）。
    """

    async def test_check_constraints_exist(self, db_session) -> None:
        names = set(
            (
                await db_session.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN (to_regclass('notifications'), "
                        "to_regclass('announcements')) "
                        "AND contype = 'c'"
                    )
                )
            )
            .scalars()
            .all()
        )
        for expected in (
            # `enum_type(native_enum=False)` 生成的是 VARCHAR + CHECK，
            # 约束名由 naming_convention 拼成 `ck_<表>_<列名>`。
            "ck_notifications_category",
            "ck_notifications_level",
            "ck_announcements_audience_type",
            "ck_announcements_level",
            "ck_notifications_announcement_link_consistent",
            "ck_notifications_event_code_consistent",
            "ck_announcements_audience_role_consistent",
        ):
            assert expected in names, f"缺少 CHECK 约束 {expected}；实际：{sorted(names)}"

    async def test_partial_indexes_exist(self, db_session) -> None:
        """未读数走**部分索引**：索引体量只与未读量成正比，而不是总量。"""
        names = set(
            (
                await db_session.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename IN ('notifications', 'announcements')"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ix_notifications_user_unread_active" in names
        assert "ix_notifications_user_created_active" in names

    async def test_unread_index_is_partial(self, db_session) -> None:
        definition = (
            await db_session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_notifications_user_unread_active'"
                )
            )
        ).scalar_one_or_none()
        assert definition is not None
        normalized = definition.upper()
        assert "WHERE" in normalized
        # 两个条件都要在索引谓词里：只索引"未读"而不排除已删除行，
        # 撤回公告留下的行会永远占着索引。
        assert "READ_AT IS NULL" in normalized
        assert "DELETED_AT IS NULL" in normalized


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
async def _rows_of_announcement(session, announcement_id: int) -> list[Notification]:
    stmt = select(Notification).where(Notification.announcement_id == announcement_id)
    return list((await session.execute(stmt)).scalars().all())


async def _recipient_ids(session, announcement_id: int) -> list[int]:
    return sorted(row.user_id for row in await _rows_of_announcement(session, announcement_id))


async def _make_announcement(session, *, title: str = "公告") -> Announcement:
    """**直接写库**造一条公告定义（给需要真实 `announcement_id` 的用例用）。

    收件箱行的 `announcement_id` 是指向本表的**外键**，
    所以"随手写一个 999001"会在 flush 时撞外键约束 —— 必须先有真行。
    """
    announcement = Announcement(
        title=title,
        level=NotificationLevel.INFO,
        audience_type=AnnouncementAudience.ALL,
        recipient_count=0,
        created_by_username="notify-admin",
    )
    session.add(announcement)
    await session.flush()
    return announcement
