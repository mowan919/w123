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
BUTTONS: list[tuple[str, str, str]] = [
    ("user:create", "新增用户", "system:user:page"),
    ("user:update", "编辑用户", "system:user:page"),
    ("user:delete", "删除用户", "system:user:page"),
    ("user:reset-password", "重置口令", "system:user:page"),
    ("department:create", "新增部门", "system:department:page"),
    ("department:update", "编辑部门", "system:department:page"),
    ("role:create", "新增角色", "system:role:page"),
    ("role:update", "编辑角色", "system:role:page"),
    ("dictionary:create", "新增字典", "system:dictionary:page"),
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
MENUS: list[tuple[str, str, str | None, str | None, int]] = [
    ("system:system", "系统管理", None, "setting", 10),
    ("system:user", "用户管理", "system:system", None, 20),
    ("system:department", "部门管理", "system:system", None, 30),
    ("system:role", "角色管理", "system:system", None, 40),
    ("system:permission", "权限配置", "system:system", None, 50),
    ("system:session", "会话管理", "system:system", None, 60),
    ("system:dictionary", "字典管理", "system:system", None, 70),
    ("system:param", "系统参数", "system:system", None, 80),
    ("system:audit-log", "审计日志", "system:system", None, 90),
    ("system:trace", "链路查询", "system:system", None, 100),
]

#: 菜单 ↔ 页面关联。菜单点进去若没有任何关联 PAGE，守卫会直接 403。
MENU_PAGES: list[tuple[str, str]] = [
    ("system:user", "system:user:page"),
    ("system:department", "system:department:page"),
    ("system:role", "system:role:page"),
    ("system:permission", "system:permission:page"),
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
ROLE_BUTTONS: dict[str, list[str]] = {
    "SUPER_ADMIN": [button[0] for button in BUTTONS],
    "DEPARTMENT_ADMIN": ["user:create", "user:update", "department:create", "department:update"],
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
