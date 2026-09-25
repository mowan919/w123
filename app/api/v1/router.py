"""API v1 路由聚合（**admin 资源域**）。

Spec 08 §1 Base：`/api/v1/admin`

认证端点（`/api/v1/auth/**`）**不在此处挂载** —— 它们属于认证域，
由 `app.main.create_app` 以独立前缀挂载。理由：
登录时尚不存在"已认证的操作者"，把登录端点放进 admin 域
会让"资源域"与"认证域"的边界模糊，并暗示"先认证才能登录"。

本阶段已挂载：

| 端点 | 归属 |
|---|---|
| `/health*` | 基础设施（Phase 0） |
| `/sessions`、`/sessions/{id}/revoke` | 会话管理（Session Phase，`08 §5`） |
| `/users/{id}/sessions`、`/users/{id}/sessions/revoke-all` | 会话管理（Session Phase，`08 §4`） |
| `/dicts*` | 字典管理（Phase 7，`05 §4` / `08 §9`） |
| `/params*` | 系统参数管理（Phase 7，`05 §5`；路径属 INTERIM-7-04） |
| `/permission-resources*` | 权限资源定义（Phase 8，DD-20 §5.1.1 冻结的 8 条端点） |
| `/roles/{id}/permissions*`、`/roles/{id}/data-scope` | 角色授权与数据范围（Phase 8，`08 §7`） |

`/users/{id}/sessions*` 的路径前缀属 Users 资源，但业务语义是会话管理，
因此实现落在 `endpoints/sessions.py`（详见该模块 docstring）。

**公开字典查询**（`GET /api/v1/dicts/{dictCode}`）**不在此处**：
它按 `05 §4` 位于 admin 域之外，由 `create_app` 以
`settings.public_v1_prefix` 挂载（见 `endpoints/dicts.py::public_router`）。

**`GET /auth/permissions`**（Phase 8）**不在此处**：它属认证域，
与 `/auth/me` 同前缀（INTERIM-4-01），由 `create_app` 以
`settings.auth_v1_prefix` 挂载。

其余业务端点分别属于后续或既有的 Phase，本阶段不实现（见
`docs/DESIGN-DECISIONS.md` §15 的 FINDING-8-01）。

`/audit/logs*`、`/traces*`（`08 §8`）于 Phase 10 补交付（FINDING-10-01）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit_logs,
    departments,
    dicts,
    health,
    params,
    permission_resources,
    role_permissions,
    roles,
    sessions,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(sessions.router)
api_router.include_router(dicts.router)
api_router.include_router(params.router)
api_router.include_router(permission_resources.router)
api_router.include_router(role_permissions.router)
# FINDING-8-01 的补救：`08 §4` / `§6` / `§7` 冻结的**实体 CRUD** 端点
# （此前只交付了服务层，HTTP 面缺失）。
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(departments.router)
# FINDING-10-01 的补救：`08 §8` 冻结的审计 / 链路**读**端点
# （Phase 6 只交付了落库，没有任何 HTTP 面能把它们查出来）。
api_router.include_router(audit_logs.router)

__all__ = ["api_router"]
