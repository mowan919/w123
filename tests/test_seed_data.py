"""初始数据清单（`scripts/seed_data.py`）的**契约一致性**测试。

为什么需要这一层
----------------
`scripts/seed_init.py` 是"新环境从不可用到可用"的唯一入口，它写什么完全由
`scripts/seed_data.py` 决定。而这份清单里有大量编码是**跨语言契约**：

- `APIS[].code` 必须与后端 `ApiPermissionCode` 逐字一致，否则 `require_api_permission()`
  认不出它 —— 历史上就写过一个自造的 `api:user:list`，没有任何端点认它，
  表现是"授权界面上明明勾了、角色照样 403"；
- `APIS[].path` 必须是**真实存在**的后端路由，否则这是一条永远授权给谁都
  不通的台账；
- `PAGES[].component_path` 必须与前端 `VIEW_REGISTRY` 的键一致，否则
  `resolveView()` 返回 null → 页面不出现（FE-12 判失败）。

这三类错误的共同点是**报错信息完全不得要领**（只说"缺少 XXX_MANAGE"），
而且**只有在真的建库、真的登录、真的点菜单之后**才暴露。把清单钉在契约上，
等于把这三个坑从"部署后才发现"提前到"CI 立刻拦住"。

不依赖数据库
------------
本模块只做静态比对，不碰 `db_session`：清单本身是纯数据，任何一条断言失败
都不需要一次性把种子写进库才能复现。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# 与 `test_seed_common.py` 以及种子脚本自身保持**同一个模块对象**
# （`scripts/` 已在 pytest 的 pythonpath 里，见 pyproject.toml 的说明）。
import seed_data as data

from app.core.config import settings
from app.main import create_app
from app.models.enums import FieldAccessLevel
from app.services.authorization import ApiPermissionCode

# `frontend/` 是独立工程，Python 侧不去 import 它，只把注册表键读出来比对。
# 之所以用"读文本 + 正则"而不是把前端测试搬过来：要钉住的是"后端清单 ↔ 前端
# 注册表"这条**边界**，两边谁都单独是对的、凑到一起就错了，只有在这里才能发现。
_GENERATE_TS = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "router" / "generate.ts"
)
_REGISTRY_KEY_RE = re.compile(r"^\s{2}'(?P<key>[^']+)':\s*\(\)\s*=>", re.MULTILINE)

#: 侧边栏的图标名称表。`MENUS[].icon` 写的是**名称**，不是可渲染字符 ——
#: 名称对不上时前端会静默回退（先名称表、再编码表、最后默认图标），
#: 于是"配了个不存在的图标名"这件事在界面上**完全看不出来**。
_SIDEBAR_VUE = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "layouts" / "AppSidebar.vue"
)


def _registry_keys() -> set[str]:
    """从前端注册表源码里取出全部 `component_path` 合法取值。"""
    assert _GENERATE_TS.is_file(), f"找不到前端注册表：{_GENERATE_TS}"
    keys = _REGISTRY_KEY_RE.findall(_GENERATE_TS.read_text(encoding="utf-8"))
    assert keys, f"正则没匹配到任何键，generate.ts 的写法可能变了：{_GENERATE_TS}"
    return set(keys)


def _route_table() -> set[tuple[str, str]]:
    """后端真实存在的 `(METHOD, 相对路径)` 集合。

    走 OpenAPI schema 而不是遍历 `app.router.routes`：当前 FastAPI 版本
    （0.141）的 `include_router` 是**惰性**的，lazy router 在 `app.routes` 里
    以 `_IncludedRouter` 占位，直接看 `.path` 会拿到一堆 `AttributeError`；
    `openapi()` 会顺带把它们展开。顺带的另一个好处是只收"进文档的端点"，
    与"授权台账该覆盖哪些端点"是同一个集合。
    """
    spec = create_app().openapi()
    prefix = settings.api_v1_prefix
    routes: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            relative = path[len(prefix) :] if path.startswith(prefix) else path
            routes.add((method.upper(), relative))
    return routes


# ---------------------------------------------------------------- 清单内部自洽


def test_resource_codes_are_unique_within_each_kind() -> None:
    """同一类型内资源编码不得重复。

    `(resource_type, resource_code)` 是逻辑删除感知唯一的业务键，重复写会让
    后者静默顶掉前者（或被库层拒绝），两种都不是种子脚本该有的行为。
    """
    for kind, entries in (
        ("PAGES", data.PAGES),
        ("BUTTONS", data.BUTTONS),
        ("APIS", data.APIS),
        ("MENUS", data.MENUS),
        ("FIELDS", data.FIELDS),
    ):
        codes = [entry[0] for entry in entries]
        duplicates = {code for code in codes if codes.count(code) > 1}
        assert not duplicates, f"{kind} 里有重复编码：{duplicates}"


def test_all_resource_codes_matches_every_kind() -> None:
    """`ALL_RESOURCE_CODES` 是撤销脚本的清单，漏一个就撤不干净。"""
    expected = {entry[0] for entry in data.PAGES} | {entry[0] for entry in data.BUTTONS}
    expected |= {entry[0] for entry in data.APIS} | {entry[0] for entry in data.MENUS}
    expected |= {f"field:{entry[0]}" for entry in data.FIELDS}
    assert expected == data.ALL_RESOURCE_CODES


def test_parent_links_point_at_real_pages() -> None:
    """BUTTON / API / FIELD 都挂在某个 PAGE 下，`ck_..._resource_type_fields` 强制非空。"""
    page_codes = {entry[0] for entry in data.PAGES}
    for entry in data.BUTTONS:
        assert entry[2] in page_codes, f"BUTTON {entry[0]} 的所属页面 {entry[2]} 不存在"
    for entry in data.APIS:
        assert entry[4] in page_codes, f"API {entry[0]} 的所属页面 {entry[4]} 不存在"
    for field_key, page_code in data.FIELDS:
        assert page_code in page_codes, f"FIELD {field_key} 的所属页面 {page_code} 不存在"


def test_menu_hierarchy_has_no_cycle() -> None:
    """菜单自引用；种子里的层级必须是 DAG，环会让前端导航直接死循环。"""
    menu_codes = {entry[0] for entry in data.MENUS}
    parent_of = {entry[0]: entry[2] for entry in data.MENUS if entry[2] is not None}
    for code, parent in parent_of.items():
        assert parent in menu_codes, f"MENU {code} 的父菜单 {parent} 不存在"
    seen: set[str] = set()
    current: str | None = "ROOT"
    while current is not None:
        assert current not in seen, f"菜单层级存在环：{current}"
        seen.add(current)
        current = parent_of.get(current)


# ---------------------------------------------------------------- 授权引用的编码都存在


def test_role_keys_are_real_roles() -> None:
    """授权映射的四张表必须都只给真实角色授权，无角色的授权等于静默丢弃。"""
    role_codes = {entry[0] for entry in data.ROLES}
    for table in (data.ROLE_PAGES, data.ROLE_BUTTONS, data.ROLE_APIS, data.ROLE_FIELDS):
        unknown = set(table) - role_codes
        assert not unknown, f"授权表引用了不存在的角色：{unknown}"


def test_every_role_has_a_grant_table_entry() -> None:
    """少一个角色就是在给一个"存在但什么都没有"的角色。"""
    role_codes = {entry[0] for entry in data.ROLES}
    assert set(data.ROLE_PAGES) == role_codes
    assert set(data.ROLE_BUTTONS) == role_codes
    assert set(data.ROLE_APIS) == role_codes
    assert set(data.ROLE_FIELDS) == role_codes


def test_granted_codes_exist_in_the_resource_lists() -> None:
    """授权清单里引用的每个编码，都必须在资源清单里真的存在。"""
    page_codes = {entry[0] for entry in data.PAGES}
    button_codes = {entry[0] for entry in data.BUTTONS}
    api_codes = {entry[0] for entry in data.APIS}
    field_keys = {entry[0] for entry in data.FIELDS}
    for role, granted in data.ROLE_PAGES.items():
        unknown = set(granted) - page_codes
        assert not unknown, f"{role} 授权了不存在的页面：{unknown}"
    for role, granted in data.ROLE_BUTTONS.items():
        unknown = set(granted) - button_codes
        assert not unknown, f"{role} 授权了不存在的按钮：{unknown}"
    for role, granted in data.ROLE_APIS.items():
        unknown = set(granted) - api_codes
        assert not unknown, f"{role} 授权了不存在的接口：{unknown}"
    for role, levels in data.ROLE_FIELDS.items():
        unknown = set(levels) - field_keys
        assert not unknown, f"{role} 授权了不存在的字段：{unknown}"


def test_menu_pages_reference_existing_menus_and_pages() -> None:
    """菜单没有关联任何 PAGE 时，点进去会被守卫 403（FE-12 §5）。"""
    menu_codes = {entry[0] for entry in data.MENUS}
    page_codes = {entry[0] for entry in data.PAGES}
    for menu_code, page_code in data.MENU_PAGES:
        assert menu_code in menu_codes, f"MENU_PAGES 引用了不存在的菜单 {menu_code}"
        assert page_code in page_codes, f"MENU_PAGES 引用了不存在的页面 {page_code}"


def test_every_page_is_mounted_by_some_menu() -> None:
    """每个 PAGE 都必须被至少一个 MENU 挂载 —— 这是**导航入口的存在性**判据。

    与授权无关：判权只认 Page（`09 §4`），所以漏挂菜单不会让谁 403。
    它的后果更隐蔽 ——

    1. 侧边栏里没有入口。路由照旧存在（前端动态路由按 **PAGE 契约**生成，
       不看菜单），所以手敲 URL 能进去，表现为"这页能用，但没人找得到它"；
    2. 权限配置页的授权树把它归进「未挂载菜单的页面」分组，
       看起来像数据坏了，实际只是少了一行菜单。

    本轮之前 `system:permission-resource:page` 正是这个状态：`PAGES` 里有它，
    `MENUS` 里连对应的菜单行都不存在。这个缺口在既有断言里**完全测不到** ——
    `test_menu_pages_reference_existing_menus_and_pages` 只验"写了的关联有效"，
    不验"该有的关联有没有写"，方向正好相反。
    """
    mounted = {page_code for _menu_code, page_code in data.MENU_PAGES}
    unmounted = sorted(entry[0] for entry in data.PAGES if entry[0] not in mounted)
    assert not unmounted, f"这些页面没有任何菜单入口（会掉进「未挂载菜单的页面」）：{unmounted}"


def test_leaf_menus_mount_at_least_one_page() -> None:
    """没有子菜单的 MENU 必须挂至少一个 PAGE，否则那是一个点不动的死入口。

    `AppSidebar` 对解不出路由的菜单渲染成不可点的标题（不是链接），所以它
    不会报错、不会 403 —— 只会在侧边栏里占一行、永远点不开。
    纯分组（`系统管理` / `日志管理`）因为**有子菜单**而不受这条约束。
    """
    child_menus = {entry[2] for entry in data.MENUS if entry[2] is not None}
    mounted = {menu_code for menu_code, _page_code in data.MENU_PAGES}
    leaves_without_page = sorted(
        entry[0] for entry in data.MENUS if entry[0] not in child_menus and entry[0] not in mounted
    )
    assert not leaves_without_page, f"这些叶子菜单没有关联页面（点不动）：{leaves_without_page}"


def test_field_access_levels_are_the_frozen_four_levels() -> None:
    """字段权限是 `03 §9` 冻结的四级取值，写错等级等于把 `HIDDEN` 当成 `EDITABLE`。

    `role_field_permissions.access_level` 由库层 CHECK 约束取值域，
    但"这个角色到底是能看还是能改"只有清单能说明，所以这里钉住类型。
    """
    valid = set(FieldAccessLevel)
    for role, levels in data.ROLE_FIELDS.items():
        for field_key, level in levels.items():
            assert level in valid, f"{role} 对字段 {field_key} 的等级 {level!r} 不是四级之一"


def test_dictionary_values_are_the_real_backend_values() -> None:
    """字典项的 `item_value` 必须是**后端真会吐出来的那一个值**。

    这条断言是写本轮种子时真踩出来的：凭印象写了 `WRITE`
    （正确是 `EDITABLE`）与 `REFRESH_INVALID` / `PASSWORD_CHANGED`
    （正确是 `REVOKE_ALL` / `TOKEN_REUSE_DETECTED`）。
    这类错误的表现是"下拉里有一项，选了之后后端 422"——
    而且只在用户真的选了那一项时才出现，静态读代码读不出来。
    """
    from app.audit.events import AuditResult
    from app.core.scope import DataScope
    from app.models.enums import FieldAccessLevel, SessionRevokeReason, UserStatus

    #: 字典码 → 该码允许取值的集合（None 表示"只校验形状，不校验取值"）。
    expected: dict[str, set[str] | None] = {
        "user_status": {member.value for member in UserStatus},
        "resource_type": {"PAGE", "MENU", "BUTTON", "API", "FIELD"},
        "resource_status": {"ACTIVE", "DISABLED"},
        "data_scope": {member.value for member in DataScope},
        "session_revoke_reason": {member.value for member in SessionRevokeReason},
        "audit_result": {member.value for member in AuditResult},
        "field_access_level": {member.value for member in FieldAccessLevel},
    }

    codes = [entry[0] for entry in data.DICTIONARIES]
    assert len(codes) == len(set(codes)), f"重复的字典码：{codes}"
    # 新增字典码必须**同时**在这里登记允许取值 ——
    # 否则"这个值到底对不对"就是无人校验的状态。
    assert set(codes) == set(expected), f"字典码与校验表不一致：{set(codes) ^ set(expected)}"

    for code, _name, _description, items in data.DICTIONARIES:
        allowed = expected[code]
        values = [item[1] for item in items]
        assert len(values) == len(set(values)), f"{code} 的取值重复：{values}"
        item_codes = [item[2] for item in items]
        assert len(item_codes) == len(set(item_codes)), f"{code} 的 item_code 重复：{item_codes}"
        # 有且只有一个默认项：多个默认值会让"默认选中"变成看实现心情。
        assert sum(1 for item in items if item[4]) == 1, f"{code} 的默认项不是一个"
        if allowed is None:
            continue
        for value in values:
            assert value in allowed, f"{code} 的取值 {value!r} 不是后端真值：{sorted(allowed)}"


def test_department_tree_is_well_formed() -> None:
    """部门是邻接表；根必须唯一，其余父节点必须存在，否则建树时 FK 直接 RESTRICT。"""
    codes = {entry[0] for entry in data.DEPARTMENTS}
    roots = [entry[0] for entry in data.DEPARTMENTS if entry[2] is None]
    assert len(roots) == 1, f"必须且只能有一个根部门，实际：{roots}"
    for code, _name, parent in data.DEPARTMENTS:
        if parent is not None:
            assert parent in codes, f"部门 {code} 的父部门 {parent} 不存在"


# ---------------------------------------------------------------- 跨语言契约


def _icon_names() -> set[str]:
    """从 `AppSidebar.vue` 的 `ICON_BY_NAME` 表里取出前端认识的图标名称。

    只截取 `const ICON_BY_NAME` 到该对象字面量的收尾 `}` 之间，并剥掉注释行 ——
    不这样做会把后面 `ICON_BY_CODE` 的键也算进来，断言就永远为真了。
    """
    assert _SIDEBAR_VUE.is_file(), f"找不到侧边栏组件：{_SIDEBAR_VUE}"
    text = _SIDEBAR_VUE.read_text(encoding="utf-8")
    start = text.index("const ICON_BY_NAME")
    block = text[start : text.index("\n}", start)]
    lines = [line for line in block.splitlines() if not line.strip().startswith("//")]
    keys = re.findall(r"^\s+'?([A-Za-z][\w-]*)'?:\s*[A-Za-z]", "\n".join(lines), re.MULTILINE)
    assert keys, f"没解析出任何图标名称，AppSidebar.vue 的写法可能变了：{_SIDEBAR_VUE}"
    return set(keys)


def test_menu_icons_are_known_to_the_sidebar() -> None:
    """`MENUS[].icon` 写的名称必须在前端 `ICON_BY_NAME` 表里存在。

    名字对不上**不会报错**：`AppSidebar.iconOf()` 先查名称表、再按菜单编码兜底、
    最后回退默认图标 —— 于是"配了个拼错的图标名"表现为"这个菜单用了默认图标"，
    与"后端本来就没配图标"看起来一模一样，无从区分。

    本轮新增的 `permission-resource` 正是这条边界上的一个真实取值：
    它在编码兜底表里本来就有，名称表缺失时功能上没问题，
    但"配了什么"与"渲染了什么"就对不上了 —— 这个用例让两边必须同时改。
    """
    known = _icon_names()
    missing: dict[str, str] = {}
    for code, _name, _parent, icon, _order in data.MENUS:
        if icon is not None and icon not in known:
            missing[code] = icon
    assert not missing, f"这些菜单配了前端不认识的图标名：{missing}"


def test_api_codes_match_the_authoritative_enum() -> None:
    """`APIS[].code` 必须是 `ApiPermissionCode` 的成员。

    这是本项目踩过最狠的一次（`seed_e2e.py` 模块文档记着）：写了个后端没人认的
    编码，界面上勾了、运行时照旧 403，而报错只说"缺少 USER_MANAGE"，
    指向性为零。
    """
    known = {member.value for member in ApiPermissionCode}
    for code, _name, _method, _path, _page in data.APIS:
        assert code in known, f"API 编码 {code} 不在 ApiPermissionCode 里"


def test_api_paths_and_methods_are_real_backend_routes() -> None:
    """路径 + 方法必须能在 FastAPI 的路由表里找到。

    Spec `03 §8` 把 API Permission 定义为后端强制授权，路径在这里只是台账；
    但台账写错和编码写错同样会骗人 —— 会出现一条"永远授权、也永远没有端点"
    （或反过来，命中了别的端点）的记录。
    """
    routes = _route_table()
    for code, _name, method, path, _page in data.APIS:
        assert (method, path) in routes, f"{code} 对应的 {method} {path} 在后端路由里不存在"


def test_pages_carry_both_paths_the_frontend_needs() -> None:
    """PAGE 必须同时给 `route_path` 与 `component_path`。"""
    for code, _name, route_path, component_path, _order in data.PAGES:
        assert route_path, f"PAGE {code} 缺 route_path"
        assert component_path, f"PAGE {code} 缺 component_path"


def test_component_paths_match_the_frontend_registry() -> None:
    """`component_path` 必须对得上前端 `VIEW_REGISTRY` 的键。

    `resolveView()` 认不出的 `component_path` 会被静默跳过 —— 菜单在、点了白屏。
    """
    registry = _registry_keys()
    for code, _name, _route, component_path, _order in data.PAGES:
        assert component_path in registry, (
            f"PAGE {code} 的 component_path {component_path!r} 不在前端 VIEW_REGISTRY 里"
        )


@pytest.mark.parametrize(("code", "path"), [(entry[0], entry[3]) for entry in data.APIS])
def test_api_path_prefix_rule(code: str, path: str) -> None:
    """API 路径取后端相对路径，不带 `/api/v1` 前缀（见 `seed_data` 模块文档）。"""
    assert not path.startswith("/api/v1"), f"{code} 的路径不该带 /api/v1 前缀：{path}"
    assert path.startswith("/"), f"{code} 的路径必须以 / 开头：{path}"
