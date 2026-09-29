"""初始数据清单的**唯一来源**（`docs/spec/16 §完整性检查` 的类目）。

为什么是"唯一来源"
------------------
这些数据最早只存在于 `seed_e2e.py` 里。E2E 种子与"新环境初始化"需要的
几乎是同一份骨架（部门 / 角色 / 权限资源 / 授权映射），两份各写一份必然
随时间漂移 —— 而且漂移是**静默**的：`seed_e2e.py` 的模块文档里已经记过
一次事故，APIS 里写的是自造编码 `api:user:list`，没有任何端点认它，
后果是"授权界面上明明勾了、角色照样 403"，报错信息还只说"缺少 USER_MANAGE"。

因此把清单搬到本模块，`seed_e2e.py` 与 `seed_init.py` 都从这里 import。
**新增 / 修改资源编码只改这一处。**

取值约定（与后端契约一致，改之前先看对应模块的文档）：
- 资源编码沿用 `permission_resources.resource_code`；
- PAGE 必须同时具备 `route_path` 与 `component_path`
  （`ck_permission_resources_resource_type_fields` 的冻结要求，
  前端 `generateRoutes` 也只认 `component_path`）；
- 按钮权限用 `role_field_permissions.access_level` 四级取值（DD-06）；
- 数据范围写 `roles.data_scope`（DD-07）；
- API 的 code 必须与 `app.services.authorization.ApiPermissionCode` 逐字一致；
- API 的 path 是**后端完整路由去掉 `settings.api_v1_prefix` 之后**的相对路径。
  `settings.api_v1_prefix` 已经是 `/api/v1/admin`（`app/core/config.py`），
  因此这里写 `/users` 而不是 `/admin/users` —— 写错不会报错，只会让台账
  指向一个不存在的端点（`tests/test_seed_data.py` 钉住了这一条）；
- 口令策略唯一判定点是 `app.core.security.password.validate_password_policy`。
"""

from __future__ import annotations

from app.core.scope import DataScope
from app.models.enums import FieldAccessLevel

# ---------------------------------------------------------------- 组织与角色

#: (code, name, parent_code)
DEPARTMENTS: list[tuple[str, str, str | None]] = [
    ("ROOT", "集团", None),
    ("TECH", "技术部", "ROOT"),
    ("MARKET", "市场部", "ROOT"),
]

#: (code, name, data_scope, description)
ROLES: list[tuple[str, str, DataScope, str]] = [
    ("SUPER_ADMIN", "超级管理员", DataScope.ALL, "拥有全部资源的访问权"),
    ("DEPARTMENT_ADMIN", "部门管理员", DataScope.DEPARTMENT_CHILDREN, "仅本部门及下级"),
    ("VIEWER", "只读用户", DataScope.SELF, "只读，字段大多 HIDDEN"),
]

# ---------------------------------------------------------------- 权限资源

#: 前端 `VIEW_REGISTRY` 的十个页面。
#: `component_path` 必须与注册表键一致，否则动态路由会跳过它。
PAGES: list[tuple[str, str, str, str, int]] = [
    ("system:user:page", "用户管理", "/system/users", "system/user", 10),
    ("system:department:page", "部门管理", "/system/departments", "system/department", 20),
    ("system:role:page", "角色管理", "/system/roles", "system/role", 30),
    ("system:permission:page", "权限配置", "/system/permissions", "system/permission", 40),
    (
        "system:permission-resource:page",
        "权限资源",
        "/system/permission-resources",
        "system/permission-resource",
        50,
    ),
    ("system:session:page", "会话管理", "/system/sessions", "system/session", 60),
    ("system:dictionary:page", "字典管理", "/system/dictionaries", "system/dictionary", 70),
    ("system:param:page", "系统参数", "/system/params", "system/param", 80),
    ("system:audit-log:page", "审计日志", "/system/audit-logs", "system/audit-log", 90),
    ("system:trace:page", "链路查询", "/system/traces", "system/trace", 100),
]

