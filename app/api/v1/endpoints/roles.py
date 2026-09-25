"""角色端点（`08 §7` 的**实体**部分）—— **FINDING-8-01 的补救交付**。

本模块与 `role_permissions.py` 的分工
-----------------------------------
`role_permissions.py` 负责角色的**权限配置面**
（`GET /roles/{id}/permissions`、`PUT .../{pages,menus,buttons,apis,fields}`、
`GET/PUT /roles/{id}/data-scope`），已在 Phase 8 交付。

本模块只补**实体 CRUD**：

- `GET/POST /roles`
- `PUT /roles/{id}`
- `POST /roles/{id}/delete`

为什么删除是 `POST /roles/{id}/delete` 而不是 `DELETE /roles/{id}`
----------------------------------------------------------------
这是 `08 §7` 冻结的写法。它看起来"不 REST"，但语义更准：
本系统的删除是**逻辑删除**（`00 §6`：`deleted_at`），
用 `DELETE` 会让"资源已不存在"与"资源被停用"在协议层无法区分。
沿用冻结写法，不自行"修正"成更符合直觉的形式 —— 契约不是审美问题。

为什么 `PUT /roles/{id}` 不能改 `role_code`
-----------------------------------------
编码是角色的稳定标识：SUPER_ADMIN 判定、API 资源引用、审计检索都依赖它。
允许改码会引入"把 SUPER_ADMIN 改名为其它码 → 系统静默失去超管入口"
这类跨模块后果。需要改码应当新建角色并迁移。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    RoleServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.response import success_response
from app.schemas.role import (
    RoleCreateRequest,
    RoleListQuery,
    RolePageResponse,
    RoleResponse,
    RoleUpdateRequest,
)
from app.services.authorization import ApiPermissionCode

router = APIRouter()

_MANAGE = ApiPermissionCode.ROLE_MANAGE


def _manage(action: AuditAction) -> list[Any]:
    """路由级依赖：需要 `ROLE_MANAGE`，拒绝写 FAILURE 审计。"""
    return [Depends(require_api_permission(_MANAGE, action=action, resource_type="ROLE"))]


@router.get(
    "/roles",
    summary="角色列表",
    dependencies=_manage(AuditAction.ROLE_READ),
)
async def list_roles(
    actor: CurrentActorDep,
    service: RoleServiceDep,
    query: Annotated[RoleListQuery, Query()],
) -> object:
    """分页列出角色。

    读也受 `ROLE_MANAGE` 约束：角色清单本身是敏感信息
    （暴露了系统的授权分层），不能对无权限者开放。
    """
    page = await service.list_roles(
        actor=actor,
        keyword=query.keyword,
        status=query.status,
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        RolePageResponse(
            list=[RoleResponse.model_validate(item) for item in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@router.post(
    "/roles",
    summary="创建角色",
    dependencies=_manage(AuditAction.ROLE_CREATE),
)
async def create_role(
    payload: RoleCreateRequest,
    actor: CurrentActorDep,
    service: RoleServiceDep,
    session: DbSessionDep,
) -> object:
    """创建角色。

    数据范围不在创建时设置（`08 §7` 走独立端点），
    新角色使用列的默认值 `DEPARTMENT_CHILDREN`（最保守的可用默认）。
    """
    role = await service.create(
        actor=actor,
        role_code=payload.role_code,
        role_name=payload.role_name,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(RoleResponse.model_validate(role))


@router.put(
    "/roles/{role_id}",
    summary="修改角色",
    dependencies=_manage(AuditAction.ROLE_UPDATE),
)
async def update_role(
    role_id: int,
    payload: RoleUpdateRequest,
    actor: CurrentActorDep,
    service: RoleServiceDep,
    session: DbSessionDep,
) -> object:
    """修改角色名称 / 描述 / 状态。**不含** `role_code` 与数据范围。"""
    role = await service.update(
        actor=actor,
        role_id=role_id,
        role_name=payload.role_name,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(RoleResponse.model_validate(role))


@router.post(
    "/roles/{role_id}/delete",
    summary="删除角色（逻辑删除）",
    dependencies=_manage(AuditAction.ROLE_DELETE),
)
async def delete_role(
    role_id: int,
    actor: CurrentActorDep,
    service: RoleServiceDep,
    session: DbSessionDep,
) -> object:
    """逻辑删除角色。

    他人的依赖（用户已持有、被继承）→ 拒绝 409；
    自己的从属（授权 / 字段权限 / CUSTOM 部门）→ 清理。
    绝不物理删除。
    """
    role = await service.delete(actor=actor, role_id=role_id)
    await session.commit()
    return success_response(RoleResponse.model_validate(role))
