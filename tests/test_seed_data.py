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


def test_field_access_levels_are_the_frozen_four_levels() -> None:
    """字段权限是 `03 §9` 冻结的四级取值，写错等级等于把 `HIDDEN` 当成 `EDITABLE`。

    `role_field_permissions.access_level` 由库层 CHECK 约束取值域，
    但"这个角色到底是能看还是能改"只有清单能说明，所以这里钉住类型。
    """
    valid = set(FieldAccessLevel)
    for role, levels in data.ROLE_FIELDS.items():
        for field_key, level in levels.items():
            assert level in valid, f"{role} 对字段 {field_key} 的等级 {level!r} 不是四级之一"


def test_department_tree_is_well_formed() -> None:
    """部门是邻接表；根必须唯一，其余父节点必须存在，否则建树时 FK 直接 RESTRICT。"""
    codes = {entry[0] for entry in data.DEPARTMENTS}
    roots = [entry[0] for entry in data.DEPARTMENTS if entry[2] is None]
    assert len(roots) == 1, f"必须且只能有一个根部门，实际：{roots}"
    for code, _name, parent in data.DEPARTMENTS:
        if parent is not None:
            assert parent in codes, f"部门 {code} 的父部门 {parent} 不存在"


# ---------------------------------------------------------------- 跨语言契约


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