#: (code, name, page_code) —— 按钮挂在其所属 PAGE 下（DD-20：BUTTON.parent_id 必填且指向 PAGE）。
#:
#: ⚠️ 这里的编码是**前端 `PermissionButton` 的 `code`**。前端拿不到授权时
#: 按钮直接不渲染（FE-09 §4），所以清单漏一个的后果不是"点不动"，而是
#: "这个功能在界面上根本不存在" —— 且不会有任何报错。
#: 曾经只有 9 个按钮，而前端用了 27 个，命名还对不上（`role:edit` vs
#: `role:update`、`dict:create` vs `dictionary:create`），结果是除用户管理外
#: 各页的"新增 / 编辑 / 删除"全部凭空消失。
#: 新增按钮只改这里，并同步前端使用点（`tests/test_seed_data.py` 会钉住父子关系）。
BUTTONS: list[tuple[str, str, str]] = [
    # 用户管理
    ("user:create", "新增用户", "system:user:page"),
    ("user:update", "编辑用户", "system:user:page"),
    ("user:enable", "启用用户", "system:user:page"),
    ("user:disable", "禁用用户", "system:user:page"),
    ("user:reset-password", "重置口令", "system:user:page"),
    ("user:delete", "删除用户", "system:user:page"),
    # 部门管理
    ("department:create", "新增部门", "system:department:page"),
    ("department:update", "编辑部门", "system:department:page"),
    ("department:disable", "禁用部门", "system:department:page"),
    # 角色管理
    ("role:create", "新增角色", "system:role:page"),
    ("role:update", "编辑角色", "system:role:page"),
    ("role:delete", "删除角色", "system:role:page"),
    # 权限配置
    ("role:assign-permission", "配置角色权限", "system:permission:page"),
    ("role:config-data-scope", "配置数据范围", "system:permission:page"),
    # 权限资源
    ("permission:resource-create", "新增权限资源", "system:permission-resource:page"),
    ("permission:resource-update", "编辑权限资源", "system:permission-resource:page"),
    ("permission:resource-delete", "删除权限资源", "system:permission-resource:page"),
    # 会话管理
    ("session:revoke", "撤销会话", "system:session:page"),
    ("session:revoke-all", "强制用户下线", "system:session:page"),
    # 数据字典
    ("dictionary:create", "新增字典", "system:dictionary:page"),
    ("dictionary:update", "编辑字典", "system:dictionary:page"),
    ("dictionary:delete", "删除字典", "system:dictionary:page"),
    ("dictionary:item-create", "新增字典项", "system:dictionary:page"),
    ("dictionary:item-update", "编辑字典项", "system:dictionary:page"),
    ("dictionary:item-delete", "删除字典项", "system:dictionary:page"),
    # 系统参数
    ("param:create", "新增参数", "system:param:page"),
    ("param:update", "编辑参数", "system:param:page"),
    ("param:delete", "删除参数", "system:param:page"),
    # 日志
    ("audit:read", "查看审计明细", "system:audit-log:page"),
    ("trace:read", "查看链路明细", "system:trace:page"),
]

#: (code, name, method, path, page_code)
#:
#: `path` 是后端完整路由去掉 `settings.api_v1_prefix`（= `/api/v1/admin`）之后
#: 的相对路径，因此是 `/users` 而不是 `/admin/users` —— 两者在 OpenAPI 里都
#: "看起来像路径"，但后者查不到路由。
APIS: list[tuple[str, str, str, str, str]] = [
    ("USER_MANAGE", "用户管理（读/写）", "GET", "/users", "system:user:page"),
    # 部门的读端点是 `/departments/tree`（列表只以树形返回），
    # 不是 `/departments` —— 后者只有 POST。写在这里但端点不认，等于台账错。
    (
        "DEPARTMENT_MANAGE",
        "部门管理（读/写）",
        "GET",
        "/departments/tree",
        "system:department:page",
    ),
    ("ROLE_MANAGE", "角色管理（读/写）", "GET", "/roles", "system:role:page"),
    (
        "SESSION_MANAGE",
        "会话管理（查看/踢下线）",
        "GET",
        "/sessions",
        "system:session:page",
    ),
    ("DICT_MANAGE", "字典管理（读/写）", "GET", "/dicts", "system:dictionary:page"),
    ("PARAM_MANAGE", "系统参数（读/写）", "GET", "/params", "system:param:page"),
    ("AUDIT_READ", "审计日志查询", "GET", "/audit/logs", "system:audit-log:page"),
    ("TRACE_READ", "链路查询", "GET", "/traces", "system:trace:page"),
    (
        "PERMISSION_RESOURCE_MANAGE",
        "权限资源管理",
        "GET",
        "/permission-resources",
        "system:permission-resource:page",
    ),
]

