"""phase 12 permission resource menu

给「权限资源」页补上导航入口。

问题
----
`permission_resources` 里有 PAGE `system:permission-resource:page`
（`/system/permission-resources`，前端组件 `system/permission-resource`），
但**没有任何 MENU 挂载它** —— `MENUS` 里整条 `system:permission-resource`
都不存在。两层后果：

  1. 侧边栏没有入口。路由本身是有的（前端动态路由按 **PAGE 契约**生成，
     不看菜单），所以手敲 URL 能进 —— 表现为"这页能用，但没人找得到它"；
  2. 权限配置页的授权树把它归进「未挂载菜单的页面」分组，
     看起来像数据坏了，实际只是少了一行菜单。

本迁移做三件事（幂等）
----------------------
  1. 插入 MENU 资源 `system:permission-resource`，挂在 `system:system` 下，
     `sort_order = 55`（夹在「权限配置」50 与「会话管理」60 之间）；
  2. 建立 `menu_pages` 关联（该菜单 → 该页面）；
  3. 给**已经持有该 PAGE** 的角色补上该 MENU 的授权。

第 3 步为什么不可省
------------------
`PermissionContractService._load_binary_resources` 对非 SUPER_ADMIN 走
`role_permissions` 授权 ID → 资源行。菜单不授权，`menus` 里就没有它，
侧栏依然不显示 —— 也就是说"建了菜单行"本身**不足以**让入口出现。
SUPER_ADMIN 走的是"该类型全部有效资源"的集中式 bypass，因此不受影响；
这一步真正兜住的是自定义角色（把某个页面授给某角色、却没同时授菜单）。

空库（尚未 seed）时本迁移是 no-op
-------------------------------
只在「PAGE `system:permission-resource:page` 已存在」时才动手。否则在
"迁移先跑、seed 后跑"的全新部署里会出现两条各自创建该菜单行的路径，
`uq_permission_resources_type_code_active` 会让 seed 直接失败。
（与 `phase11_log_menu_group` 同一约定。）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "phase12_perm_resource_menu"
down_revision: str | None = "phase11_log_menu"
branch_labels: str | None = None
depends_on: str | None = None

#: 新增菜单的固定 ID。
#:
#: 取固定值而不是调用 Snowflake 生成器：迁移必须在**任何**部署形态下可重复
#: 执行且结果确定，而 Snowflake 依赖 worker / datacenter 配置。
#: `720001` 落在生成器输出范围之外（最小输出 `1 << 22 = 4194304`），
#: 不会与真实资源 ID 撞号 —— 与 Phase 7 的 `700001`、Phase 11 的 `710001`
#: 同一做法。
_SEED_MENU_ID = 720001

_MENU_CODE = "system:permission-resource"
_MENU_NAME = "权限资源"
_MENU_ICON = "permission-resource"
_MENU_SORT = 55
_PARENT_MENU_CODE = "system:system"
_PAGE_CODE = "system:permission-resource:page"

# ---------------------------------------------------------------- SQL
#
# 抽成模块常量而不是内联在 `upgrade()` 里：这两条语句的**行为**（幂等、
# 参数类型、保留语义）只有在真库上跑一遍才算验证过，而 `op.get_bind()`
# 需要一个 Alembic 上下文。把 SQL 提出来，验证脚本就能拿同一个字符串
# 在普通事务里执行 —— 测的是**将要上线的那一句**，不是它的副本。

#: 建立「菜单 → 页面」关联；已存在则不动。
#:
#: 两处 `CAST` 不是装饰：`SELECT :menu_id, ...` 里的裸参数**没有**类型上下文，
#: PostgreSQL 会直接报 `could not determine data type of parameter`。
#: 子查询里的比较虽然给了类型，但同一参数在列表里先出现，不能指望它被回填。
SQL_LINK_MENU_PAGE = (
    "INSERT INTO menu_pages (menu_id, page_id, created_at) "
    "SELECT CAST(:menu_id AS bigint), CAST(:page_id AS bigint), now() "
    "WHERE NOT EXISTS ("
    "  SELECT 1 FROM menu_pages WHERE menu_id = :menu_id AND page_id = :page_id"
    ")"
)

#: 给**已经持有该 PAGE** 的角色补上该 MENU 的授权；已有则不动。
#:
#: 这一步不可省：`PermissionContractService._load_binary_resources` 对非
#: SUPER_ADMIN 走 `role_permissions` 授权 ID → 资源行。菜单不授权，
#: `menus` 里就没有它，侧栏依然不显示 —— 也就是说"建了菜单行"本身
#: **不足以**让入口出现。SUPER_ADMIN 走集中式 bypass，因此不受影响。
SQL_GRANT_MENU_TO_PAGE_HOLDERS = (
    "INSERT INTO role_permissions (role_id, resource_id, created_at) "
    "SELECT granted.role_id, CAST(:menu_id AS bigint), now() "
    "FROM role_permissions granted "
    "WHERE granted.resource_id = :page_id "
    "  AND NOT EXISTS ("
    "    SELECT 1 FROM role_permissions existing "
    "    WHERE existing.role_id = granted.role_id "
    "      AND existing.resource_id = :menu_id"
    "  )"
)


def _live_resource_id(bind: sa.engine.Connection, resource_type: str, code: str) -> int | None:
    """按 `(resource_type, resource_code)` 取一个未删除的资源 ID。"""
    value = bind.execute(
        sa.text(
            "SELECT id FROM permission_resources "
            "WHERE resource_type = :resource_type AND resource_code = :code "
            "AND deleted_at IS NULL"
        ),
        {"resource_type": resource_type, "code": code},
    ).scalar()
    return None if value is None else int(value)


def upgrade() -> None:
    bind = op.get_bind()

    page_id = _live_resource_id(bind, "PAGE", _PAGE_CODE)
    parent_id = _live_resource_id(bind, "MENU", _PARENT_MENU_CODE)
    # 库还没 seed 过：交给 `seed_init.py`，它的清单里这棵树本来就是对的。
    if page_id is None or parent_id is None:
        return

    menu_id = _live_resource_id(bind, "MENU", _MENU_CODE)
    if menu_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO permission_resources "
                "(id, resource_type, resource_code, resource_name, parent_id, sort_order, "
                " status, route_path, component_path, icon, api_method, api_path, field_key, "
                " owner_resource_id, created_at, updated_at) "
                "VALUES (:id, 'MENU', :code, :name, :parent_id, :sort_order, 'ACTIVE', "
                " NULL, NULL, :icon, NULL, NULL, NULL, NULL, now(), now())"
            ),
            {
                "id": _SEED_MENU_ID,
                "code": _MENU_CODE,
                "name": _MENU_NAME,
                "parent_id": parent_id,
                "sort_order": _MENU_SORT,
                "icon": _MENU_ICON,
            },
        )
        menu_id = _SEED_MENU_ID

    # 关联用 `WHERE NOT EXISTS` 而不是 `ON CONFLICT`：`menu_pages` 的主键是
    # `(menu_id, page_id)`，但显式写条件让"已存在就跳过"这件事在 SQL 里可读，
    # 也免得依赖具体是哪个约束名兜底。
    bind.execute(sa.text(SQL_LINK_MENU_PAGE), {"menu_id": menu_id, "page_id": page_id})

    bind.execute(
        sa.text(SQL_GRANT_MENU_TO_PAGE_HOLDERS),
        {"menu_id": menu_id, "page_id": page_id},
    )


def downgrade() -> None:
    bind = op.get_bind()

    menu_id = _live_resource_id(bind, "MENU", _MENU_CODE)
    if menu_id is None:
        return

    # 只删**本迁移建的那一行**。若这个编码下已有别的行（管理员手工建过，
    # 或 seed 在新环境里建的），擅自删除会把它的授权一起带走 ——
    # 那种情况下留着即可，最多是"多一个同编码菜单"的无害冗余。
    if menu_id != _SEED_MENU_ID:
        return

    # 先删授权与关联，再删资源行：两处外键都是 `ondelete="RESTRICT"`，
    # 顺序反了会直接报外键冲突（而不是安静地删一半）。
    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE resource_id = :id"),
        {"id": _SEED_MENU_ID},
    )
    bind.execute(
        sa.text("DELETE FROM menu_pages WHERE menu_id = :id"),
        {"id": _SEED_MENU_ID},
    )
    bind.execute(
        sa.text("DELETE FROM permission_resources WHERE id = :id"),
        {"id": _SEED_MENU_ID},
    )
