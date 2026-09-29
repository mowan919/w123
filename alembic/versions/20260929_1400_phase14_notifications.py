"""站内通知：公告定义表 + 收件箱表 —— `DESIGN-DECISIONS §32`。

Revision ID: phase14_notifications
Revises: phase13_session_presence

Spec 里没有这一域（`docs/spec/` 全 17 个文档零提及「消息 / 通知 / 公告」），
因此本迁移建的是**技术推导表**，口径见 `docs/DESIGN-DECISIONS.md §32`。

两张表的分工
-----------
- `announcements`：一次发布的**定义**（标题 / 正文 / 受众 / 发布人 / 收件人数）。
- `notifications`：**收件箱**（一行 = 一个收件人的一份消息），
  系统消息与公告扇出的行都存在这里，读路径只查它。

为什么用原生 DDL 建索引（与 phase11 / phase12 / phase13 同一约定）
----------------------------------------------------------------
环境的 `naming_convention` 会给 `op.create_index` 传入的名字再套一层前缀，
拼出的名字与模型里 `Index(..., name=...)` 不一致 —— 索引名对不上时
迁移能跑通、模型也对，但两边的元数据核对会永远对不齐。
部分索引（`postgresql_where`）尤其要小心：写成普通索引不会报错，
只会让"未读行"的索引体量随总量增长。这里用 `op.execute` 写完整 DDL，
名字与模型逐字一致，且 `if not exists` 保证幂等。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "phase14_notifications"
down_revision: str | None = "phase13_session_presence"
branch_labels: str | None = None
depends_on: str | None = None


def _has_table(conn: sa.Connection, name: str) -> bool:
    return (
        conn.execute(
            sa.text("select 1 from information_schema.tables where table_name = :n"),
            {"n": name},
        ).scalar()
        is not None
    )


def upgrade() -> None:
    conn = op.get_bind()
    # 幂等：表已存在就直接返回（本迁移可能被重复执行于已有库）。
    if _has_table(conn, "notifications"):
        return

    op.create_table(
        "announcements",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="Snowflake BIGINT 业务主键",
        ),
        sa.Column(sa.String(length=200), name="title", nullable=False, comment="公告标题"),
        sa.Column(
            sa.Text(),
            name="body",
            nullable=True,
            comment="公告正文（Markdown 不解析，纯文本展示）",
        ),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            comment="轻重 INFO / WARNING / IMPORTANT（仅影响展示）",
        ),
        sa.Column(
            "audience_type",
            sa.String(length=16),
            nullable=False,
            comment="受众类型 ALL（全员）/ ROLE（指定角色）",
        ),
        sa.Column(
            "audience_role_id",
            sa.BigInteger(),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=True,
            comment="受众角色 ID；audience_type=ROLE 时必填",
        ),
        sa.Column(
            "recipient_count",
            sa.Integer(),
            nullable=False,
            comment="发布那一刻的收件人数（历史事实，不用 count(*) 现算）",
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
            comment="发布人用户 ID；操作者被删除时置空（用户名快照仍在）",
        ),
        sa.Column(
            "created_by_username",
            sa.String(length=64),
            nullable=False,
            comment="发布人用户名快照（发布当时的名字，不随后续改名变化）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="创建时间 (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="更新时间 (UTC)",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="逻辑删除时间 (UTC)，NULL 表示未删除",
        ),
        sa.CheckConstraint(
            "level IN ('INFO', 'WARNING', 'IMPORTANT')",
            name="level",
        ),
        sa.CheckConstraint(
            "audience_type IN ('ALL', 'ROLE')",
            name="audience_type",
        ),
        # 受众完整性：选了 ROLE 就必须给角色，选了 ALL 就不能带角色。
        # 写成等价而不是"ROLE ⇒ 非空"，是为了同时挡住"ALL + 角色"这种
        # 自相矛盾的行 —— 它会让"到底发给了谁"有两个答案。
        sa.CheckConstraint(
            "(audience_type = 'ROLE') = (audience_role_id IS NOT NULL)",
            name="audience_role_consistent",
        ),
    )

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="Snowflake BIGINT 业务主键",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            # `RESTRICT`：本项目所有业务实体都是逻辑删除，一条 CASCADE 会让
            # "物理删掉用户"顺手抹掉他的收件箱历史（见 `tests/test_hardening.py`
            # 的 `test_no_cascade_foreign_keys`）。
            sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="收件人用户 ID",
        ),
        sa.Column(
            "category",
            sa.String(length=16),
            nullable=False,
            comment="分类 SYSTEM（服务端事件）/ ANNOUNCEMENT（管理员公告）",
        ),
        sa.Column(
            "event_code",
            sa.String(length=64),
            nullable=True,
            comment="系统事件码（如 SESSION_SUPERSEDED）；公告为 NULL",
        ),
        sa.Column(
            "announcement_id",
            sa.BigInteger(),
            # `RESTRICT` 与上面的 `announcement_link_consistent` CHECK 一起，
            # 让"物理删公告定义、留下无法追溯的收件箱行"在库层不可能发生。
            sa.ForeignKey("announcements.id", ondelete="RESTRICT"),
            nullable=True,
            comment="来源公告 ID；系统消息为 NULL",
        ),
        sa.Column(
            sa.String(length=200),
            name="title",
            nullable=False,
            comment="标题（界面上一眼看到的那一句）",
        ),
        sa.Column(
            sa.Text(),
            name="body",
            nullable=True,
            comment="正文；公告填写，系统消息可空",
        ),
        sa.Column(
            sa.String(length=255),
            name="link",
            nullable=True,
            comment="点击后的前端路由路径（如 /system/sessions）",
        ),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            comment="轻重 INFO / WARNING / IMPORTANT（仅影响展示）",
        ),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="已读时间 (UTC)；NULL = 未读",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="创建时间 (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="更新时间 (UTC)",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="逻辑删除时间 (UTC)，NULL 表示未删除",
        ),
        sa.CheckConstraint(
            "category IN ('SYSTEM', 'ANNOUNCEMENT')",
            name="category",
        ),
        sa.CheckConstraint(
            "level IN ('INFO', 'WARNING', 'IMPORTANT')",
            name="level",
        ),
        sa.CheckConstraint(
            "(category = 'ANNOUNCEMENT') = (announcement_id IS NOT NULL)",
            name="announcement_link_consistent",
        ),
        sa.CheckConstraint(
            "(category = 'SYSTEM') = (event_code IS NOT NULL)",
            name="event_code_consistent",
        ),
    )

    # 公告列表按时间倒序翻页。
    op.execute(
        "create index if not exists ix_announcements_created_active"
        " on announcements (created_at) where deleted_at is null"
    )
    # 收件箱主查询（user_id + 时间排序）。
    op.execute(
        "create index if not exists ix_notifications_user_created_active"
        " on notifications (user_id, created_at) where deleted_at is null"
    )
    # 角标未读数：只索引未读行，索引体量与未读量成正比而不是总量。
    op.execute(
        "create index if not exists ix_notifications_user_unread_active"
        " on notifications (user_id) where read_at is null and deleted_at is null"
    )
    # 事件码反查（"这个事件给他投过消息吗"）。
    op.execute(
        "create index if not exists ix_notifications_event_code_active"
        " on notifications (event_code) where deleted_at is null"
    )
    # 撤回公告时按来源批量处置收件箱行。
    op.execute(
        "create index if not exists ix_notifications_announcement_active"
        " on notifications (announcement_id) where deleted_at is null"
    )
    # SoftDeleteMixin 自带 index=True 的 deleted_at 普通索引。
    op.execute("create index if not exists ix_notifications_deleted_at on notifications (deleted_at)")
    op.execute("create index if not exists ix_announcements_deleted_at on announcements (deleted_at)")


def downgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, "notifications"):
        # 先删子表：`notifications.announcement_id` 上有外键指向 `announcements`。
        op.drop_table("notifications")
    if _has_table(conn, "announcements"):
        # 通知是**派生数据**：删掉只会让角标清零，不会丢失任何业务事实
        # （每条系统消息在审计里都有对应事件，公告的正文由发布者自己留存）。
        # 因此直接 drop，不做数据搬运 —— 与日志表不同，通知没有保留期义务。
        op.drop_table("announcements")
