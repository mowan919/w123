"""站内通知（收件箱）模型 —— `DESIGN-DECISIONS §32`。

Frozen 依据
-----------
本表**不在** `docs/spec/` 的任何文档里：全 17 个文档对「消息 / 通知 / 公告」
零提及。因此这一域整体属**技术推导**，由人类裁定后落地
（`docs/DESIGN-DECISIONS.md §32`，2026-09-29）：

```text
1、前端页面新增站内通知，如果有消息需要展示消息角标 在右上角个人中心那个位置
```

裁定：**后端真存储** + **系统事件与管理员公告都要** + **下拉面板 + 查看全部**。

为什么是"收件箱（fan-out on write）"而不是"公告表 + 已读回执"
---------------------------------------------------------
同一张表承载两类消息，每条消息**属于一个收件人**：

```text
一行 = 一个收件人的一份消息（收件人维度的行）
```

另一种做法是"公告只存一行 + 一张 `notification_reads` 回执表"，
两者在读路径上差别很大：

| | 收件箱（本实现） | 公告 + 回执 |
|---|---|---|
| 未读数 | `count(*) where user_id=? and read_at is null` | 需要"公告总数 − 我已读数"的联表 |
| 分页 | 单表按 `user_id` 分页 | `union` 系统消息与公告，再排序分页 |
| 已读语义 | 列就在行上 | 每个读写点都要"先找/建回执行" |
| 系统消息 | 天然同一张表 | 系统消息没有"公告行"，要么另建表要么塞进公告表 |

本项目的既有取向是**把"读"做得足够便宜**（收件箱是每次打开后台都要走的面），
因此选扇出。代价明确记录：一次全员公告会写入 N 行（N = 受众用户数）。
在本项目的规模下（后台管理面，用户以百/千计）这是可接受的；
真到需要百万级扇出时，正确的改法是"公告表 + 回执表 + 物化视图"，
那是一次**读路径重写**，不是本表加一列能解决的 —— 因此现在不预先复杂化。

为什么没有 `delivered_at` / `status` 之类的投递状态列
-------------------------------------------------
本表既是投递队列也是收件箱，投递发生在**与业务同一个事务**里
（见 `app/services/notification.py`）：事务提交即投递完成，
没有"投递中"这个中间态，因此没有可表达的状态。

`read_at` 为什么不是布尔 `is_read`
---------------------------------
时间比布尔多一个信息：**什么时候读的**。而定长 `read_at IS NULL`
是收件箱里最热的判定（未读数、未读筛选、角标），
布尔列无法表达"这条是什么时候被读掉的"，
而"某条安全消息在被告知后 3 秒还是 3 天才被读"在追责时是有差别的。

`link` 为什么存路径字符串而不是"类型 + ID"
----------------------------------------
通知要能跳回事发处（例如"你的会话被顶替了"跳到会话管理页）。
用"类型 + ID"意味着**每个新事件类型都要加一种跳转解析**，
并且跳转规则会分裂在前端与后端两处。存一个前端路由路径，
跳转规则就只有一个（前端的路由表），后端只需要写字符串。
代价：路径写错不会报错，只会跳到一个 404 —— 由
`tests/test_notification_api.py` 钉住每个 `event_code` 的 `link` 形状。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import enum_type
from app.models.enums import AnnouncementAudience, NotificationCategory, NotificationLevel

#: 标题长度上限。取 200：足够放下"你的账号已在其他设备登录"这类完整句子，
#: 又不至于让一条通知在面板里占满三行。
TITLE_LENGTH = 200
#: 事件码长度（`SESSION_SUPERSEDED` 这类常量名）。
EVENT_CODE_LENGTH = 64
#: 跳转路径长度（前端路由路径，最长的那条是 `/system/permission-resources`）。
LINK_LENGTH = 255
#: 正文长度上限。公告正文是有长度的文本，用 TEXT 而不是 VARCHAR(n)：
#: 定长上限会让"这条公告能不能发出去"取决于字数，
#: 而截断一封公告比拒绝发送更糟（收件人以为自己读到了全文）。
BODY_MAX_CHARS = 4000
#: 发布人用户名长度（与 `audit_logs.operator_username` 同口径的快照列）。
OPERATOR_USERNAME_LENGTH = 64


class Announcement(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """一次公告发布（**定义**，不含收件人）。

    为什么收件箱之外还要这张表
    -------------------------
    收件箱表（`notifications`）里一次全员公告是 N 行 ——
    从这 N 行**无法可靠地**还原"这是几次发布"：按 `(title, body, level)` 分组
    会把两次内容相同的发布并成一次（运营重复发同一句是常见操作）。

    更需要这张表的理由是**发布人**：收件箱行的 owner 是**收件人**，
    没有任何一列表达"谁发的"。而"这条公告是谁发的"是管理页面上的第一列。

    这张表也不参与收件人的读路径：收件箱列表 / 未读数只查 `notifications`。
    它只服务于两件事：管理页的已发布列表，以及将来的"撤回公告"
    （撤回 = 逻辑删除本行 + 按 `announcement_id` 逻辑删除对应的收件箱行）。

    为什么记 `recipient_count`（发布那一刻的收件人数）
    ----------------------------------------------
    它是**历史事实**而不是派生值：受众是动态的（明天会有新用户），
    用 `count(*)` 现算出来的是"今天还在的人里当时收到了几个"，
    与"发布时发给了几个人"不是一回事。发布后有人被删除时，
    后者才是审计问答要的数字。

    发布人为什么同时存 id 与用户名
    -----------------------------
    与 `audit_logs.operator_username` 同一理由：这是**历史快照**。
    用户之后被改名或逻辑删除时，公告的发布人应当仍是当时那个人，
    而不是变成空值或新名字 —— 那样一条"某管理员发过这条公告"的记录
    会随着人事变动失真。
    """

    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(TITLE_LENGTH), nullable=False, comment="公告标题")
    body: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="公告正文（Markdown 不解析，纯文本展示）"
    )
    level: Mapped[NotificationLevel] = mapped_column(
        enum_type(NotificationLevel, name="level"),
        nullable=False,
        default=NotificationLevel.INFO,
        comment="轻重 INFO / WARNING / IMPORTANT（仅影响展示）",
    )
    audience_type: Mapped[AnnouncementAudience] = mapped_column(
        enum_type(AnnouncementAudience, name="audience_type"),
        nullable=False,
        comment="受众类型 ALL（全员）/ ROLE（指定角色）",
    )
    audience_role_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=True,
        comment="受众角色 ID；audience_type=ROLE 时必填",
    )
    recipient_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="发布那一刻的收件人数（历史事实，不用 count(*) 现算）",
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="发布人用户 ID；操作者被删除时置空（用户名快照仍在）",
    )
    created_by_username: Mapped[str] = mapped_column(
        String(OPERATOR_USERNAME_LENGTH),
        nullable=False,
        comment="发布人用户名快照（发布当时的名字，不随后续改名变化）",
    )

    __table_args__ = (
        # 管理页按时间倒序翻页。
        Index(
            "ix_announcements_created_active",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 受众完整性：选了 ROLE 就必须给角色，选了 ALL 就不能带角色。
        # 写成**等价**而不是"ROLE ⇒ 非空"，是为了同时挡住"ALL + 角色"
        # 这种自相矛盾的行 —— 它会让"到底发给了谁"有两个答案。
        CheckConstraint(
            "(audience_type = 'ROLE') = (audience_role_id IS NOT NULL)",
            name="audience_role_consistent",
        ),
    )


class Notification(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """一条站内通知（一个收件人的一份消息）。

    语义边界（重要）：

    - 本表**不是**审计表的替代品。审计记录"谁做了什么"，
      通知记录"谁该被告知什么"。同一次操作可能两样都写
      （例如管理员重置口令 → 审计 `USER_RESET_PASSWORD` + 通知被重置的用户），
      但两者**没有**约束关系：审计是义务，通知是体验。
    - 因此本表可以逻辑删除、可以读、可以改 `read_at`；
      审计表不许 UPDATE / DELETE（`10 §8` append-only）。
    - 也**不**把敏感内容放进通知：通知会以明文出现在界面上，
      且没有脱敏管道（脱敏作用于日志，见 `app/core/masking.py`）。
      口令、令牌、MFA 密钥一律不得进 `title` / `body`。
    """

    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        # `RESTRICT` 而不是 `CASCADE` —— 与 `sessions` / `password_history` /
        # `user_roles` 同一条约定（见 `tests/test_hardening.py` 的
        # `test_no_cascade_foreign_keys`）。本项目所有业务实体都是**逻辑删除**，
        # 一条 CASCADE 会让"物理删掉用户"顺手抹掉他的收件箱历史，
        # 也就把"逻辑删除"这个不变量在数据库层打穿。
        # 代价：物理删除有邮件箱行的用户会被库层拒绝 —— 这正是想要的
        # （本项目从不物理删用户；确有合规要求时走保留期清理通道）。
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="收件人用户 ID",
    )
    category: Mapped[NotificationCategory] = mapped_column(
        enum_type(NotificationCategory, name="category"),
        nullable=False,
        comment="分类 SYSTEM（服务端事件）/ ANNOUNCEMENT（管理员公告）",
    )
    event_code: Mapped[str | None] = mapped_column(
        String(EVENT_CODE_LENGTH),
        nullable=True,
        comment="系统事件码（如 SESSION_SUPERSEDED）；公告为 NULL",
    )
    announcement_id: Mapped[int | None] = mapped_column(
        BigInteger,
        # 同样 `RESTRICT`，而且这里比 `user_id` 更必要：
        # 配合下面的 `announcement_link_consistent` CHECK（公告行必须有来源），
        # `RESTRICT` 让"物理删掉公告定义、留下一地无法追溯的收件箱行"
        # 在库层就不可能发生 —— 撤下公告只有**逻辑删除**（撤回）这一条路，
        # 而那条路会写审计。若改成 CASCADE，撤回就多了一条
        # "直接 delete 掉公告行"的静默旁路。
        ForeignKey("announcements.id", ondelete="RESTRICT"),
        nullable=True,
        comment="来源公告 ID；系统消息为 NULL",
    )
    title: Mapped[str] = mapped_column(
        String(TITLE_LENGTH),
        nullable=False,
        comment="标题（界面上一眼看到的那一句）",
    )
    body: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="正文；公告填写，系统消息可空",
    )
    link: Mapped[str | None] = mapped_column(
        String(LINK_LENGTH),
        nullable=True,
        comment="点击后的前端路由路径（如 /system/sessions）",
    )
    level: Mapped[NotificationLevel] = mapped_column(
        enum_type(NotificationLevel, name="level"),
        nullable=False,
        default=NotificationLevel.INFO,
        comment="轻重 INFO / WARNING / IMPORTANT（仅影响展示）",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="已读时间 (UTC)；NULL = 未读",
    )

    __table_args__ = (
        # 收件箱主查询：`where user_id = ? order by created_at desc`。
        # 复合索引（而不是只给 user_id）的理由：分页要排序，
        # 单列索引会让每次翻页都对候选行做一次排序。
        Index(
            "ix_notifications_user_created_active",
            "user_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 角标未读数：`count(*) where user_id = ? and read_at is null`。
        # 用**部分索引**（只索引未读行）而不是 (user_id, read_at) 全量索引：
        # 已读行会随时间无限增长，而它们对未读计数毫无用处 ——
        # 索引体量因此与"未读量"而不是"总量"成正比，
        # 而收件箱的未读量天然很小。
        Index(
            "ix_notifications_user_unread_active",
            "user_id",
            postgresql_where=text("read_at IS NULL AND deleted_at IS NULL"),
        ),
        # 事件码反查（"这个事件有没有给这个人投过消息"），供测试与运维核对。
        Index(
            "ix_notifications_event_code_active",
            "event_code",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 按来源公告反查（撤回公告时要按 `announcement_id` 批量逻辑删除收件箱行）。
        Index(
            "ix_notifications_announcement_active",
            "announcement_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 类别一致性：公告行必须有来源公告、系统消息行必须有事件码。
        # 两个方向都极易写漏，而漏掉的后果是"这行永远无法被归档/撤回，
        # 也无法回答它因何而来" —— 一条悬挂的通知。
        CheckConstraint(
            "(category = 'ANNOUNCEMENT') = (announcement_id IS NOT NULL)",
            name="announcement_link_consistent",
        ),
        CheckConstraint(
            "(category = 'SYSTEM') = (event_code IS NOT NULL)",
            name="event_code_consistent",
        ),
    )


__all__ = [
    "BODY_MAX_CHARS",
    "EVENT_CODE_LENGTH",
    "LINK_LENGTH",
    "OPERATOR_USERNAME_LENGTH",
    "TITLE_LENGTH",
    "Announcement",
    "Notification",
]
