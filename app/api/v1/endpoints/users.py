"""用户端点（`08 §4`）—— **FINDING-8-01 的补救交付**。

为什么这个模块直到 Phase 9 才出现
--------------------------------
`08 §4` 早就冻结了下面这组端点，但 Phase 1 / Phase 2 的验收裁判
（`001` / `002`）**全部是服务层判定**，不含端点存在性，
因此那两个阶段 PASS 时不会暴露"HTTP 面根本不存在"这个缺口。
它是在 Phase 8 写契约测试时才被发现的，登记为 FINDING-8-01。

本模块**不**修补历史，只把冻结的端点补上；服务层能力早已就位
（`app/services/user.py`），因此这里只做接线。

`status` 与口令为什么不在这里改
------------------------------
`PUT /users/{id}` 的请求体刻意**不含** `status` 与任何口令字段：
禁用 / 启用走 `/disable`、`/enable`，重置口令走 `/reset-password`。
原因不是"路径好看"，而是 `10 §8` 要求这些动作可审计 ——
若允许在通用 PUT 里改状态，那么审计里就分不清
"改了个显示名"与"把某人禁用了"。

数据范围
--------
列表与读都经由 `UserService`，它在服务层把数据范围**下推到 SQL**
（`list_in_scope`），因此越权目标表现为"看不到"，而不是"看到了再拒绝"。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    UserServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.response import success_response
from app.schemas.user import (
    UserCreateRequest,
    UserListQuery,
    UserPageResponse,
    UserResetPasswordRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.authorization import ApiPermissionCode
from app.services.user import UNSET

router = APIRouter()

_MANAGE = ApiPermissionCode.USER_MANAGE


def _manage(action: AuditAction) -> list[Any]:
    """路由级依赖：需要 `USER_MANAGE`，拒绝写 FAILURE 审计。"""
    return [Depends(require_api_permission(_MANAGE, action=action, resource_type="USER"))]


@router.get(
    "/users",
    summary="用户列表",
    dependencies=_manage(AuditAction.USER_READ),
)
async def list_users(
    actor: CurrentActorDep,
    service: UserServiceDep,
    query: Annotated[UserListQuery, Query()],
) -> object:
    """分页列出**数据范围内**的用户。"""
    page = await service.list_users(
        actor=actor,
        page_num=query.pageNum,
        page_size=query.pageSize,
        department_id=query.department_id,
        status=query.status,
        keyword=query.keyword,
    )
    # 领域对象 → 响应 DTO：分页协议（`{list,total,pageNum,pageSize}`）是
    # **对外契约**，不能让服务层的 `items/page_num/...` 直接漏到 HTTP 层。
    return success_response(
        UserPageResponse(
            list=[UserResponse.model_validate(item) for item in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@router.post(
    "/users",
    summary="创建用户",
    dependencies=_manage(AuditAction.USER_CREATE),
)
async def create_user(
    payload: UserCreateRequest,
    actor: CurrentActorDep,
    service: UserServiceDep,
    session: DbSessionDep,
) -> object:
    """创建用户。

    新建用户会被标记为 `must_change_password`（Phase 2 的 RISK-001 裁定），
    否则管理员设的初始口令会成为长期有效的共享口令。
    """
    user = await service.create(
        actor=actor,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        department_id=payload.department_id,
        phone=payload.phone,
        email=payload.email,
        role_ids=frozenset(payload.role_ids) if payload.role_ids is not None else None,
    )
    await session.commit()
    return success_response(UserResponse.model_validate(user))


@router.get(
    "/users/{user_id}",
    summary="用户详情",
    dependencies=_manage(AuditAction.USER_READ),
)
async def get_user(
    user_id: int,
    actor: CurrentActorDep,
    service: UserServiceDep,
) -> object:
    """读取单个用户；范围外用户按不存在处理（不泄露存在性）。"""
    user = await service.get(actor=actor, user_id=user_id)
    return success_response(UserResponse.model_validate(user))


@router.put(
    "/users/{user_id}",
    summary="修改用户",
    dependencies=_manage(AuditAction.USER_UPDATE),
)
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    actor: CurrentActorDep,
    service: UserServiceDep,
    session: DbSessionDep,
) -> object:
    """修改显示名 / 联系方式 / 所属部门。

    ## 为什么必须按"客户端是否真的传了"来分派（FINDING-9-02）

    `phone` / `email` / `department_id` 是**三态**字段：
    未传 = 不要动，显式 `null` = 清空 / 移出部门，具体值 = 设为该值。
    DTO 的默认值是 `None`，若直接把 `payload.x` 原样传给服务层，
    "只想改个显示名"就会被解释成"顺便把用户移出部门" ——
    在非全局数据范围下那会直接 403，在全局范围下则是**静默的数据破坏**。

    因此这里用 `model_fields_set` 判断客户端实际提交了哪些字段，
    未提交的显式传 `UNSET`。
    """
    sent = payload.model_fields_set
    user = await service.update(
        actor=actor,
        user_id=user_id,
        username=payload.username,
        display_name=payload.display_name,
        phone=payload.phone if "phone" in sent else UNSET,
        email=payload.email if "email" in sent else UNSET,
        department_id=payload.department_id if "department_id" in sent else UNSET,
    )
    await session.commit()
    return success_response(UserResponse.model_validate(user))


@router.post(
    "/users/{user_id}/disable",
    summary="禁用用户",
    dependencies=_manage(AuditAction.USER_DISABLE),
)
async def disable_user(
    user_id: int,
    actor: CurrentActorDep,
    service: UserServiceDep,
    session: DbSessionDep,
) -> object:
    """禁用用户。

    禁止禁用**最后一个** SUPER_ADMIN（Phase 2 的 RISK-002 裁定），
    否则系统会永久失去超管入口。
    """
    user = await service.disable(actor=actor, user_id=user_id)
    await session.commit()
    return success_response(UserResponse.model_validate(user))


@router.post(
    "/users/{user_id}/enable",
    summary="启用用户",
    dependencies=_manage(AuditAction.USER_ENABLE),
)
async def enable_user(
    user_id: int,
    actor: CurrentActorDep,
    service: UserServiceDep,
    session: DbSessionDep,
) -> object:
    """启用用户。"""
    user = await service.enable(actor=actor, user_id=user_id)
    await session.commit()
    return success_response(UserResponse.model_validate(user))


@router.post(
    "/users/{user_id}/reset-password",
    summary="重置用户口令",
    dependencies=_manage(AuditAction.USER_RESET_PASSWORD),
)
async def reset_password(
    user_id: int,
    payload: UserResetPasswordRequest,
    actor: CurrentActorDep,
    service: UserServiceDep,
    session: DbSessionDep,
) -> object:
    """重置口令；重置后该用户下次登录必须改密。

    响应**不回显**新口令，也**不含** `password_hash`。
    """
    user = await service.reset_password(
        actor=actor, user_id=user_id, new_password=payload.new_password
    )
    await session.commit()
    return success_response(UserResponse.model_validate(user))
