"""系统事件投递接线测试（Phase 14 / `DESIGN-DECISIONS §32`）。

本文件管的是**接线**，不是口径
============================
三个文件各管一层，刻意的分工：

| 文件 | 管什么 |
|---|---|
| `tests/test_notification_service.py` | 读口径（未读怎么算、受众怎么解析、分页怎么稳） |
| `tests/test_notification_api.py` | HTTP 面（路由存在性、状态码、信封、ID 字符串化） |
| **本文件** | 业务服务在什么条件下**真的**投递 / **真的**不投递 |

为什么"接线"必须单独有一组用例
----------------------------
投递是**默认开启**的隐式副作用：`UserService(session)` /
`SessionService(session)` 不传 `notifier` 时会自建真实投递器
（见两个服务 `__init__` 的说明）。因此

- 漏接一个调用点 → 用户永远收不到那类消息，但**没有任何一处会红**；
- 多接一个调用点 → 用户被噪音刷屏，同样**没有任何一处会红**。

这两种错都属于本项目反复踩过的形状：**两个各自正确的东西拼起来才错**，
只有在本文件这种"业务动作 → 落库结果"的端到端断言里才暴露。

本文件同时钉住三条**反噪音**规则（都是刻意的，不是实现巧合）：
1. 一次顶替事件**一条**消息，不按被顶替的会话数重复；
2. 状态没真变（`enable` 一个本就 ACTIVE 的用户）**不投**；
3. 角色集合没真变（保存一次没改动的表单）**不投**。

以及一条事务性规则
----------------
投递与业务**同事务**：业务回滚，消息必须一起消失。
本文件用**保存点**验证它（`TestDeliverySharesBusinessTransaction`）——
回滚到保存点后业务状态与消息行必须同时复原，任何一个留下来都说明
投递走了自己的事务。
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.auth.actor import CurrentActor
from app.db.base import utc_now
from app.models.enums import NotificationCategory, NotificationLevel, UserStatus
from app.models.notification import BODY_MAX_CHARS, TITLE_LENGTH, Notification
from app.models.session import UserSession
from app.models.user import AdminUser
from app.services.notification import (
    SYSTEM_EVENTS,
    NotificationPublisher,
    NotificationService,
    NullNotificationPublisher,
)
from app.services.session import SessionService
from app.services.user import UserService
from tests.factories import make_role, make_session, make_user

pytestmark = pytest.mark.integration

#: 本文件专用的 ID 段（**必须**与其它文件不同）。
#:
#: ⚠️ 为什么不复用 `tests/test_user_service._seed_tree`：本项目跑在**共享**的
#: PostgreSQL 上，那个种子用 `role_code="SUPER_ADMIN"` 等真实码播种，而真实库
#: 里已经由 `scripts/seed_init.py` 写过同名角色 —— 再插一次直接撞
#: `uq_roles_role_code_*`（`test_user_service.py` / `test_dict_service.py`
#: 在共享库上成片变红就是这个原因，本项目记作"既存红"）。
#: 本文件的名字全部带 `NOTIFYDEL` 前缀，只为"接线"服务，不需要真实码。
U_TARGET = 62101
U_OTHER = 62102
S_OLD_1 = 62111
S_OLD_2 = 62112
S_OLD_3 = 62113
ROLE_AUDITOR = 62121
ROLE_PLAIN = 62122

#: 管理动作的操作者。构造一个**合成**操作者即可：投递与数据范围无关，
#: 而造一个真实的 SUPER_ADMIN 用户又会回到上面那个撞码问题。
ROOT_ACTOR = CurrentActor.super_admin(user_id=62151, username="notify-deliver-root")

#: 形状合法的令牌（43 字符 base64url）。
TOKEN_1 = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
TOKEN_2 = "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
TOKEN_3 = "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"

PW_NEW = "Hotel-Passw0rd!08"


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------
async def _seed(session) -> None:
    """两个角色，供 `assign_roles` 的"集合变了 / 没变"两条用例使用。"""
    await make_role(session, role_id=ROLE_AUDITOR, role_code="NOTIFYDEL_AUDITOR")
    await make_role(session, role_id=ROLE_PLAIN, role_code="NOTIFYDEL_PLAIN")


# ---------------------------------------------------------------------------
# 断言辅助
# ---------------------------------------------------------------------------
async def _inbox(session, user_id: int) -> list[Notification]:
    """某用户收件箱的全部行（按创建序）。

    排序用 `id` 而不是 `created_at`：同一毫秒内写下的两行时间戳可能完全相同，
    而雪花 ID 是全序的（这正是 `§32` 里"扇出必须带 id 排序"的同一条理由）。
    """
    rows = await session.execute(
        select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)
    )
    return list(rows.scalars().all())


async def _codes(session, user_id: int) -> list[str]:
    return [row.event_code or "" for row in await _inbox(session, user_id)]


async def _only(session, user_id: int, event_code: str) -> Notification:
    """断言该用户**恰好**收到一条指定事件，并返回它。

    "恰好一条"而不是"至少一条"：多出来的那条正是本文件要防的噪音。
    """
    rows = [row for row in await _inbox(session, user_id) if row.event_code == event_code]
    assert len(rows) == 1, f"期望恰好 1 条 {event_code}，实际 {[r.event_code for r in rows]}"
    return rows[0]


async def _seed_user(session, *, user_id: int, username: str) -> AdminUser:
    """创建一个无部门、无角色的普通用户（投递不需要部门语义）。"""
    await make_user(session, user_id=user_id, username=username)
    user = await session.get(AdminUser, user_id)
    assert user is not None
    return user


# ---------------------------------------------------------------------------
# 端口契约
# ---------------------------------------------------------------------------
class TestPublisherPort:
    """`NotificationPublisher` 的形状不得漂移。"""

    def test_protocol_declares_exactly_one_method(self) -> None:
        """端口只有 `publish_system_event` 一个方法。

        多一个方法就等于开了一条"调用点自带文案"的口子 ——
        而 `SYSTEM_EVENTS` 目录的全部价值正是"文案只有一处"。
        `_abc_impl` / `__protocol_attrs__` 之类的私有名不算。
        """
        public = {name for name in NotificationPublisher.__dict__ if not name.startswith("_")}
        assert public == {"publish_system_event"}

    def test_both_implementations_share_the_signature(self) -> None:
        """真实投递器与空实现必须同形，否则替换会静默丢掉参数。"""
        real = inspect.signature(NotificationService.publish_system_event)
        null = inspect.signature(NullNotificationPublisher.publish_system_event)
        assert list(real.parameters) == list(null.parameters)

    async def test_null_publisher_writes_nothing(self, db_session) -> None:
        """空实现是**零副作用**：不写行、不报错、返回 None。"""
        await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-null")
        result = await NullNotificationPublisher().publish_system_event(
            recipient_user_id=U_TARGET,
            event=SYSTEM_EVENTS["USER_ENABLED"],
            body=None,
        )
        assert result is None
        assert await _inbox(db_session, U_TARGET) == []

    def test_every_system_event_has_a_valid_shape(self) -> None:
        """目录里的每一行都要能被写进表：标题不超长、链接不超长、等级合法。"""
        assert SYSTEM_EVENTS, "系统事件目录为空"
        for code, spec in SYSTEM_EVENTS.items():
            assert code == spec.code, f"目录键与实体码不一致：{code}"
            assert spec.title.strip(), f"{code} 的标题为空"
            assert len(spec.title) <= TITLE_LENGTH, f"{code} 的标题超长"
            assert isinstance(spec.level, NotificationLevel)


class TestSystemEventLinksPointAtRealFrontendRoutes:
    """`link` 是**前端路由路径**，必须真的能落地。

    这是典型的"两边各自都对、凑起来才错"：`/system/session` 是注册表键、
    `/system/sessions` 才是路由路径，一个字母之差在界面上表现为
    "点消息什么都不发生"（或落到 404 兜底页），而两侧的测试都不会红。

    路由来源有两个，缺一不可：
    - **静态路由**：`frontend/src/router/index.ts` 里写死的 `/profile` 等；
    - **动态路由**：由权限契约的页面表生成 —— 页面路径在
      `scripts/seed_data.py` 的 `PAGES` 里（后端是唯一真相）。
    """

    @staticmethod
    def _static_route_paths() -> set[str]:
        source = Path(__file__).resolve().parent.parent / "frontend" / "src" / "router" / "index.ts"
        assert source.is_file(), f"找不到前端路由文件：{source}"
        literal = set(re.findall(r"path:\s*'([^']+)'", source.read_text(encoding="utf-8")))
        # 布局子路由写的是相对路径（`profile` / `notifications` / `reports`），
        # 它们挂在 `path: '/'` 之下，因此对外路径是 `/` + 相对路径。
        return {p if p.startswith("/") else f"/{p}" for p in literal}

    @staticmethod
    def _page_route_paths() -> set[str]:
        from scripts import seed_data

        return {entry[2] for entry in seed_data.PAGES}

    def test_links_resolve_to_a_known_route(self) -> None:
        reachable = self._static_route_paths() | self._page_route_paths()
        links = {spec.code: spec.link for spec in SYSTEM_EVENTS.values() if spec.link is not None}
        assert links, "没有任何系统事件带跳转链接，这条护栏就失去意义了"
        unknown = {code: link for code, link in links.items() if link not in reachable}
        assert not unknown, (
            f"以下事件的 link 不是真实路由：{unknown}；已知路由：{sorted(reachable)}"
        )

    def test_announcement_link_resolves_too(self) -> None:
        """公告扇出的 `link` 同样要落地（它写在服务里，不在目录里）。"""
        reachable = self._static_route_paths() | self._page_route_paths()
        source = (
            Path(__file__).resolve().parent.parent / "app" / "services" / "notification.py"
        ).read_text(encoding="utf-8")
        links = set(re.findall(r'link="([^"]+)"', source))
        assert links, "服务里找不到任何 link 字面量，正则可能失效了"
        unknown = {link for link in links if link not in reachable}
        assert not unknown, f"公告跳转目标是真实路由之外的路径：{unknown}"


# ---------------------------------------------------------------------------
# 会话顶替
# ---------------------------------------------------------------------------
class TestSessionSupersedeDelivery:
    """`SessionService.create` 顶替旧会话时的投递规则。"""

    async def _seed_old_session(
        self, session, *, session_id: int, user_id: int, token: str
    ) -> None:
        await make_session(
            session,
            session_id=session_id,
            user_id=user_id,
            access_token=token,
            refresh_token=token,
            login_at=utc_now(),
        )

    async def test_first_login_delivers_nothing(self, db_session) -> None:
        """首次登录没有可顶替的会话 → 一条都不该发。"""
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-first")

        await SessionService(db_session).create(user=user, ip="10.4.0.1")

        assert await _inbox(db_session, U_TARGET) == []

    async def test_supersede_delivers_exactly_one_message(self, db_session) -> None:
        """顶替成功 → 恰好一条，且形状由目录决定。"""
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-super")
        await self._seed_old_session(
            db_session, session_id=S_OLD_1, user_id=U_TARGET, token=TOKEN_1
        )

        await SessionService(db_session).create(user=user, ip="10.4.0.2", user_agent="pytest/1.0")

        row = await _only(db_session, U_TARGET, "SESSION_SUPERSEDED")
        spec = SYSTEM_EVENTS["SESSION_SUPERSEDED"]
        assert row.category is NotificationCategory.SYSTEM
        assert row.title == spec.title
        assert row.level is NotificationLevel.WARNING
        assert row.link == spec.link
        assert row.read_at is None, "刚投递的消息必须是未读"
        assert row.body, "顶替消息必须带正文说明发生了什么"
        assert len(row.body) <= BODY_MAX_CHARS

    async def test_three_superseded_sessions_still_deliver_one_message(self, db_session) -> None:
        """**反噪音的核心断言**：角标是"有几件事要看"，不是"几个会话被关了"。"""
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-many")
        for session_id, token in ((S_OLD_1, TOKEN_1), (S_OLD_2, TOKEN_2), (S_OLD_3, TOKEN_3)):
            await self._seed_old_session(
                db_session, session_id=session_id, user_id=U_TARGET, token=token
            )

        await SessionService(db_session).create(user=user, ip="10.4.0.3")

        assert await _codes(db_session, U_TARGET) == ["SESSION_SUPERSEDED"]

    async def test_supersede_does_not_notify_other_users(self, db_session) -> None:
        """投递对象是**被顶替的那个账号**，不是本次登录的发起人之外任何人。"""
        await _seed_user(db_session, user_id=U_OTHER, username="notify-deliver-bystander")
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-scope")
        await self._seed_old_session(
            db_session, session_id=S_OLD_1, user_id=U_TARGET, token=TOKEN_1
        )

        await SessionService(db_session).create(user=user)

        assert await _inbox(db_session, U_OTHER) == []

    async def test_explicit_null_notifier_suppresses_delivery(self, db_session) -> None:
        """显式传空实现 → 不投递。

        这是"不发"作为**写出来的选择**存在的证明：默认开启 + 可显式关闭，
        两者都能被观察到，才谈得上"投递是一个可观测的依赖"。
        """
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-deliver-mute")
        await self._seed_old_session(
            db_session, session_id=S_OLD_1, user_id=U_TARGET, token=TOKEN_1
        )

        await SessionService(db_session, notifier=NullNotificationPublisher()).create(user=user)

        assert await _inbox(db_session, U_TARGET) == []
        # 会话确实被顶替了 —— 否则上面那条断言只是在证明"什么都没发生"。
        old = await db_session.get(UserSession, S_OLD_1)
        assert old is not None and old.revoked_at is not None


# ---------------------------------------------------------------------------
# 账号状态
# ---------------------------------------------------------------------------
class TestUserStatusDelivery:
    """`UserService.disable` / `enable` 的投递规则。"""

    async def test_disable_then_enable_delivers_two_distinct_messages(self, db_session) -> None:
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-status-target")
        service = UserService(db_session)

        await service.disable(actor=ROOT_ACTOR, user_id=U_TARGET)
        await service.enable(actor=ROOT_ACTOR, user_id=U_TARGET)

        assert await _codes(db_session, U_TARGET) == ["USER_DISABLED", "USER_ENABLED"]
        disabled = await _only(db_session, U_TARGET, "USER_DISABLED")
        enabled = await _only(db_session, U_TARGET, "USER_ENABLED")
        assert disabled.level is NotificationLevel.IMPORTANT
        assert enabled.level is NotificationLevel.INFO

    async def test_enabling_an_active_user_delivers_nothing(self, db_session) -> None:
        """**反噪音**：`enable()` 对本就 ACTIVE 的用户照样写库，但不该通知。

        "你的账号已恢复启用"发给一个从没被禁用过的人，是纯粹的噪音；
        而"没有通知"这个结果只有在本用例里才被钉住 ——
        单看 `enable()` 的实现，`previous_status is new_status` 时
        投不投递是个可以随手改掉的细节。
        """
        await _seed(db_session)
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-status-active")
        assert user.status is UserStatus.ACTIVE

        await UserService(db_session).enable(actor=ROOT_ACTOR, user_id=U_TARGET)

        assert await _inbox(db_session, U_TARGET) == []

    async def test_second_disable_delivers_only_once(self, db_session) -> None:
        """重复禁用不重复通知（第二次时状态没变）。"""
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-status-twice")
        service = UserService(db_session)

        await service.disable(actor=ROOT_ACTOR, user_id=U_TARGET)
        await service.disable(actor=ROOT_ACTOR, user_id=U_TARGET)

        assert await _codes(db_session, U_TARGET) == ["USER_DISABLED"]

    async def test_explicit_null_notifier_suppresses_status_delivery(self, db_session) -> None:
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-status-mute")

        await UserService(db_session, notifier=NullNotificationPublisher()).disable(
            actor=ROOT_ACTOR, user_id=U_TARGET
        )

        assert await _inbox(db_session, U_TARGET) == []
        user = await db_session.get(AdminUser, U_TARGET)
        assert user is not None and user.status is UserStatus.DISABLED


# ---------------------------------------------------------------------------
# 口令重置
# ---------------------------------------------------------------------------
class TestPasswordResetDelivery:
    async def test_reset_delivers_an_important_message(self, db_session) -> None:
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-pw-target")

        await UserService(db_session).reset_password(
            actor=ROOT_ACTOR, user_id=U_TARGET, new_password=PW_NEW
        )

        row = await _only(db_session, U_TARGET, "PASSWORD_RESET")
        assert row.level is NotificationLevel.IMPORTANT
        assert row.read_at is None

    async def test_message_never_contains_the_new_password(self, db_session) -> None:
        """**安全断言**：通知没有脱敏管道，明文口令写进去就撤不回来。

        断言的不是"某个字段没含口令"，而是**整行的可读文本里都不含**——
        将来有人往 `body` 里拼口令、或往 `title` 里拼，这条都会红。
        """
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-pw-secret")

        await UserService(db_session).reset_password(
            actor=ROOT_ACTOR, user_id=U_TARGET, new_password=PW_NEW
        )

        for row in await _inbox(db_session, U_TARGET):
            haystack = " ".join(filter(None, (row.title, row.body, row.link, row.event_code)))
            assert PW_NEW not in haystack, f"通知里出现了明文口令：{haystack!r}"


# ---------------------------------------------------------------------------
# 角色变更
# ---------------------------------------------------------------------------
class TestRoleAssignmentDelivery:
    async def test_changed_role_set_delivers_one_message(self, db_session) -> None:
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-role-change")

        await UserService(db_session).assign_roles(
            actor=ROOT_ACTOR, user_id=U_TARGET, role_ids=frozenset({ROLE_AUDITOR})
        )

        row = await _only(db_session, U_TARGET, "USER_ROLES_CHANGED")
        assert row.level is NotificationLevel.WARNING

    async def test_unchanged_role_set_delivers_nothing(self, db_session) -> None:
        """**反噪音**：整体替换语义下，保存一次没改动的表单不该发通知。"""
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-role-same")
        service = UserService(db_session)

        await service.assign_roles(
            actor=ROOT_ACTOR, user_id=U_TARGET, role_ids=frozenset({ROLE_AUDITOR})
        )
        await service.assign_roles(
            actor=ROOT_ACTOR, user_id=U_TARGET, role_ids=frozenset({ROLE_AUDITOR})
        )

        assert await _codes(db_session, U_TARGET) == ["USER_ROLES_CHANGED"]

    async def test_clearing_all_roles_delivers(self, db_session) -> None:
        """清空角色集合同样是"变了"，必须通知（权限被收回，用户必须知道）。"""
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-role-clear")
        service = UserService(db_session)

        await service.assign_roles(
            actor=ROOT_ACTOR, user_id=U_TARGET, role_ids=frozenset({ROLE_AUDITOR})
        )
        await service.assign_roles(actor=ROOT_ACTOR, user_id=U_TARGET, role_ids=frozenset())

        assert await _codes(db_session, U_TARGET) == ["USER_ROLES_CHANGED", "USER_ROLES_CHANGED"]


# ---------------------------------------------------------------------------
# 事务性
# ---------------------------------------------------------------------------
class TestDeliverySharesBusinessTransaction:
    """投递与业务**同事务** —— 业务回滚，消息必须一起消失。

    为什么用保存点而不是"回滚后换个会话再查"：换会话就看不到本用例尚未提交的
    播种数据，于是那条断言会变成"表里没有别人的行"，跟事务性毫无关系。
    保存点把"回滚"压缩在同一个连接、同一份可见数据之内，
    得到的结论才是真正的"两者在同一个事务单元里"。
    """

    async def test_rollback_removes_both_the_change_and_the_message(self, db_session) -> None:
        await _seed(db_session)
        await _seed_user(db_session, user_id=U_TARGET, username="notify-tx-rollback")

        nested = await db_session.begin_nested()
        await UserService(db_session).disable(actor=ROOT_ACTOR, user_id=U_TARGET)

        # 事务内：业务已改、消息已写。
        assert (await db_session.get(AdminUser, U_TARGET)).status is UserStatus.DISABLED
        assert await _codes(db_session, U_TARGET) == ["USER_DISABLED"]

        await nested.rollback()

        # 回滚后：两者必须**同时**复原。
        user = await db_session.get(AdminUser, U_TARGET)
        assert user is not None and user.status is UserStatus.ACTIVE
        assert await _inbox(db_session, U_TARGET) == []

    async def test_rollback_of_a_supersede_removes_the_message_too(self, db_session) -> None:
        """会话顶替路径同样要同事务 —— 这条路径走的是另一个服务。"""
        user = await _seed_user(db_session, user_id=U_TARGET, username="notify-tx-session")
        await make_session(
            db_session,
            session_id=S_OLD_1,
            user_id=U_TARGET,
            access_token=TOKEN_1,
            refresh_token=TOKEN_1,
            login_at=utc_now(),
        )

        nested = await db_session.begin_nested()
        await SessionService(db_session).create(user=user)
        assert await _codes(db_session, U_TARGET) == ["SESSION_SUPERSEDED"]
        await nested.rollback()

        assert await _inbox(db_session, U_TARGET) == []
        old = await db_session.get(UserSession, S_OLD_1)
        assert old is not None and old.revoked_at is None, "回滚后旧会话必须重新有效"


# ---------------------------------------------------------------------------
# 端口默认值
# ---------------------------------------------------------------------------
class TestDefaultNotifierIsReal:
    """两个业务服务的默认投递器必须是**真实投递器**，而不是空实现。

    这是刻意的、也是反直觉的一处选择（通常默认值取"什么也不做"）：
    投递只需要一个 `AsyncSession`，而两个服务**已经有**这个会话，
    所以"忘了注入"就成了纯粹的静默故障 —— 用户会话被顶替、账号被禁用，
    却永远收不到那条消息。默认真实投递让"不发"必须被写出来。
    """

    def test_user_service_defaults_to_a_real_publisher(self, db_session) -> None:
        """默认值必须是**真实投递器**本身，而不是"看着像"的东西。

        断言的是构造出来的属性，而不是源码文本：源码里必然出现
        `NullNotificationPublisher()` 这个名字（`__init__` 的文档在解释
        为什么要显式传它），字符串匹配会把一句注释判成实现。
        """
        notifier = UserService(db_session)._notify
        assert isinstance(notifier, NotificationService)
        assert not isinstance(notifier, NullNotificationPublisher)

    def test_session_service_defaults_to_a_real_publisher(self, db_session) -> None:
        notifier = SessionService(db_session)._notify
        assert isinstance(notifier, NotificationService)
        assert not isinstance(notifier, NullNotificationPublisher)

    async def test_default_and_service_agree_on_what_gets_written(self, db_session) -> None:
        """默认投递器写出的行，与直接用 `NotificationService` 写出的行同形。

        这条把"默认值是不是真的那个东西"从源码字符串断言升级成行为断言：
        若默认值被换成"看着像但其实不写库"的实现，上面两条仍会通过，
        而这条会红。
        """
        await _seed_user(db_session, user_id=U_TARGET, username="notify-default-shape")
        await _seed_user(db_session, user_id=U_OTHER, username="notify-default-shape-2")

        via_default = await UserService(db_session).reset_password(
            actor=ROOT_ACTOR, user_id=U_TARGET, new_password=PW_NEW
        )
        assert via_default is not None

        await NotificationService(db_session).publish_system_event(
            recipient_user_id=U_OTHER,
            event=SYSTEM_EVENTS["PASSWORD_RESET"],
            body=None,
        )

        from_default = await _only(db_session, U_TARGET, "PASSWORD_RESET")
        from_service = await _only(db_session, U_OTHER, "PASSWORD_RESET")
        assert from_default.title == from_service.title
        assert from_default.link == from_service.link
        assert from_default.level is from_service.level
        assert from_default.category is from_service.category


# ---------------------------------------------------------------------------
# 调用点清单
# ---------------------------------------------------------------------------
class TestDeliveryCallSites:
    """投递调用点是一份**清单**，多了少了都要看得见。

    为什么用静态扫描：`publish_system_event` 是"业务动作 → 用户被告知"的
    唯一出口，而它的调用点分散在两个服务里。新增一个业务动作时忘了投递，
    没有任何断言会红（这正是 `FINDING-8-01` / `FINDING-10-01` 那种
    "能力已具备但接不上"的形状）。把清单钉住，改动就必须是有意识的。

    ⚠️ 为什么用 **AST** 而不是正则：调用点里有一处写的是条件表达式
    （`SYSTEM_EVENTS["USER_DISABLED" if ... else "USER_ENABLED"]`），
    正则 `SYSTEM_EVENTS\\["([^"]+)"\\]` 匹配不到它 —— 于是"没人用"的**假报**
    会落在一个**正在被使用**的事件码上。AST 顺带免疫换行 / 拆行等格式变化。
    """

    #: 允许调用投递的业务服务文件（**不含** `notification.py` —— 那是出口本身）。
    _ALLOWED_FILES = frozenset({"user.py", "session.py"})

    #: 扫描根：`app/`。
    @staticmethod
    def _app_root() -> Path:
        return Path(__file__).resolve().parent.parent / "app"

    @classmethod
    def _trees(cls) -> list[tuple[Path, ast.Module]]:
        return [
            (path, ast.parse(path.read_text(encoding="utf-8")))
            for path in sorted(cls._app_root().rglob("*.py"))
            if path.name != "notification.py"
        ]

    @classmethod
    def _call_sites(cls) -> dict[str, int]:
        """每个服务文件里 `x.publish_system_event(...)` 的调用次数。"""
        sites: dict[str, int] = {}
        for path, tree in cls._trees():
            count = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "publish_system_event"
            )
            if count:
                sites[path.name] = count
        return sites

    @classmethod
    def _referenced_codes(cls) -> set[str]:
        """调用点里出现过的全部 `SYSTEM_EVENTS[...]` 事件码字面量。"""
        codes: set[str] = set()
        for _path, tree in cls._trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                value = node.value
                if not (isinstance(value, ast.Name) and value.id == "SYSTEM_EVENTS"):
                    continue
                for inner in ast.walk(node.slice):
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                        codes.add(inner.value)
        return codes

    def test_only_expected_services_deliver(self) -> None:
        sites = self._call_sites()
        unexpected = set(sites) - self._ALLOWED_FILES
        assert not unexpected, f"以下服务新增了投递调用点，请确认是刻意的：{unexpected}"
        # 反方向：清单里的文件必须**真的**还在投递，否则这条护栏只是在数一个空集。
        assert set(sites) >= self._ALLOWED_FILES, (
            f"这些文件不再投递了：{self._ALLOWED_FILES - set(sites)}"
        )
        # 调用点总数钉住：少一处就是"某个业务动作不再通知用户了"。
        assert sites["user.py"] == 3, f"user.py 的投递调用点数变了：{sites['user.py']}"
        assert sites["session.py"] == 1, f"session.py 的投递调用点数变了：{sites['session.py']}"

    def test_every_catalog_event_has_a_call_site(self) -> None:
        """目录里的每个事件码都要有出处。

        孤儿事件码（写了文案却没人用）很容易出现：想好文案、加进目录、
        忘了接调用点 —— 读者会以为功能已经有了。
        """
        unused = set(SYSTEM_EVENTS) - self._referenced_codes()
        assert not unused, f"以下事件码在目录里但没有调用点：{unused}"

    def test_catalog_codes_are_not_invented_at_call_sites(self) -> None:
        """调用点只允许用目录里的码，不得自己拼一个字符串（运行期 `KeyError`）。"""
        invented = self._referenced_codes() - set(SYSTEM_EVENTS)
        assert not invented, f"调用了目录里不存在的事件码：{invented}"