#: (field_key, page_code)
FIELDS: list[tuple[str, str]] = [
    ("phone", "system:user:page"),
    ("email", "system:user:page"),
    ("remark", "system:user:page"),
    ("department_name", "system:department:page"),
]

#: 菜单（导航层级），code 沿用前端 `menuTree` 的父子约定。
#: (code, name, parent_code, icon, order)
#:
#: `icon` 是**图标名称**，不是渲染字符；前端按名称 → 菜单编码两级解析
#: （`AppSidebar` 的 `ICON_BY_NAME` / `ICON_BY_CODE`）。留空也能显示，
#: 会回退到默认图标 —— 但显式写上，`权限资源` 页里才看得到这个菜单配了什么。
#:
#: ⚠️ 顺序有语义：父菜单必须排在子菜单**之前** —— `seed_common.seed_resources`
#: 边遍历边按 `(MENU, parent_code)` 查已建好的 ID，父还没建就会 KeyError。
#:
#: 「审计日志 / 链路查询」挂在**独立**的顶级分组「日志管理」下，与「系统管理」
#: 平级：日志是排障入口，和"配置类"菜单混在一起时，翻日志要先进一个
#: 与它无关的分组。迁移 `phase11_log_menu` 负责把存量库改成同一形状。
MENUS: list[tuple[str, str, str | None, str | None, int]] = [
    ("system:system", "系统管理", None, "setting", 10),
    ("system:user", "用户管理", "system:system", "user", 20),
    ("system:department", "部门管理", "system:system", "department", 30),
    ("system:role", "角色管理", "system:system", "role", 40),
    ("system:permission", "权限配置", "system:system", "permission", 50),
    # ⚠️ 这一行曾经**整条缺失**。`PAGES` 里有 `system:permission-resource:page`，
    # 但没有任何 MENU 挂载它 —— 后果有两层：
    #   1. 侧边栏里没有入口，`/system/permission-resources` 只能手敲 URL 进
    #      （路由本身照旧存在：动态路由是按 PAGE 契约生成的，不看菜单）；
    #   2. 权限配置页的授权树把它归进「未挂载菜单的页面」分组 ——
    #      看起来像数据坏了，其实只是少了一行。
    # 排序 55 落在「权限配置」(50) 与「会话管理」(60) 之间：资源定义与
    # 角色授权是相邻的两步操作，中间不该夹别的菜单。
    ("system:permission-resource", "权限资源", "system:system", "permission-resource", 55),
    ("system:session", "会话管理", "system:system", "session", 60),
    ("system:dictionary", "字典管理", "system:system", "dictionary", 70),
    ("system:param", "系统参数", "system:system", "param", 80),
    ("log:manage", "日志管理", None, "log", 200),
    ("system:audit-log", "审计日志", "log:manage", "audit-log", 210),
    ("system:trace", "链路查询", "log:manage", "trace", 220),
]

#: 菜单 ↔ 页面关联。菜单点进去若没有任何关联 PAGE，守卫会直接 403。
#:
#: ⚠️ 这份清单必须覆盖 `PAGES` 里的**每一个**页面，否则该页面会在权限配置页
#: 掉进「未挂载菜单的页面」分组、并且在侧边栏里没有任何入口。
#: `tests/test_seed_data.py::test_every_page_is_mounted_by_some_menu` 钉住这一条 ——
#: 本轮之前正是它缺失，`system:permission-resource:page` 静静少了一个入口。
MENU_PAGES: list[tuple[str, str]] = [
    ("system:user", "system:user:page"),
    ("system:department", "system:department:page"),
    ("system:role", "system:role:page"),
    ("system:permission", "system:permission:page"),
    ("system:permission-resource", "system:permission-resource:page"),
    ("system:session", "system:session:page"),
    ("system:dictionary", "system:dictionary:page"),
    ("system:param", "system:param:page"),
    ("system:audit-log", "system:audit-log:page"),
    ("system:trace", "system:trace:page"),
]

