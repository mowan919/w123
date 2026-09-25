"""角色权限与数据范围端点（Phase 8 / Spec `08 §7`）。

端点清单（`08 §7` 冻结）
-----------------------
| 方法 | 路径 |
|---|---|
| GET | `/roles/{id}/permissions` |
| PUT | `/roles/{id}/permissions/pages` |
| PUT | `/roles/{id}/permissions/menus` |
| PUT | `/roles/{id}/permissions/buttons` |
| PUT | `/roles/{id}/permissions/apis` |
| PUT | `/roles/{id}/permissions/fields` |
| GET | `/roles/{id}/data-scope` |
| PUT | `/roles/{id}/data-scope` |

为什么把"权限授予"与"数据范围"放在同一个模块
------------------------------------------
它们回答的是同一个问题的两半：
**角色能做什么（Page/Menu/Button/API/Field）** 与
**角色能对谁做（Data Scope）**。
`08 §7` 也把它们排在同一节。两者合起来才是"角色的权限配置面"，
而"角色/用户/部门"等**实体 CRUD** 的 HTTP 面**不在本 Phase**
（见 `docs/DESIGN-DECISIONS.md` §15 的 FINDING-8-01）——
本 Phase 的主题是权限的**输出与管理**，不是组织实体的增删改查。

`fields` 的请求体为什么与四类二元权限不同
-------------------------------------
`03 §9` 的字段权限是**四级有序取值**而非"有 / 无"（DD-06 冻结），
因此 `pages/menus/buttons/apis` 收 `{"resourceIds": [...]}`，
而 `fields` 收 `{"fields": [{"resourceId": ..., "accessLevel": ...}]}`。
把两者统一成一种形状必然丢掉等级信息。

六个端点为什么写成六个显式路由而不是 `/permissions/{kind}`
----------------------------------------------------
用路径参数 `{kind}` 会让 OpenAPI 里只出现一条
`/roles/{id}/permissions/{kind}`，而 `08 §7` 冻结的是**四条具体路径** ——
契约测试（Phase 10 的 API contract test）按路径比对时会直接判缺失。
该端点本来就少，显式声明换来"路由面逐条可核"，是划算的。

全部端点声明式绑定 `ROLE_MANAGE`（`08 §10` 后端强制授权），
并在拒绝时写 FAILURE 审计（见 `require_api_permission` 的说明）。

事务边界
-------
与既有端点同一约定：**端点负责 `commit()`**，Service 只 `flush()`。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    RoleDataScopeServiceDep,
    RolePermissionServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.response import success_response
from app.schemas.role import (
    RoleDataScopeRequest,
    RoleDataScopeResponse,
    RoleFieldPermissionsRequest,
    RolePermissionIdsRequest,
    RolePermissionViewResponse,
)
from app.services.authorization import ApiPermissionCode
from app.services.role_data_scope import RoleDataScope
from app.services.role_permission import RESOURCE_TYPE, RolePermissionService, RolePermissionView

router = APIRouter(tags=["RolePermission"])

#: 本模块所有端点共用的权限位。
_MANAGE = ApiPermissionCode.ROLE_MANAGE


def _manage_dependency(action: AuditAction) -> list[Any]:
    """路由级依赖：需要 `ROLE_MANAGE`，拒绝写 FAILURE 审计。"""
    return [Depends(require_api_permission(_MANAGE, action=action, resource_type=RESOURCE_TYPE))]


def _permission_response(view: RolePermissionView) -> RolePermissionViewResponse:
    """把授权视图映射为响应模型。

    `field_levels` 的键必须是字符串（JSON 对象的键只能是字符串，
    而业务 ID 也规定序列化为字符串，`00 §6`）—— 在这里一次性转换，
    避免每个消费方各自 `str(...)` 而产生"有的地方是数字键"的漂移。
    """
    return RolePermissionViewResponse(
        role_id=view.role_id,
        page_ids=sorted(view.page_ids),
        menu_ids=sorted(view.menu_ids),
        button_ids=sorted(view.button_ids),
        api_ids=sorted(view.api_ids),
        field_levels={
            str(field_id): level for field_id, level in sorted(view.field_levels.items())
        },
    )


def _data_scope_response(view: RoleDataScope) -> RoleDataScopeResponse:
    """把数据范围视图映射为响应模型。"""
    return RoleDataScopeResponse(
        role_id=view.role_id,
        data_scope=view.scope,
        department_ids=sorted(view.department_ids),
    )


@router.get(
    "/roles/{role_id}/permissions",
    summary="角色权限（授权详情）",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_READ),
)
async def get_role_permissions(
    role_id: int,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
) -> JSONResponse:
    """读取角色的四类二元授权 ID 与字段等级。

    只返回**已授权**的有效资源（已删除 / 已停用的资源会被过滤）——
    后台界面据此勾选，若把失效授权也返回，管理员会看到"勾上了却不生效"。
    """
    view = await service.get(actor=actor, role_id=role_id)
    return success_response(_permission_response(view))


async def _replace_binary(
    *,
    kind: str,
    role_id: int,
    payload: RolePermissionIdsRequest,
    actor: CurrentActor,
    service: RolePermissionService,
    session: AsyncSession,
) -> JSONResponse:
    """四类二元授权的公共实现（整体替换语义，DD-20 冻结）。

    刻意不在本函数里做任何类型/存在性校验：那些校验属于服务层
    （`_assert_resources_assignable`），在这里再写一遍就会出现
    "路由层允许、服务层拒绝"或反之的分歧。
    """
    view = await service.replace(
        actor=actor,
        role_id=role_id,
        kind=kind,
        resource_ids=frozenset(payload.resourceIds),
    )
    await session.commit()
    return success_response(_permission_response(view))


@router.put(
    "/roles/{role_id}/permissions/pages",
    summary="整体替换角色的页面授权",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_UPDATE),
)
async def replace_role_pages(
    role_id: int,
    payload: RolePermissionIdsRequest,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """替换该角色的**页面**授权集合（空数组 = 清空；其余类别不受影响）。"""
    return await _replace_binary(
        kind="pages",
        role_id=role_id,
        payload=payload,
        actor=actor,
        service=service,
        session=session,
    )


@router.put(
    "/roles/{role_id}/permissions/menus",
    summary="整体替换角色的菜单授权",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_UPDATE),
)
async def replace_role_menus(
    role_id: int,
    payload: RolePermissionIdsRequest,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """替换该角色的**菜单**授权集合（只影响导航可见性，不改变判权）。"""
    return await _replace_binary(
        kind="menus",
        role_id=role_id,
        payload=payload,
        actor=actor,
        service=service,
        session=session,
    )


@router.put(
    "/roles/{role_id}/permissions/buttons",
    summary="整体替换角色的按钮授权",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_UPDATE),
)
async def replace_role_buttons(
    role_id: int,
    payload: RolePermissionIdsRequest,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """替换该角色的**按钮**授权集合。

    `09 §5`：按钮授权只决定操作入口的可见性，
    对应 API 仍必须由后端独立授权 —— 两者不可互相替代。
    """
    return await _replace_binary(
        kind="buttons",
        role_id=role_id,
        payload=payload,
        actor=actor,
        service=service,
        session=session,
    )


@router.put(
    "/roles/{role_id}/permissions/apis",
    summary="整体替换角色的接口授权",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_UPDATE),
)
async def replace_role_apis(
    role_id: int,
    payload: RolePermissionIdsRequest,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """替换该角色的**后端接口**授权集合（`03 §8`：这是后端强制授权的依据）。"""
    return await _replace_binary(
        kind="apis",
        role_id=role_id,
        payload=payload,
        actor=actor,
        service=service,
        session=session,
    )


@router.put(
    "/roles/{role_id}/permissions/fields",
    summary="整体替换角色的字段权限",
    dependencies=_manage_dependency(AuditAction.ROLE_PERMISSION_UPDATE),
)
async def replace_role_fields(
    role_id: int,
    payload: RoleFieldPermissionsRequest,
    actor: CurrentActorDep,
    service: RolePermissionServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """替换该角色的**字段**权限（携带四级取值，DD-06 冻结）。

    同一字段被多个角色授予不同等级时，有效等级由**最宽松者胜**合并
    （`app.models.enums.most_permissive_field_level` 是唯一实现）——
    调用方只需如实提交本角色的等级，不要在客户端预合并。
    """
    view = await service.replace_fields(
        actor=actor,
        role_id=role_id,
        levels={item.resourceId: item.accessLevel for item in payload.fields},
    )
    await session.commit()
    return success_response(_permission_response(view))


@router.get(
    "/roles/{role_id}/data-scope",
    summary="角色数据范围",
    dependencies=_manage_dependency(AuditAction.ROLE_DATA_SCOPE_READ),
)
async def get_role_data_scope(
    role_id: int,
    actor: CurrentActorDep,
    service: RoleDataScopeServiceDep,
) -> JSONResponse:
    """读取角色的数据范围策略与（CUSTOM 时）部门集合。

    非 CUSTOM 角色的 `department_ids` **恒为空数组**：那样才是真实状态
    （关联表不应残留行，DD-07 的不变量）。返回残留行会让界面显示
    "配了 CUSTOM 部门但策略不是 CUSTOM"，属误导性数据。
    """
    view = await service.get(actor=actor, role_id=role_id)
    return success_response(_data_scope_response(view))


@router.put(
    "/roles/{role_id}/data-scope",
    summary="设置角色数据范围",
    dependencies=_manage_dependency(AuditAction.ROLE_DATA_SCOPE_UPDATE),
)
async def set_role_data_scope(
    role_id: int,
    payload: RoleDataScopeRequest,
    actor: CurrentActorDep,
    service: RoleDataScopeServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """设置角色的数据范围策略（`03 §10` 五值）。

    非 CUSTOM 策略携带非空 `departmentIds` 会被**拒绝**（400）而不是静默丢弃：
    静默丢弃会造成"以为已限定、实际未限定"的错觉（Spec `11 §5` 的取向）。
    """
    view = await service.set_scope(
        actor=actor,
        role_id=role_id,
        scope=payload.data_scope,
        department_ids=frozenset(payload.department_ids),
    )
    await session.commit()
    return success_response(_data_scope_response(view))


__all__ = ["router"]
