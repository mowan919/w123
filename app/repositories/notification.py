"""站内通知数据访问 —— `DESIGN-DECISIONS §32`。

职责边界
-------
只做数据访问与数据层口径（未删除 / 受众是谁 / 未读计数）。
"什么时候该发一条通知""谁能发公告"这类规则落在
`app/services/notification.py`。

⚠️ 本仓储的**每一个读方法都带收件人维度**（`user_id`）。
这不是冗余：收件箱是"我的"数据，任何"按 ID 取一条通知"的写法都必须在
SQL 层就把 `user_id` 带进 `where`，而不是取出来之后在 Python 里比一下 ——
后者是"先泄漏再校验"，一次忘记比对的改动就是越权读。
因此本仓储刻意**不提供** `get(notification_id)`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AnnouncementAudience, NotificationCategory, UserStatus
from app.models.notification import Announcement, Notification
from app.models.role import UserRole
from app.models.user import AdminUser

#: 批量插入的分片大小。
#:
#: 一次全员公告是"用户数"行。一次性 `add_all` 会让 UnitOfWork 里堆着
#: 几万个 ORM 对象（每个都有身份映射开销），且单条 INSERT 的参数个数
#: 有上限（PostgreSQL 协议最多 65535 个绑定参数）。
#: 分片后每次 flush 一小批，内存与语句长度都可控。
#:
#: 为什么用 ORM `add_all` 而不是 Core `insert()`：主键是 Python 侧
#: Snowflake 默认值（`PrimaryKeyMixin`），Core 插入需要手工逐个生成 ID；
#: 更重要的理由是 Phase 7 的教训 —— Core 语句不维护 ORM 身份映射，
#: 同一事务内后续 `select` 会看到"库里已有、内存里没有"的幽灵对象。
_FANOUT_CHUNK = 500


class NotificationRepository:
    """收件箱与公告的数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ 收件箱写入

    async def add(self, notification: Notification) -> Notification:
        """写入一条通知并 flush（拿到数据库约束的校验结果）。"""
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def add_many(self, notifications: list[Notification]) -> None:
        """分片写入一批通知（公告扇出）。"""
        for start in range(0, len(notifications), _FANOUT_CHUNK):
            self._session.add_all(notifications[start : start + _FANOUT_CHUNK])
            await self._session.flush()

    # ------------------------------------------------------------ 收件箱读取

    async def get_for_user(self, notification_id: int, user_id: int) -> Notification | None:
        """取**属于该用户**的一条未删除通知。

        两个条件必须在同一个 `where` 里（见模块文档）：
        分成"先按 ID 取、再比 user_id"就等于把别人的通知读进了内存。
        """
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        category: NotificationCategory | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[Notification]:
        """分页列出该用户的收件箱（新的在前）。

        排序键是 `(created_at desc, id desc)` 而不是只按 `created_at`：
        一次公告扇出的 N 行**共用同一个 `created_at`**（发布时刻），
        只按时间排序时它们的相对顺序由数据库决定 —— 于是"翻到第 2 页
        又出现第 1 页看过的那条"会随机发生。
        Snowflake ID 单调递增，补上它就能得到稳定且与时间一致的全序。
        """
        stmt = (
            self._mine(user_id, unread_only=unread_only, category=category)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        category: NotificationCategory | None = None,
    ) -> int:
        """统计收件箱条数（与 `list_for_user` 同口径，供分页总数）。"""
        stmt = select(func.count()).select_from(
            self._mine(user_id, unread_only=unread_only, category=category).subquery()
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_unread(self, user_id: int) -> int:
        """未读数（角标）。走 `ix_notifications_user_unread_active` 部分索引。"""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                Notification.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------ 收件箱变更

    async def mark_read(self, notification: Notification, *, now: datetime) -> None:
        """把一条通知标记为已读（**幂等**：已读的不会被改写时间）。

        时间只写第一次读的那一次：后端的 `read_at` 是"什么时候读的"这个事实，
        重复标记把它刷新成"最后一次点它"，那个事实就没了。
        视图层每次打开面板都会重放一次标记请求，因此幂等不是可选优化。
        """
        if notification.read_at is not None:
            return
        notification.read_at = now
        await self._session.flush()

    async def mark_all_read(self, user_id: int, *, now: datetime) -> int:
        """把该用户全部未读标记为已读，返回受影响行数。

        ⚠️ 这里用 Core `update()` 而**不是**逐个 ORM 变更，与 Phase 7 的
        教训（`DESIGN-DECISIONS §13`）看似冲突，但适用条件不同：
        那条教训针对的是"同一事务内会再 `session.get()` 同一个实体"的场景
        —— Core 语句不维护身份映射，会留下"库里已改、内存未改"的幽灵对象。
        "全部已读"是本请求里对该集合的**最后一次**写：调用方随后只返回
        未读数（一个 `count(*)`，走 SQL 不看内存），不读这些实体。
        因此不构成幽灵对象问题，同时避免把 N 个实体全加载进内存。
        若将来要在同一请求里返回"已读后的列表"，必须改成逐个 ORM 变更。

        行数用 `RETURNING id` 统计而不是 `Result.rowcount`：后者在类型上
        只存在于 `CursorResult`（`AsyncSession.execute` 声明返回基类
        `Result`），读它必须引入 `Any` / `cast` 兜底。
        `RETURNING` 让结果自带类型信息 —— 与
        `UserRepository.prune_password_history` 同一取向。
        """
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                Notification.deleted_at.is_(None),
            )
            .values(read_at=now)
            .returning(Notification.id)
        )
        updated = (await self._session.execute(stmt)).scalars().all()
        await self._session.flush()
        return len(updated)

    # ------------------------------------------------------------ 受众解析

    async def resolve_audience_user_ids(
        self, *, audience_type: AnnouncementAudience, audience_role_id: int | None
    ) -> list[int]:
        """解析受众用户 ID（**发布那一刻**的名单）。

        口径（`DESIGN-DECISIONS §32`，两条都刻意如此）：

        1. 只取 `status=ACTIVE` 且未逻辑删除的用户。
           给被禁用的人发消息没有意义 —— 他登录不进来，
           只会让"已送达 N 人"这个数字虚高。
        2. `ROLE` 按 `user_roles` 的**直接分配**判定，**不含角色继承**。
           继承（DD-05）是**权限**关系："他继承了这个角色的权限"不等于
           "他是这个角色的人"。公告受众是组织归属问题。
           若将来裁定继承者也算受众，改动只在本方法一处。
        """
        if audience_type is AnnouncementAudience.ALL:
            stmt = select(AdminUser.id).where(
                AdminUser.status == UserStatus.ACTIVE,
                AdminUser.deleted_at.is_(None),
            )
        else:
            if audience_role_id is None:
                # `audience_role_consistent` 约束已保证这种组合进不了库；
                # 这里显式返回空名单而不是抛异常：调用方（服务层）
                # 已经在写入前校验过，走到这里说明数据被人手动改过，
                # 空名单是"发给 0 人"这个可观测的结果，比 500 更好定位。
                return []
            stmt = (
                select(UserRole.user_id)
                .join(AdminUser, AdminUser.id == UserRole.user_id)
                .where(
                    UserRole.role_id == audience_role_id,
                    AdminUser.status == UserStatus.ACTIVE,
                    AdminUser.deleted_at.is_(None),
                )
                .distinct()
            )
        return [int(row) for row in (await self._session.execute(stmt)).scalars().all()]

    # ------------------------------------------------------------ 公告

    async def add_announcement(self, announcement: Announcement) -> Announcement:
        """写入公告定义并 flush（拿到 ID 供扇出引用）。"""
        self._session.add(announcement)
        await self._session.flush()
        return announcement

    async def get_announcement(self, announcement_id: int) -> Announcement | None:
        """按 ID 取**未撤回**的公告定义。

        ⚠️ 与收件箱的 `get_for_user` 不同，这里**不**带收件人维度 ——
        公告是面向管理者的公开记录（谁都能看到"系统发过这条公告"），
        不是某个人的私有消息。它同样不泄漏隐私：公告本来就是要广播的内容。
        """
        stmt = select(Announcement).where(
            Announcement.id == announcement_id,
            Announcement.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_announcements(
        self, *, page_num: int = 1, page_size: int = 20
    ) -> list[Announcement]:
        """分页列出已发布公告（新的在前，同 `list_for_user` 的全序理由）。"""
        stmt = (
            select(Announcement)
            .where(Announcement.deleted_at.is_(None))
            .order_by(Announcement.created_at.desc(), Announcement.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_announcements(self) -> int:
        """统计已发布公告数。"""
        stmt = (
            select(func.count()).select_from(Announcement).where(Announcement.deleted_at.is_(None))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def purge_for_announcement(self, announcement_id: int, *, now: datetime) -> int:
        """逻辑删除某公告扇出的全部收件箱行（撤回公告用）。

        目前唯一的调用方是撤回公告
        （`NotificationService.revoke_announcement`）。
        保留独立方法而不是把 `update` 内联进服务：本仓储存着"收件箱永远按
        `user_id` 过滤"这条口径，让服务层自己拼一条跨用户的 `update`
        正是那条约定的反面。
        """
        stmt = (
            update(Notification)
            .where(
                Notification.announcement_id == announcement_id,
                Notification.deleted_at.is_(None),
            )
            .values(deleted_at=now)
            .returning(Notification.id)
        )
        purged = (await self._session.execute(stmt)).scalars().all()
        await self._session.flush()
        return len(purged)

    # ------------------------------------------------------------ 内部

    @staticmethod
    def _mine(
        user_id: int,
        *,
        unread_only: bool,
        category: NotificationCategory | None,
    ) -> Select[tuple[Notification]]:
        """收件箱的基础条件（list / count 共用，保证两者口径一致）。"""
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if category is not None:
            stmt = stmt.where(Notification.category == category)
        return stmt


__all__ = ["NotificationRepository"]