# ---------------------------------------------------------------- 授权映射

#: 角色 → 可见页面。VIEWER 刻意看不到"权限配置 / 系统参数 / 审计日志"。
ROLE_PAGES: dict[str, list[str]] = {
    "SUPER_ADMIN": [page[0] for page in PAGES],
    "DEPARTMENT_ADMIN": [
        "system:user:page",
        "system:department:page",
        "system:role:page",
        "system:session:page",
    ],
    "VIEWER": ["system:user:page", "system:department:page"],
}

#: 角色 → 授权按钮。
#:
#: 部门管理员刻意**只拿到日常运维动作**：用户的增改与启停、部门维护、
#: 撤销会话。授权类（`role:*permission*`）、删除类（`*:delete`）、
#: 字典与参数维护都不给 —— 那几类会直接改变"谁能看到什么"，
#: 属于超管职责（与 `ROLE_PAGES` 里不给它「权限配置 / 系统参数 / 审计日志」一致）。
#:
#: VIEWER 一个按钮都不给：只读用户不该在管理面上有任何写入口。
ROLE_BUTTONS: dict[str, list[str]] = {
    "SUPER_ADMIN": [button[0] for button in BUTTONS],
    "DEPARTMENT_ADMIN": [
        "user:create",
        "user:update",
        "user:enable",
        "user:disable",
        "user:reset-password",
        "department:create",
        "department:update",
        "session:revoke",
        "session:revoke-all",
    ],
    "VIEWER": [],
}

#: 角色 → 授权接口。
#:
#: VIEWER **一个接口都不给** —— 只读用户不该碰管理面。这样 `GET /admin/users`
#: 在三个角色下的结果必然不同（超管 200 全量 / 部门管理员 200 范围内 / 只读 403），
#: 而"三个角色同一请求给出三种结果"正是 FE-12 §4 要求的判据。
ROLE_APIS: dict[str, list[str]] = {
    "SUPER_ADMIN": [api[0] for api in APIS],
    "DEPARTMENT_ADMIN": ["USER_MANAGE", "DEPARTMENT_MANAGE"],
    "VIEWER": [],
}

#: 角色 → 字段权限（DD-06 四级）。
ROLE_FIELDS: dict[str, dict[str, FieldAccessLevel]] = {
    "SUPER_ADMIN": {
        "phone": FieldAccessLevel.READ_ONLY,
        "email": FieldAccessLevel.EDITABLE,
        "remark": FieldAccessLevel.EDITABLE,
        "department_name": FieldAccessLevel.EDITABLE,
    },
    # 部门管理员能看到联系方式，但不能改。
    "DEPARTMENT_ADMIN": {
        "phone": FieldAccessLevel.VISIBLE,
        "email": FieldAccessLevel.VISIBLE,
        "remark": FieldAccessLevel.READ_ONLY,
        "department_name": FieldAccessLevel.READ_ONLY,
    },
    # 只读用户：可见但不改，敏感字段直接 HIDDEN。
    "VIEWER": {
        "phone": FieldAccessLevel.HIDDEN,
        "email": FieldAccessLevel.HIDDEN,
        "remark": FieldAccessLevel.READ_ONLY,
        "department_name": FieldAccessLevel.READ_ONLY,
    },
}

# ---------------------------------------------------------------- 撤销用

#: 本脚本写过的全部资源编码 —— 按业务键还原时要用到。
#:
#: 注意 FIELD 的编码规则是 `field:{key}` 而不是裸 `field_key`，
#: 这里若照抄 `resource_code=field_key`，撤销时会漏掉字段资源。
ALL_RESOURCE_CODES: set[str] = (
    {entry[0] for entry in PAGES}
    | {entry[0] for entry in BUTTONS}
    | {entry[0] for entry in APIS}
    | {entry[0] for entry in MENUS}
    | {f"field:{entry[0]}" for entry in FIELDS}
)

