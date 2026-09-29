"""站内通知服务 —— `DESIGN-DECISIONS §32`。

Frozen / 已裁定依据
------------------
`docs/spec/` 全 17 个文档对「消息 / 通知 / 公告」零提及，本域整体属
**技术推导**，由人类裁定后落地（`§32`，2026-09-29）：

```text
1、前端页面新增站内通知，如果有消息需要展示消息角标 在右上角个人中心那个位置
```

三项裁定：**后端真存储** + **系统事件与管理员公告都要** + **下拉面板 + 查看全部**。

两个域，一个服务
==============
本服务同时承载两种调用者，但**权限形状完全不同**：

| | 自助（收件箱） | 管理（公告） |
|---|---|---|
| 调用者 | 任何已认证用户 | 需 `NOTIFICATION_MANAGE` |
| 作用对象 | 只能是自己（`user_id` 来自 Actor） | 全体 / 指定角色 |
| 端点前缀 | `/api/v1/auth/notifications*` | `/api/v1/admin/notifications*` |

刻意**不拆成两个服务**：两者共用同一张表与同一套读口径
（"未读怎么算""已读怎么算"），拆开后"未读数"的定义会出现第二份实现 ——
而这正是最容易被改歪、又最难被发现的一处（角标差 1 谁也不报警）。

为什么投递与业务**同事务**
========================
`publish_system_event` 直接写调用方传进来的那个 `AsyncSession`，
因此"业务改动提交"与"消息落库"要么一起成立、要么一起不成立。
这是刻意的：

- **不能异步投递**（例如后台任务）：本项目没有任务队列（DD 未冻结），
  而"发消息失败就静默丢掉"会让用户账户已经被禁用、却从来没被通知过；
- **不能在业务提交后再写**：那需要一个新事务，失败时业务已经生效，
  于是留下一类无法自动修复的缺口（"我改了但你没告诉我"）；
- 同事务的代价是"通知写不进去 ⇒ 业务也失败"。这个代价可接受且**方向正确**：
  通知写不进去只可能是数据库不可用，而那时业务本身也写不进去。
  唯一被放大的场景是"通知表结构坏了导致用户无法被禁用" ——
  属于必须立刻发现的部署事故，fail-closed 比静默降级好。

为什么通知**不进审计表**
======================
`§32` 的边界：审计记录"谁做了什么"，通知记录"谁该被告知什么"。
系统消息本身不是治理动作（它由治理动作派生，而那个动作已经被审计了），
逐条记审计只会让审计表里一半是"系统给人发了条消息"。
唯一被审计的是**管理员发布 / 撤回公告** —— 那是治理动作。

⚠️ 因此通知内容里**不得出现敏感值**：通知没有脱敏管道
（`app/core/masking.py` 作用于日志），它会以明文出现在界面上。
口令、令牌、MFA 密钥一律不进 `title` / `body`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditEvent, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError
from app.db.base import utc_now
from app.models.enums import (
    AnnouncementAudience,
    NotificationCategory,
    NotificationLevel,
)
from app.models.notification import (
    BODY_MAX_CHARS,
    LINK_LENGTH,
    OPERATOR_USERNAME_LENGTH,
    TITLE_LENGTH,
    Announcement,
    Notification,
)
from app.repositories.notification import NotificationRepository
from app.services.authorization import ApiPermissionCode, AuthorizationService

#: 审计资源类型（与 `announcements` 表对应）。
RESOURCE_TYPE_ANNOUNCEMENT = "ANNOUNCEMENT"

#: 分页上界（与其它列表接口一致）。
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class SystemEventSpec:
    """一个系统事件在通知面上的形状。

    为什么把"事件码 → 标题 / 跳转 / 轻重"集中成一张表而不是散在各调用点：
    调用点只该回答"发生了什么、发生在谁身上"，不该各写一遍文案 ——
    否则同一类事件在不同调用点会有不同措辞（"你的会话已被顶替" vs
    "账号在别处登录"），用户看到的是两种事。
    文案集中在 `SYSTEM_EVENTS` 后，改动一处即可全站统一。

    `link` 是**前端路由路径**（不是后端 API 路径）：点进去要落到页面上。
    """

    code: str
    title: str
    link: str | None
    level: NotificationLevel


#: 系统事件目录。
#:
#: ⚠️ 每个 `link` 都必须是前端**真实存在**的路由（`/system/*` 为动态路由，
#: 由权限契约生成；用户无该页权限时点进去会落 403 —— 这是可接受的，
#: 因为"无权看会话管理"的用户本来也不该被引导去看会话明细，
#: 消息正文已经说清了发生了什么）。
#: `tests/test_notification_api.py` 钉住这条清单与前端的路由表一致。
SYSTEM_EVENTS: dict[str, SystemEventSpec] = {
    spec.code: spec
    for spec in (
        SystemEventSpec(
            code="SESSION_SUPERSEDED",
            title="你的账号在另一处登录，此前会话已下线",
            link="/system/sessions",
            level=NotificationLevel.WARNING,
        ),
        SystemEventSpec(
            code="PASSWORD_RESET",
            title="你的登录口令已被管理员重置",
            link="/profile",
            level=NotificationLevel.IMPORTANT,
        ),
        SystemEventSpec(
            code="USER_DISABLED",
            title="你的账号已被禁用",
            link="/profile",
            level=NotificationLevel.IMPORTANT,
        ),
        SystemEventSpec(
            code="USER_ENABLED",
            title="你的账号已恢复启用",
            link="/profile",
            level=NotificationLevel.INFO,
        ),
        SystemEventSpec(
            code="USER_ROLES_CHANGED",
            title="你的角色授权已变更，权限已即时生效",
            link="/profile",
            level=NotificationLevel.WARNING,
        ),
    )
}


class NotificationPublisher(Protocol):
    """系统事件投递端口。

    为什么要有这个端口（而不是让 `UserService` / `SessionService`
    直接 new 一个 `NotificationService`）：那些服务在一次单测里会被大量构造，
    而绝大多数用例与通知无关。"默认不投递、需要时显式注入"让通知成为
    **可观测的依赖**而不是隐式副作用 —— 与 `AuditRecorder` 完全同一取向。

    ⚠️ 端口只有这一个方法：系统消息不允许"自定义标题"。
    若允许调用点自带文案，`SYSTEM_EVENTS` 的集中就白做了。
    需要新文案时往目录里加一个 `SystemEventSpec`。
    """

    async def publish_system_event(
        self,
        *,
        recipient_user_id: int,
        event: SystemEventSpec,
        body: str | None,
    ) -> Notification | None:
        """给某个用户投递一条系统消息。返回写入的行（无副作用实现返回 None）。"""
        ...


class NullNotificationPublisher:
    """不做任何投递（未注入通知设施时的默认实现）。

    与 `NullAuditRecorder` 同一存在理由：让业务服务不必依赖通知设施即可构造。
    """

    async def publish_system_event(
        self,
        *,
        recipient_user_id: int,
        event: SystemEventSpec,
        body: str | None,
    ) -> Notification | None:
        del recipient_user_id, event, body
        return None


@dataclass(frozen=True, slots=True)
class NotificationPage:
    """收件箱分页结果（分页协议沿用人类已裁定的 `pageNum` / `pageSize`）。"""

    items: list[Notification]
    total: int
    unread: int
    page_num: int
    page_size: int


@dataclass(frozen=True, slots=True)
class AnnouncementPage:
    """已发布公告分页结果。"""

    items: list[Announcement]
    total: int
    page_num: int
    page_size: int


@dataclass(frozen=True, slots=True)
class AnnouncementResult:
    """公告发布结果。

    `recipient_count` 是**发布那一刻**解析出的收件人数，与
    `announcement.recipient_count` 同源；单独列出是让调用方（端点 / 审计）
    不必再去读实体字段。
    """

    announcement: Announcement
    recipient_count: int


class NotificationService:
    """站内通知服务（自助收件箱 + 管理端公告 + 系统事件投递端口）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._repo = NotificationRepository(session)
        self._authz = AuthorizationService(session)
        self._audit = audit or NullAuditRecorder()

    # ------------------------------------------------------------------
    # 自助：我的收件箱
    # ------------------------------------------------------------------

    async def list_mine(
        self,
        *,
        actor: CurrentActor,
        unread_only: bool = False,
        category: NotificationCategory | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> NotificationPage:
        """列出**我自己**的收件箱。

        收件人恒为 `actor.user_id`，**不接受收件人参数** ——
        一个"按 user_id 查收件箱"的参数就是一条越权读的入口，
        而它没有任何正当用处（管理端要看的是公告，不是某个人的私信）。
        """
        self._validate_page(page_num, page_size)
        items = await self._repo.list_for_user(
            actor.user_id,
            unread_only=unread_only,
            category=category,
            page_num=page_num,
            page_size=page_size,
        )
        total = await self._repo.count_for_user(
            actor.user_id, unread_only=unread_only, category=category
        )
        unread = await self._repo.count_unread(actor.user_id)
        return NotificationPage(
            items=items, total=total, unread=unread, page_num=page_num, page_size=page_size
        )

    async def unread_count(self, *, actor: CurrentActor) -> int:
        """我的未读数（顶栏角标）。"""
        return await self._repo.count_unread(actor.user_id)

    async def mark_read(self, *, actor: CurrentActor, notification_id: int) -> Notification:
        """把**我的一条**通知标记为已读。

        Raises:
            NotFoundError: 该通知不存在、不属于我、或已被删除。
                三种情况**故意返回同一个 404**：区分它们等于把
                "存在一个 ID 为 X 的通知（但不是你的）"这个事实泄给调用方，
                而那正是枚举他人消息的第一步。
        """
        notification = await self._repo.get_for_user(notification_id, actor.user_id)
        if notification is None:
            raise NotFoundError("通知不存在")
        await self._repo.mark_read(notification, now=utc_now())
        return notification

    async def mark_all_read(self, *, actor: CurrentActor) -> int:
        """把我的全部未读标记为已读，返回本次影响条数。"""
        return await self._repo.mark_all_read(actor.user_id, now=utc_now())

    # ------------------------------------------------------------------
    # 管理：公告
    # ------------------------------------------------------------------

    async def list_announcements(
        self, *, actor: CurrentActor, page_num: int = 1, page_size: int = 20
    ) -> AnnouncementPage:
        """列出已发布公告（需要公告管理权限）。"""
        self._validate_page(page_num, page_size)
        await self._assert_can_manage(actor)
        items = await self._repo.list_announcements(page_num=page_num, page_size=page_size)
        total = await self._repo.count_announcements()
        return AnnouncementPage(items=items, total=total, page_num=page_num, page_size=page_size)

    async def announce(
        self,
        *,
        actor: CurrentActor,
        title: str,
        body: str | None,
        level: NotificationLevel,
        audience_type: AnnouncementAudience,
        audience_role_id: int | None,
    ) -> AnnouncementResult:
        """发布一条公告：写公告定义 + 扇出到受众的收件箱。

        顺序是**先定义、后扇出**：扇出行要引用公告 ID，且"公告存在但收件箱
        一条没有"（受众为空）是一个合法状态 —— 反过来先扇出再写定义，
        就会有一段"收件箱里有消息、但查不到它从何而来"的窗口。

        Raises:
            BadRequestError: 受众参数自相矛盾（ROLE 却没给角色 / ALL 却给了角色）。
                数据库上的 `audience_role_consistent` 约束是最终保证，
                这里的预校验只负责给出**可读的报错**而不是一个 500。
        """
        await self._assert_can_manage(actor)
        self._validate_audience(audience_type=audience_type, audience_role_id=audience_role_id)
        title = title.strip()
        if title == "":
            raise BadRequestError("公告标题不能为空")
        if len(title) > TITLE_LENGTH:
            raise BadRequestError(f"公告标题不能超过 {TITLE_LENGTH} 个字符")
        if body is not None and len(body) > BODY_MAX_CHARS:
            raise BadRequestError(f"公告正文不能超过 {BODY_MAX_CHARS} 个字符")

        recipient_ids = await self._repo.resolve_audience_user_ids(
            audience_type=audience_type, audience_role_id=audience_role_id
        )

        announcement = await self._repo.add_announcement(
            Announcement(
                title=title,
                body=body,
                level=level,
                audience_type=audience_type,
                audience_role_id=audience_role_id,
                recipient_count=len(recipient_ids),
                created_by=actor.user_id,
                created_by_username=actor.username,
            )
        )

        # 扇出：共用同一个 `created_at`（发布时刻），因此读路径必须用
        # `(created_at desc, id desc)` 排序才稳定（见仓储的说明）。
        published_at = utc_now()
        await self._repo.add_many(
            [
                Notification(
                    user_id=user_id,
                    category=NotificationCategory.ANNOUNCEMENT,
                    announcement_id=announcement.id,
                    title=title,
                    body=body,
                    link="/notifications",
                    level=level,
                    created_at=published_at,
                    updated_at=published_at,
                )
                for user_id in recipient_ids
            ]
        )

        self._record(
            actor=actor,
            action=AuditAction.NOTIFICATION_ANNOUNCE,
            resource_id=announcement.id,
            after={
                "title": title,
                "level": level.value,
                "audience_type": audience_type.value,
                "audience_role_id": audience_role_id,
                "recipient_count": len(recipient_ids),
                # 正文长度而非正文：公告正文可能很长，
                # 而审计 append-only、保留 2 年 —— 写进去撤不回来。
                # 与系统参数的"审计不记值"同一取向（§13）。
                "body_length": len(body) if body is not None else 0,
            },
        )
        return AnnouncementResult(announcement=announcement, recipient_count=len(recipient_ids))

    async def revoke_announcement(self, *, actor: CurrentActor, announcement_id: int) -> int:
        """撤回一条公告：逻辑删除公告定义 + 逻辑删除它扇出的收件箱行。

        为什么必须有"撤回"：一次误发的全员公告会落在每个人的角标上，
        而通知**没有其它出口**（不像邮件可以道歉再发一封）。
        撤回只删扇出的副本，已经读过的内容无法收回 —— 这一点必须
        在界面上说清（`docs/DESIGN-DECISIONS §32` 记为已知代价）。

        Returns:
            被一并逻辑删除的收件箱行数。

        Raises:
            NotFoundError: 公告不存在或已被撤回。
        """
        await self._assert_can_manage(actor)
        announcement = await self._repo.get_announcement(announcement_id)
        if announcement is None:
            raise NotFoundError("公告不存在")
        now = utc_now()
        purged = await self._repo.purge_for_announcement(announcement_id, now=now)
        announcement.deleted_at = now
        await self._session.flush()

        self._record(
            actor=actor,
            action=AuditAction.NOTIFICATION_REVOKE,
            resource_id=announcement_id,
            before={"title": announcement.title, "recipient_count": announcement.recipient_count},
            after={"purged": purged},
        )
        return purged

    # ------------------------------------------------------------------
    # 端口实现：系统事件投递
    # ------------------------------------------------------------------

    async def publish_system_event(
        self,
        *,
        recipient_user_id: int,
        event: SystemEventSpec,
        body: str | None = None,
    ) -> Notification | None:
        """给某个用户投递一条系统消息（**与调用方业务同事务**）。

        返回写入的行；`event.link` 为空时不设跳转。
        """
        notification = Notification(
            user_id=recipient_user_id,
            category=NotificationCategory.SYSTEM,
            event_code=event.code,
            title=event.title[:TITLE_LENGTH],
            body=body,
            link=None if event.link is None else event.link[:LINK_LENGTH],
            level=event.level,
        )
        return await self._repo.add(notification)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _assert_can_manage(self, actor: CurrentActor) -> None:
        await self._authz.assert_api_permission(
            actor=actor, api_code=ApiPermissionCode.NOTIFICATION_MANAGE
        )

    @staticmethod
    def _validate_page(page_num: int, page_size: int) -> None:
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise BadRequestError(f"pageSize 必须在 1 到 {MAX_PAGE_SIZE} 之间")

    @staticmethod
    def _validate_audience(
        *, audience_type: AnnouncementAudience, audience_role_id: int | None
    ) -> None:
        """受众参数的自洽性（DB 约束是最终保证，这里只负责可读报错）。"""
        if audience_type is AnnouncementAudience.ROLE and audience_role_id is None:
            raise BadRequestError("受众为角色时必须指定角色")
        if audience_type is AnnouncementAudience.ALL and audience_role_id is not None:
            raise BadRequestError("受众为全员时不能指定角色")

    def _record(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """写一条成功审计（只有公告的发布 / 撤回会走到这里）。"""
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type=RESOURCE_TYPE_ANNOUNCEMENT,
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username[:OPERATOR_USERNAME_LENGTH],
                before_data=before,
                after_data=after,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )


__all__ = [
    "MAX_PAGE_SIZE",
    "RESOURCE_TYPE_ANNOUNCEMENT",
    "SYSTEM_EVENTS",
    "AnnouncementPage",
    "AnnouncementResult",
    "NotificationPage",
    "NotificationPublisher",
    "NotificationService",
    "NullNotificationPublisher",
    "SystemEventSpec",
]
