"""phase 13 session presence & supersede

会话在线口径修订 + 新登录顶替旧会话（`DESIGN-DECISIONS §31`，人类裁定"两个都要"）。

背景
----
用户反馈"同一个用户显示多个 session 在线"。两个独立成因：

1. **在线判定不设空闲阈值**（INTERIM-4-04）：关掉标签页的会话要等
   7 天 refresh 过期才从"在线"里消失。阈值判定在 SQL 条件里完成
   （`SESSION_ONLINE_IDLE_WINDOW`），**不需要**本迁移改任何列；
2. **同一账号允许任意多个并发会话**：裁定改为"新登录顶替旧会话"，
   旧会话撤销原因需要新取值 `SUPERSEDED` ——
   而 `sessions.revoke_reason` 的取值域由 CHECK 约束
   `ck_sessions_revoke_reason`（`native_enum=False` 的 sa.Enum 生成）钉住，
   不改约束，签发顶替时会直接 `CheckViolation`。

本迁移只做一件事：把 `SUPERSEDED` 加入该 CHECK（幂等）。

往返说明
--------
`downgrade()` 会先把 `SUPERSEDED` 行改记为 `REVOKE_ALL` 再收窄约束 ——
这是**改写历史**，但方向是"系统顶替 → 管理员强制下线"，两者都属于
"会话被系统外力终结"，且 downgrade 本身就是罕见的运维动作；
若不这么做，带着 SUPERSEDED 行的库将无法降级。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "phase13_session_presence"
down_revision: str | None = "phase12_perm_resource_menu"
branch_labels: str | None = None
depends_on: str | None = None

#: 撤销原因取值域（与 `app.models.enums.SessionRevokeReason` 保持一致）。
_REASONS_WITH_SUPERSEDE = (
    "LOGOUT",
    "ADMIN_REVOKE",
    "REVOKE_ALL",
    "TOKEN_REUSE_DETECTED",
    "SUPERSEDED",
)
_REASONS_LEGACY = ("LOGOUT", "ADMIN_REVOKE", "REVOKE_ALL", "TOKEN_REUSE_DETECTED")

_CONSTRAINT = "ck_sessions_revoke_reason"


def _check_ddl(reasons: tuple[str, ...]) -> str:
    return f"check (revoke_reason IN ({', '.join(repr(r) for r in reasons)}))"


def _set_check(reasons: tuple[str, ...]) -> None:
    # 用原生 SQL 而不是 op.create_check_constraint：环境的 naming_convention
    # 会给约束名再套一层 `ck_` 前缀，拼出 `ck_sessions_ck_sessions_revoke_reason`。
    # 约束名必须与 phase4 建出的 `ck_sessions_revoke_reason` 一字不差。
    conn = op.get_bind()
    conn.execute(sa.text(f"alter table sessions drop constraint {_CONSTRAINT}"))
    ddl = f"alter table sessions add constraint {_CONSTRAINT} {_check_ddl(reasons)}"
    conn.execute(sa.text(ddl))


def upgrade() -> None:
    conn = op.get_bind()
    # 幂等：约束里已有 SUPERSEDED 就不动（与 phase11/12 同一约定）。
    current = conn.execute(
        sa.text(
            "select pg_get_constraintdef(oid) from pg_constraint"
            " where conname = :name and conrelid = 'sessions'::regclass"
        ),
        {"name": _CONSTRAINT},
    ).scalar()
    if current is not None and "SUPERSEDED" in current:
        return

    _set_check(_REASONS_WITH_SUPERSEDE)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "update sessions set revoke_reason = 'REVOKE_ALL' where revoke_reason = 'SUPERSEDED'"
        )
    )
    _set_check(_REASONS_LEGACY)