ROLE_CODES: list[str] = [entry[0] for entry in ROLES]
DEPARTMENT_CODES: list[str] = [entry[0] for entry in DEPARTMENTS]

# ---------------------------------------------------------------- 数据字典
#
# 为什么清单放在这里：字典与权限资源是同一类"初始数据"——
# 缺席不会报错，只会让界面退化成英文枚举值（`ACTIVE` / `BUTTON` / `ALL`）。
# 混入执行脚本就等于多一处会被漏改的清单（`DESIGN-DECISIONS §19.2`）。
#
# 取值约定
# --------
# `item_value` **必须**是后端真会吐出来的那个值：下拉选项按它提交、
# 状态标签按它反查。写成中文或别的别名，结果是"选了之后后端 422"。
#: (dict_code, dict_name, description, [(label, value, code, sort_order, is_default)])
DICTIONARIES: list[tuple[str, str, str, list[tuple[str, str, str, int, bool]]]] = [
    (
        "user_status",
        "用户状态",
        "后台用户的账号状态；缺失后状态列会退回显示原始枚举值",
        [
            ("正常", "ACTIVE", "user_status_active", 10, True),
            ("停用", "DISABLED", "user_status_disabled", 20, False),
            ("已锁定", "LOCKED", "user_status_locked", 30, False),
        ],
    ),
    (
        "resource_type",
        "资源类型",
        "权限资源的五分类；与 `permission_resources.resource_type` 列名同源",
        [
            ("页面", "PAGE", "resource_type_page", 10, True),
            ("菜单", "MENU", "resource_type_menu", 20, False),
            ("按钮", "BUTTON", "resource_type_button", 30, False),
            ("接口", "API", "resource_type_api", 40, False),
            ("字段", "FIELD", "resource_type_field", 50, False),
        ],
    ),
    (
        "resource_status",
        "资源状态",
        "资源的启用 / 停用；被停用的资源不参与授权计算",
        [
            ("启用", "ACTIVE", "resource_status_active", 10, True),
            ("禁用", "DISABLED", "resource_status_disabled", 20, False),
        ],
    ),
    (
        "data_scope",
        "数据范围",
        "角色的数据范围策略；取值必须与 `app.core.scope.DataScope` 逐字一致",
        [
            ("全部数据", "ALL", "data_scope_all", 10, False),
            ("本部门及下级", "DEPARTMENT_CHILDREN", "data_scope_children", 20, True),
            ("仅本部门", "DEPARTMENT", "data_scope_department", 30, False),
            ("仅本人", "SELF", "data_scope_self", 40, False),
            ("自定义部门", "CUSTOM", "data_scope_custom", 50, False),
        ],
    ),
    (
        "session_revoke_reason",
        "会话撤销原因",
        "会话行被撤销的来源；取值必须与 `app.models.enums.SessionRevokeReason` 逐字一致",
        [
            ("本人登出", "LOGOUT", "revoke_logout", 10, True),
            ("管理员撤销", "ADMIN_REVOKE", "revoke_admin", 20, False),
            ("强制下线", "REVOKE_ALL", "revoke_all", 30, False),
            ("令牌复用", "TOKEN_REUSE_DETECTED", "revoke_token_reuse", 40, False),
            ("顶替下线", "SUPERSEDED", "revoke_superseded", 50, False),
        ],
    ),
    (
        "audit_result",
        "审计结果",
        "审计记录的成败；取值必须与 `app.audit` 写入的值一致",
        [
            ("成功", "SUCCESS", "audit_success", 10, True),
            ("失败", "FAILURE", "audit_failure", 20, False),
        ],
    ),
    (
        "field_access_level",
        "字段权限级别",
        "四级取值由 DD-06 冻结；改名不会报错，只会让授权界面的下拉变成空选项",
        [
            ("隐藏", "HIDDEN", "field_hidden", 10, False),
            ("可见", "VISIBLE", "field_visible", 20, True),
            ("只读", "READ_ONLY", "field_read_only", 30, False),
            ("可编辑", "EDITABLE", "field_editable", 40, False),
        ],
    ),
]

DICT_CODES: list[str] = [entry[0] for entry in DICTIONARIES]
