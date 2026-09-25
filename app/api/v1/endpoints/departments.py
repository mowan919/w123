"""部门端点（`08 §6`）—— **FINDING-8-01 的补救交付**。

为什么**没有** `DELETE /departments/{id}`
---------------------------------------
`08 §6` 冻结的清单里只有 `POST /departments/{id}/disable`，没有删除端点。
服务层确实实现了逻辑删除（`DepartmentService.delete`），但
"服务层有能力"不等于"契约允许暴露" —— 冻结的端点清单是**对外承诺**，
自行加一条等于在没有需求的地方发明 API 面，
既增加待冻结项，也让 Phase 10 的路径比对失去意义。

`GET /departments/tree` 为什么不是 `GET /departments`
---------------------------------------------------
`08 §6` 只冻结了树这一个读端点。部门在业务上确实是树形结构，
因此"只要树"是完整表达，不需要再引入一个平铺列表 ——
那会给出第二种、且更容易越权的读取形态。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    DepartmentServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.response import success_response
from app.schemas.department import (
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentTreeNodeResponse,
    DepartmentUpdateRequest,
)
from app.services.authorization import ApiPermissionCode
from app.services.department import UNSET

router = APIRouter()

_MANAGE = ApiPermissionCode.DEPARTMENT_MANAGE


def _manage(action: AuditAction) -> list[Any]:
    """路由级依赖：需要 `DEPARTMENT_MANAGE`，拒绝写 FAILURE 审计。"""
    return [Depends(require_api_permission(_MANAGE, action=action, resource_type="DEPARTMENT"))]


@router.get(
    "/departments/tree",
    summary="部门树",
    dependencies=_manage(AuditAction.DEPARTMENT_READ),
)
async def tree(actor: CurrentActorDep, service: DepartmentServiceDep) -> object:
    """返回**数据范围内**的部门树。

    范围外的节点不会出现；范围内但父节点在范围外的"孤儿"按根呈现，
    否则前端会丢掉整棵子树。
    """
    nodes = await service.list_tree(actor=actor)
    return success_response([DepartmentTreeNodeResponse.model_validate(node) for node in nodes])


@router.post(
    "/departments",
    summary="创建部门",
    dependencies=_manage(AuditAction.DEPARTMENT_CREATE),
)
async def create(
    payload: DepartmentCreateRequest,
    actor: CurrentActorDep,
    service: DepartmentServiceDep,
    session: DbSessionDep,
) -> object:
    """创建部门。

    非全局数据范围不允许创建根部门（服务层守卫）。
    """
    department = await service.create(
        actor=actor,
        department_code=payload.department_code,
        department_name=payload.department_name,
        parent_id=payload.parent_id,
    )
    await session.commit()
    return success_response(DepartmentResponse.model_validate(department))


@router.put(
    "/departments/{department_id}",
    summary="修改部门",
    dependencies=_manage(AuditAction.DEPARTMENT_UPDATE),
)
async def update(
    department_id: int,
    payload: DepartmentUpdateRequest,
    actor: CurrentActorDep,
    service: DepartmentServiceDep,
    session: DbSessionDep,
) -> object:
    """修改编码 / 名称 / 父部门。

    `status` 不在此处修改（DTO 里也没有该字段）——
    禁用必须走 `/disable`，否则 `DEPARTMENT_DISABLE` 审计可被绕过。

    `parent_id` 是**三态**字段（未传 / 显式 null / 具体值），
    与用户端点同一处理（FINDING-9-02）：未传的字段传 `UNSET`，
    绝不折叠成 `None` —— 否则一次改名会意外把部门挪到根层级
    （非全局范围下还会直接 403）。
    """
    department = await service.update(
        actor=actor,
        department_id=department_id,
        department_code=payload.department_code,
        department_name=payload.department_name,
        parent_id=payload.parent_id if "parent_id" in payload.model_fields_set else UNSET,
    )
    await session.commit()
    return success_response(DepartmentResponse.model_validate(department))


@router.post(
    "/departments/{department_id}/disable",
    summary="禁用部门",
    dependencies=_manage(AuditAction.DEPARTMENT_DISABLE),
)
async def disable(
    department_id: int,
    actor: CurrentActorDep,
    service: DepartmentServiceDep,
    session: DbSessionDep,
) -> object:
    """禁用部门（逻辑删除之外的"停用"语义）。"""
    department = await service.disable(actor=actor, department_id=department_id)
    await session.commit()
    return success_response(DepartmentResponse.model_validate(department))
