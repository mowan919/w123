"""phase 11 log menu group

把「审计日志」与「链路查询」从「系统管理」下移出，归入一个新的顶级菜单
「日志管理」。这是一次**导航结构**调整，不改动任何授权数据：

  - 新增一个 MENU 资源 `log:manage`（顶层，不关联任何 PAGE —— 它是分组标题）；
  - 把 `system:audit-log` / `system:trace` 两个 MENU 的 `parent_id` 指到它，
    `sort_order` 归为 210 / 220。

为什么不改这两个菜单的 `resource_code`
------------------------------------
`resource_code` 是**权限标识**：`role_permissions` 按 ID 授权，前端
`AppSidebar.ICON_BY_CODE` 按编码解析图标。把 `system:audit-log` 改成
`log:audit-log` 不会带来任何用户可见的变化，却要求同步改动图标映射与全部
引用点（`scripts/seed_data.py`、前端 fixtures）。本轮只调整层级，编码保持
稳定。登记为 INTERIM-23-01（`docs/DESIGN-DECISIONS.md` §23.2）。

为什么是迁移而不是只改种子脚本
----------------------------
`scripts/seed_data.py` 的写入是幂等的（按 `(resource_type, resource_code)`
先查后写），因此它**不会**修正存量库里已经写好的 `parent_id`。要让已经部署
的环境（含共享开发库）拿到新结构，必须走一次数据迁移。种子清单同步更新，
新装环境从源头就是对的 —— 两边描述同一棵树。

空库（尚未 seed）时本迁移是 no-op
-------------------------------
新增行只在「日志菜单已存在」时才写。否则在"迁移先跑、seed 后跑"的全新部署
里，会出现两条各自创建 `log:manage` 的路径（迁移建的行与种子的行），
`uq_permission_resources_type_code_active` 会让 seed 直接失败。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "phase11_log_menu"
down_revision: str | None = "phase7_dict"
branch_labels: str | None = None
depends_on: str | None = None

#: 新增顶级菜单的固定 ID。
#:
#: 取固定值而不是调用 Snowflake 生成器：迁移文件必须在**任何**部署形态下
#: 可重复执行且结果确定，而 Snowflake 依赖 worker/datacenter 配置。
#: `710001` 落在生成器输出范围之外（最小输出 `1 << 22 = 4194304`），
#: 因此不会与真实资源 ID 撞号 —— 与 Phase 7 的 `700001` 同一做法。
_SEED_LOG_MENU_ID = 710001

#: 新分组的编码与名称。
_LOG_MENU_CODE = "log:manage"
_LOG_MENU_NAME = "日志管理"
#: 新分组在**根层**的排序值。`系统管理` 是 10，它排在后面。
_LOG_MENU_SORT = 200

#: 要搬迁到新分组的菜单：(业务编码, 在新分组内的排序值)。
_LOG_MENU_CHILDREN: tuple[tuple[str, int], ...] = (
    ("system:audit-log", 210),
    ("system:trace", 220),
)

#: 它们原来挂在哪、顺序是多少（`downgrade` 要原样还回去）。
_ORIGINAL_PARENT_CODE = "system:system"
_ORIGINAL_SORTS: dict[str, int] = {"system:audit-log": 90, "system:trace": 100}


def _live_menu_id(bind: sa.engine.Connection, code: str) -> int | None:
    """按业务编码取一个未删除的 MENU 资源 ID。"""
    value = bind.execute(
        sa.text(
            "SELECT id FROM permission_resources "
            "WHERE resource_type = 'MENU' AND resource_code = :code AND deleted_at IS NULL"
        ),
        {"code": code},
    ).scalar()
    return None if value is None else int(value)


def upgrade() -> None:
    bind = op.get_bind()

    children = {code: _live_menu_id(bind, code) for code, _ in _LOG_MENU_CHILDREN}
    # 库还没 seed 过（全新部署）：交给 `seed_init.py`，它在种子清单里
    # 直接就把这棵树建对，迁移不该在这里抢先把行建出来。
    if any(menu_id is None for menu_id in children.values()):
        return

    log_menu_id = _live_menu_id(bind, _LOG_MENU_CODE)
    if log_menu_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO permission_resources "
                "(id, resource_type, resource_code, resource_name, parent_id, sort_order, "
                " status, route_path, component_path, icon, api_method, api_path, field_key, "
                " owner_resource_id, created_at, updated_at) "
                "VALUES (:id, 'MENU', :code, :name, NULL, :sort_order, 'ACTIVE', "
                " NULL, NULL, 'log', NULL, NULL, NULL, NULL, now(), now())"
            ),
            {
                "id": _SEED_LOG_MENU_ID,
                "code": _LOG_MENU_CODE,
                "name": _LOG_MENU_NAME,
                "sort_order": _LOG_MENU_SORT,
            },
        )
        log_menu_id = _SEED_LOG_MENU_ID

    # 逐条搬迁：`id` 是主键，逐条写让"哪一条没搬成功"在 SQL 里可见，
    # 而不是一条 `IN (...)` 静默改掉两个。
    for code, sort_order in _LOG_MENU_CHILDREN:
        bind.execute(
            sa.text(
                "UPDATE permission_resources "
                "SET parent_id = :parent_id, sort_order = :sort_order, updated_at = now() "
                "WHERE resource_type = 'MENU' AND resource_code = :code AND deleted_at IS NULL"
            ),
            {"parent_id": log_menu_id, "sort_order": sort_order, "code": code},
        )


def downgrade() -> None:
    bind = op.get_bind()

    original_parent_id = _live_menu_id(bind, _ORIGINAL_PARENT_CODE)
    for code, _ in _LOG_MENU_CHILDREN:
        bind.execute(
            sa.text(
                "UPDATE permission_resources "
                "SET parent_id = :parent_id, sort_order = :sort_order, updated_at = now() "
                "WHERE resource_type = 'MENU' AND resource_code = :code AND deleted_at IS NULL"
            ),
            {
                "parent_id": original_parent_id,
                "sort_order": _ORIGINAL_SORTS[code],
                "code": code,
            },
        )

    log_menu_id = _live_menu_id(bind, _LOG_MENU_CODE)
    # 只删**本迁移建的那一行**。若这个编码下已有别的行（管理员手工建过），
    # 擅自删除会把它的授权一起带走 —— 那种情况下退回结构即可，行留着。
    if log_menu_id == _SEED_LOG_MENU_ID:
        bind.execute(
            sa.text("DELETE FROM permission_resources WHERE id = :id"),
            {"id": _SEED_LOG_MENU_ID},
        )
