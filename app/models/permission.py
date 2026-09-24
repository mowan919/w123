"""权限域模型：资源定义、资源授权、字段授权、权限版本。

Frozen / 已裁定依据
------------------
- Spec `00 §3` / `03 §5~§9`：权限链 Page / Menu / Button / API / Field / Data Scope。
- Spec `00 §1#4` / `03 §6` / `09 §4`：一个 Menu 可关联**多个** Page；
  Menu 负责导航组织，Page 负责页面访问权限。
- Spec `03 §8` / `08 §10`：API Permission 是后端强制授权，不能只依赖前端隐藏。
- Spec `03 §9` / `00 §3`：Field 权限四级 VISIBLE / HIDDEN / READ_ONLY / EDITABLE，
  最终字段策略必须由后端统一计算后输出。
- Spec `07 §5`：核心表含 `role_permissions`。
- Spec `07 §9`：必须检查 FK / index / unique / soft-delete-aware unique / parent-child index。
- Spec `09 §2`：`/auth/permissions` 必须返回 permission version。
- Spec `11 §2` / `§3`：权限修改必须递增 version 并使旧缓存失效；权限修改属并发保护重点。
- **DD-20 已冻结（方案 A）**：统一 `permission_resources` 表 + 显式类型专属列 + CHECK
  + 独立 `menu_pages` 关联表 + 统一 `role_permissions`；
  `resource_code` **按类型**做逻辑删除感知唯一。
- **DD-06 已冻结（方案 A）**：专用 `role_field_permissions` 表承载四级取值；
  多角色合并取**最宽松者胜**。
- **DD-04 仍未冻结**：`permission_versions` 只提供**单调递增**的取值能力，
  Redis Key 命名与缓存失效机制留待 Phase 9；表结构与 `scope` 命名登记为 INTERIM。

设计取舍说明（为什么用显式列而非 JSONB）
--------------------------------------
`api_method` / `api_path` 属于**安全关键字段**，一旦被静默写错就会出现
"以为已授权、实际未授权"或反之。JSONB 会把这类约束退到应用层，
因此 DD-20 选择显式列 + CHECK：数据库自身就能拒绝形状非法的资源行。
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import (
    FieldAccessLevel,
    HttpMethod,
    PermissionResourceType,
    PermissionStatus,
)

#: 权限资源"类型 → 该类型**必须非空**的专属列"（DD-20 冻结）。
TYPE_REQUIRED_COLUMNS: dict[PermissionResourceType, tuple[str, ...]] = {
    PermissionResourceType.PAGE: ("route_path", "component_path"),
    PermissionResourceType.MENU: (),
    PermissionResourceType.BUTTON: ("parent_id",),
    PermissionResourceType.API: ("api_method", "api_path"),
    PermissionResourceType.FIELD: ("field_key", "owner_resource_id"),
}

#: 权限资源"类型 → 该类型**允许出现**（可空可不空）的专属列"（DD-20 冻结）。
#:
#: 未列入 required 也未列入 optional 的类型专属列，必须为 NULL ——
#: 这样"给 PAGE 行塞 api_path"这类形状错误会被数据库直接拒绝。
TYPE_OPTIONAL_COLUMNS: dict[PermissionResourceType, tuple[str, ...]] = {
    # MENU 可嵌套（导航层级），因此 parent_id 允许为空也允许指向父 MENU；
    # icon 是 MENU 的专属列，但并非每个菜单都配图标，故为可空。
    PermissionResourceType.MENU: ("parent_id", "icon"),
    # API 可挂在某个 PAGE 下，也可独立存在（全局接口）。
    PermissionResourceType.API: ("parent_id",),
}

#: 需要参与"类型专属列形状"校验的全部列（含 parent_id）。
_TYPE_SCOPED_COLUMNS: tuple[str, ...] = (
    "parent_id",
    "route_path",
    "component_path",
    "icon",
    "api_method",
    "api_path",
    "field_key",
    "owner_resource_id",
)


#: 形状约束各"类型子句"之间的连接符。
#:
#: 必须是 **`AND`**，不能是 `OR`。
#:
#: 每个子句都是一条**蕴含式** `resource_type <> 'T' OR (T 的列形状)`：
#: 对不属于 `T` 的行恒真，因此要想约束住"每一种类型"，所有子句必须**同时**成立。
#: 若用 `OR` 连接，则对任意一行，只要存在**一个**不等于该行类型的 `T`
#: （五类资源里必然存在），对应子句就恒真，整条约束随之恒真 ——
#: 约束**完全失效**，而且**任何数据都不会报错**。
#:
#: 这不是假想风险：本约束的第一版正是用 `OR` 连接的，单测检出了它
#: （`TestShapeCheckExpression::test_clauses_are_conjoined_by_and` 与
#: `TestResourceShapeConstraints` 的数据库拒绝用例）。
#: 之所以单独抽成常量，是为了让测试可以引用同一处定义，
#: 避免"测试跟着缺陷改"（当时测试就是按 `OR` 切分的，从而放过了缺陷）。
SHAPE_CLAUSE_SEPARATOR = "\n      AND "


def _build_type_shape_check() -> str:
    """构造"资源类型 ↔ 专属列形状"的 SQL 校验表达式。

    对每一种类型 `T`，生成形如::

        (resource_type <> 'T' OR (必须非空的列 IS NOT NULL
                                  AND 其余列 IS NULL))

    即"**只有当资源确实属于该类型时**，列形状才必须成立"；
    对不属于该类型的行，这一支恒真，由其余子句负责约束。
    `TYPE_OPTIONAL_COLUMNS` 中列出的列**不参与** IS NULL 断言（可为空可不空）。

    ⚠️ 两个方向都极易写错，且写错后都**不会在任何正常数据上暴露**：

    1. **子句内部**若写成 `resource_type <> 'PAGE' AND route_path IS NOT NULL`，
       语义会反转成"**不是** PAGE 的行必须有路由"，与意图完全相反；
    2. **子句之间**若用 `OR` 连接（见 `SHAPE_CLAUSE_SEPARATOR` 的说明），
       整条约束退化为恒真，等于完全没有约束。

    两类缺陷都属于"看起来生效、实际上没保护"，因此下方生成逻辑只有一处，
    并有专门测试钉住两个方向。

    生成 SQL 而非手写，是为了让"类型 ↔ 列"的对应关系在代码里**唯一一份**，
    避免手写时漏掉某个类型。生成的表达式会原样进入 Alembic 迁移，可审查。
    """
    clauses: list[str] = []
    for resource_type in PermissionResourceType:
        required = TYPE_REQUIRED_COLUMNS[resource_type]
        optional = TYPE_OPTIONAL_COLUMNS.get(resource_type, ())
        conditions = [
            f"{column} IS NOT NULL" if column in required else f"{column} IS NULL"
            for column in _TYPE_SCOPED_COLUMNS
            if column not in optional
        ]
        clauses.append(
            f"(resource_type <> '{resource_type.value}' OR ({' AND '.join(conditions)}))"
        )
    return SHAPE_CLAUSE_SEPARATOR.join(clauses)


#: `permission_resources` 的类型形状约束（DD-20 冻结）。
PERMISSION_RESOURCE_TYPE_SHAPE_CHECK = _build_type_shape_check()

#: API 资源允许的 HTTP 方法（DD-20 冻结取值域）。
_HTTP_METHOD_VALUES = ", ".join(f"'{method.value}'" for method in HttpMethod)


class PermissionResource(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """权限资源（Page / Menu / Button / API / Field 的统一载体）。

    树形结构
    --------
    `parent_id` 自引用（邻接表）：
    - `MENU → MENU`：导航层级，可嵌套；
    - `BUTTON → PAGE`：按钮属于某个页面；
    - `API → PAGE`：接口可挂在页面上（也可不挂，`parent_id` 为 NULL）；
    - `FIELD → PAGE`：字段归属通过 `owner_resource_id` 表达（**不是** `parent_id`）。

    为什么 FIELD 用 `owner_resource_id` 而不是 `parent_id`
    ---------------------------------------------------
    `parent_id` 语义是"权限树上的父子"，参与树遍历；
    字段对页面的关系是"归属"而非"层级"，混用会让"展开页面子树"
    把字段一并带出，污染树结构。因此分成两列，语义各自明确。

    应用层必须保证的跨行不变量（FK 无法表达）
    ----------------------------------------
    1. `BUTTON.parent_id` 指向的资源必须是 `PAGE`；
    2. `MENU.parent_id` 指向的资源必须是 `MENU`；
    3. `API.parent_id`（若非空）指向的资源必须是 `PAGE`；
    4. `FIELD.owner_resource_id` 指向的资源必须是 `PAGE`。
    """

    __tablename__ = "permission_resources"

    resource_type: Mapped[PermissionResourceType] = mapped_column(
        enum_type(PermissionResourceType, name="resource_type", length=16),
        nullable=False,
        comment="资源类型 PAGE / MENU / BUTTON / API / FIELD（Spec 00 §3）",
    )
    resource_code: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="资源编码；业务唯一键，(resource_type, resource_code) 逻辑删除感知唯一",
    )
    resource_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="资源名称（前端展示）",
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        nullable=True,
        comment="父资源 ID（权限树）；BUTTON 必须非空，PAGE/API/FIELD 必须为空",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="同级排序值",
    )
    status: Mapped[PermissionStatus] = mapped_column(
        enum_type(PermissionStatus),
        nullable=False,
        default=PermissionStatus.ACTIVE,
        server_default=PermissionStatus.ACTIVE.value,
        comment="资源状态；DISABLED 的资源不参与有效权限计算",
    )

    # ---- PAGE 专属 ----
    route_path: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="PAGE 专属：前端路由路径",
    )
    component_path: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="PAGE 专属：前端组件路径",
    )
    # ---- MENU 专属 ----
    icon: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="MENU 专属：导航图标",
    )
    # ---- API 专属 ----
    api_method: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="API 专属：HTTP 方法（DD-20 冻结取值域）",
    )
    api_path: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="API 专属：接口路径（保留 {id} 占位）；仅作资源台账，不作为判权主键",
    )
    # ---- FIELD 专属 ----
    field_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="FIELD 专属：字段名（如 phone / email）",
    )
    owner_resource_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        nullable=True,
        comment="FIELD 专属：所属 PAGE 资源 ID（应用层保证类型为 PAGE）",
    )

    __table_args__ = (
        # 逻辑删除感知唯一（Spec 00 §6 / 07 §9）：删除后可重建同 code 资源。
        # 唯一范围是 (resource_type, resource_code) —— DD-20 冻结"按类型唯一"。
        Index(
            "uq_permission_resources_type_code_active",
            "resource_type",
            "resource_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # parent-child index（Spec 07 §9）
        Index(
            "ix_permission_resources_parent_id_active",
            "parent_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_permission_resources_type_status_active",
            "resource_type",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # FIELD 必须能按所属页面反查（字段权限输出时按页面聚合）
        Index(
            "ix_permission_resources_owner_resource_id_active",
            "owner_resource_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            PERMISSION_RESOURCE_TYPE_SHAPE_CHECK,
            name="resource_type_fields",
        ),
        CheckConstraint(
            f"api_method IS NULL OR api_method IN ({_HTTP_METHOD_VALUES})",
            name="api_method_domain",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="parent_not_self",
        ),
        CheckConstraint(
            "owner_resource_id IS NULL OR owner_resource_id <> id",
            name="owner_not_self",
        ),
    )


class MenuPage(Base):
    """Menu → Page 多对多关联（`00 §1#4` / `03 §6` 冻结）。

    为什么必须是独立表而不是 `parent_id`
    ---------------------------------
    `parent_id` 只能表达"单亲"。而一个 Page 可以被多个 Menu 引用
    （同一页面出现在不同导航分组下），因此必须用多对多关联表。

    方向（`09 §4` 冻结）：Menu 负责导航组织，Page 负责页面访问权限。
    因此**授权与判权只认 Page**，Menu 仅决定导航可见性。

    应用层不变量：`menu_id` 指向 MENU，`page_id` 指向 PAGE（FK 无法表达类型）。
    """

    __tablename__ = "menu_pages"

    menu_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="MENU 资源 ID",
    )
    page_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="PAGE 资源 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="关联建立时间 (UTC)",
    )


class RolePermission(Base):
    """角色 → 权限资源授权（`07 §5` 核心表 `role_permissions`）。

    只承载"有 / 无"二元授权：PAGE / MENU / BUTTON / API 四类走本表。
    FIELD 因需要四级取值，走 `role_field_permissions`（DD-06 冻结）。
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="角色 ID",
    )
    resource_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="权限资源 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="授权时间 (UTC)",
    )


