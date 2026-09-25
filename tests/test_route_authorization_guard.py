"""全路由授权护栏（`08 §10` / DD-20 §5.1.3）。

为什么需要这条护栏
------------------
`08 §10` 冻结："每个受保护 API 必须经过后端 API Permission 校验，
禁止仅依赖 URL 隐藏、菜单隐藏或按钮隐藏。"

DD-20 §5.1.3 选择**声明式绑定**而不是"路径 ↔ 权限正则匹配"，
理由写在 `require_api_permission` 的 docstring 里：正则在 `{id}` 占位、
尾斜杠、方法覆盖下容易**漏判，而漏判即越权**。
但该决策里还有半句话此前没有落地：

> 漏声明的路由可以被静态扫描出来

本项目已经因为"某个 HTTP 面根本不存在 / 根本没被检查，却没有任何断言会红"
踩过两次（FINDING-8-01、FINDING-10-01）。本文件把那半句话补上：
**新增一条没有声明授权的管理端点，本文件立刻失败。**

已知遗留（白名单）为什么是**子集**断言而不是相等断言
----------------------------------------------
`assert undeclared <= ALLOWLIST`：

- 新增一条未声明端点 → 不在白名单里 → **失败**（这是护栏的目的）；
- 修好一条遗留端点 → 集合变小 → **仍然通过**（鼓励修，不逼人改测试）。

反方向（相等）会把"修好了"也判成失败，那是在惩罚改进。

白名单里的路由**不是**未授权
--------------------------
它们（sessions / dicts / params）在**服务层**调用
`assert_can_manage_sessions` / `assert_can_manage_dicts` / `assert_can_manage_params`，
而这些方法最终都走 `assert_api_permission` —— `08 §10` 是满足的。
白名单表达的是**绑定位置不一致**（服务层而非路由层）这一技术债，
不是"没有授权"。登记为 `DEBT-10-01`（`docs/DESIGN-DECISIONS.md §17.7`）。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI

from app.api.deps import API_PERMISSION_MARKER
from app.api.v1.router import api_router
from app.core.config import settings

pytestmark = pytest.mark.unit

ADMIN_PREFIX = "/api/v1/admin"

#: 已知遗留：授权在**服务层**完成，路由层未声明（`DEBT-10-01`）。
#:
#: 这些路径是路由对象上的**相对**路径（不含 `/api/v1/admin` 前缀）。
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Phase 5 会话管理（`08 §5` + `08 §4` 的会话子资源）
        "/sessions",
        "/sessions/{session_id}/revoke",
        "/users/{user_id}/sessions",
        "/users/{user_id}/sessions/revoke-all",
        # Phase 7 字典（`05 §4` / `08 §9`）
        "/dicts",
        "/dicts/{dict_type_id}",
        "/dicts/{dict_type_id}/items",
        "/dicts/{dict_type_id}/items/{item_id}",
        # Phase 7 系统参数（`05 §5`）
        "/params",
        "/params/{param_id}",
    }
)

#: 健康检查探针**刻意**不要求权限：它们要能回答"这个进程还活着吗"，
#: 而一个需要登录才能访问的健康检查在依赖挂掉时最没用（恰恰那时才需要它）。
PROBE_SUFFIXES = ("/health", "/health/ready", "/health/db", "/health/redis")


def _iter_route_objects(router: Any) -> list[Any]:
    """递归展开路由对象。

    FastAPI 0.141 的 `include_router` 产生 `_IncludedRouter` 包装
    （它没有 `.path` / `.routes`），真正的路由在其 `original_router` 里。
    只遍历 `router.routes` 会**静默地**什么也看不到 ——
    那会让本护栏变成一条永远通过的空断言。
    """
    collected: list[Any] = []
    for route in router.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            collected.extend(_iter_route_objects(inner))
        else:
            collected.append(route)
    return collected


def _iter_dependant_calls(node: Any) -> Iterator[Any]:
    """深度遍历 `Dependant` 树上的全部 callable。

    为什么必须遍历 `dependant` 而不能只看 `route.dependencies`：
    在 FastAPI 0.141 上，`route.dependencies` 里的 `Depends` 对象的
    `.call` 是 **None**（该版本把它解析进了 `route.dependant` 树）。
    只看前者会得到"一条声明都没有" —— 而那会让本护栏变成
    **永远绿的空断言**，比没有护栏更危险。
    """
    call = getattr(node, "call", None)
    if call is not None:
        yield call
    for sub in getattr(node, "dependencies", None) or ():
        yield from _iter_dependant_calls(sub)


def _declared_api_code(route: Any) -> str | None:
    """返回该路由声明的 `resource_code`；未声明则为 None。"""
    for dependency in getattr(route, "dependencies", None) or ():
        for candidate in (
            getattr(dependency, "call", None),
            getattr(dependency, "dependency", None),
        ):
            marker = getattr(candidate, API_PERMISSION_MARKER, None)
            if marker is not None:
                return str(marker)

    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for call in _iter_dependant_calls(dependant):
            marker = getattr(call, API_PERMISSION_MARKER, None)
            if marker is not None:
                return str(marker)
    return None


@pytest.fixture
def admin_route_objects(app: FastAPI) -> list[Any]:
    """admin 域下的全部路由对象。

    从 `api_router` **直接**展开而不是从 `app.router` 反推前缀：
    按"全路径 endswith 相对路径"反推会产生**歧义** ——
    认证域的 `GET /permissions`（`/api/v1/auth/permissions`）
    与 admin 域的 `/roles/{role_id}/permissions` 都以 `/permissions` 结尾，
    于是前者会被误判成 admin 路由并报"未声明授权"。
    直接展开 `api_router` 得到的前缀是唯一确定的（`settings.api_v1_prefix`）。

    代价是：若有端点绕过 `api_router` 直接挂到 app 上，本护栏看不到它。
    该代价由 `test_openapi_admin_paths_are_all_covered` 补上 ——
    它按 OpenAPI 的全量路径做一次对账。
    """
    del app  # 仅用于确保应用已构造（路由已注册）
    return [
        route
        for route in _iter_route_objects(api_router)
        if getattr(route, "path", None) is not None
    ]


def _full_path(relative: str) -> str:
    return f"{settings.api_v1_prefix}{relative}"


class TestRouteAuthorizationGuard:
    def test_guard_actually_sees_the_routes(self, admin_route_objects: list[Any]) -> None:
        """护栏自检：如果遍历方式失效，本用例先红。

        没有这条，"扫到了 0 条路由"会被 `<=` 断言判成通过 ——
        那是一条**永远绿**的护栏，比没有护栏更危险（它会给人虚假的安全感）。
        """
        assert len(admin_route_objects) >= 40, (
            f"只扫到 {len(admin_route_objects)} 条 admin 路由，"
            "遍历方式很可能已经失效（`_IncludedRouter` 结构变化？）"
        )

    def test_every_admin_route_declares_a_permission_or_is_allowlisted(
        self, admin_route_objects: list[Any]
    ) -> None:
        undeclared: set[str] = set()
        for route in admin_route_objects:
            path = str(route.path)
            if path.endswith(PROBE_SUFFIXES):
                continue
            if _declared_api_code(route) is None:
                undeclared.add(path)

        assert undeclared <= ALLOWLIST, (
            "以下管理端点未声明 API 权限绑定（新增端点必须声明式绑定，见 DD-20 §5.1.3）："
            f"{sorted(undeclared - ALLOWLIST)}"
        )

    def test_openapi_admin_paths_are_all_covered(self, app: FastAPI) -> None:
        """对账：OpenAPI 里的每条 admin 路径都能在本护栏的扫描范围内找到。

        补上"直接展开 `api_router`"留下的盲区（绕过 `api_router`
        挂到 app 上的端点）。路径模板里的参数名不影响匹配 ——
        两边都来自同一份路由定义，形状必然一致。
        """
        openapi_admin = {
            path for path in app.openapi()["paths"] if path.startswith(f"{ADMIN_PREFIX}/")
        }
        covered = {_full_path(str(route.path)) for route in _iter_route_objects(api_router)}
        missing = openapi_admin - covered
        assert not missing, f"有 admin 端点未被授权护栏覆盖：{sorted(missing)}"

    def test_allowlist_is_not_growing(self, admin_route_objects: list[Any]) -> None:
        """白名单里的条目必须**都还存在** —— 防止白名单变成无人认领的僵尸清单。

        条目被修好后从本文件删掉即可；反过来，如果某个路径已经改名或删除
        却还留在白名单里，说明有人改了路由却没同步这里。
        """
        present = {str(route.path) for route in admin_route_objects}
        stale = ALLOWLIST - present
        assert not stale, f"白名单里有已不存在的路由：{sorted(stale)}"

    def test_marker_is_attached_to_declared_routes(self, admin_route_objects: list[Any]) -> None:
        """标记机制本身有效：确实扫到了带标记的路由。

        与第一条自检同向，但针对的是**标记**而不是遍历 ——
        两个环节任一失效都会各自暴露。
        """
        declared = {
            str(route.path): _declared_api_code(route)
            for route in admin_route_objects
            if _declared_api_code(route) is not None
        }
        assert len(declared) >= 20, f"只识别出 {len(declared)} 条声明式绑定"
        assert declared["/users"] == "USER_MANAGE"
        assert declared["/roles"] == "ROLE_MANAGE"
        assert declared["/audit/logs"] == "AUDIT_READ"
        assert declared["/traces/{trace_id}"] == "TRACE_READ"