class RoleFieldPermission(Base):
    """角色 → 字段资源授权（DD-06 已冻结：专用表 + 四级取值）。

    为什么不复用 `role_permissions`
    ----------------------------
    `03 §9` 的字段权限是**四级有序取值**，不是"有 / 无"。
    用二元表承载会丢失等级信息（等于把 HIDDEN 与 EDITABLE 视为相同），
    直接违反"最终字段策略需要由后端统一计算"的冻结要求。

    合并规则（DD-06 冻结）：同一字段被多角色授予不同等级时取**最宽松者胜**，
    序为 HIDDEN < READ_ONLY < VISIBLE < EDITABLE。该方向与 `00 §1#2`
    "权限取并集"同向；注意此约束下 HIDDEN **不能**覆盖其他角色的 VISIBLE。
    """

    __tablename__ = "role_field_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="角色 ID",
    )
    field_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("permission_resources.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="FIELD 资源 ID",
    )
    access_level: Mapped[FieldAccessLevel] = mapped_column(
        enum_type(FieldAccessLevel, name="access_level"),
        nullable=False,
        comment="字段权限等级 VISIBLE / HIDDEN / READ_ONLY / EDITABLE",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="授权时间 (UTC)",
    )


class PermissionVersion(Base):
    """权限版本计数器（单调递增）。

    用途（Spec `09 §2` / `11 §2`）
    ----------------------------
    `/auth/permissions` 必须返回 permission version；权限修改必须
    递增版本并使旧缓存失效（`11 §2` 第 2 步）。

    Phase 3 的裁定
    -------------
    人类已裁定：Phase 3 **不启用 Redis 权限缓存**，权限上下文每请求实时计算。
    因此本表只提供"**单调递增的取值能力**"，缓存失效机制与 Redis Key
    命名留待 Phase 9（DD-03 / DD-04 未冻结）。

    INTERIM（DD-04 未冻结）
    --------------------
    - `scope` 取值的命名规范（此处仅使用 `GLOBAL`）尚未冻结；
    - 是否按用户 / 按角色分桶尚未冻结；
    - 递增时机（哪些写操作算"权限修改"）尚未冻结，当前取
      "任何改变权限配置的写操作"这一保守口径。

    并发安全（Spec `11 §3`：权限修改属并发保护重点）
    ---------------------------------------------
    递增使用 `UPDATE ... SET version = version + 1`（行级锁），
    绝不是"读出来 +1 再写回"。后者在并发下会产生重复版本号，
    使缓存失效判断失效。
    """

    __tablename__ = "permission_versions"

    scope: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="版本桶标识；Phase 3 仅使用 GLOBAL（DD-04 未冻结其命名规范）",
    )
    version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="单调递增版本号",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        comment="最后递增时间 (UTC)",
    )


__all__ = [
    "PERMISSION_RESOURCE_TYPE_SHAPE_CHECK",
    "SHAPE_CLAUSE_SEPARATOR",
    "TYPE_OPTIONAL_COLUMNS",
    "TYPE_REQUIRED_COLUMNS",
    "MenuPage",
    "PermissionResource",
    "PermissionVersion",
    "RoleFieldPermission",
    "RolePermission",
]
