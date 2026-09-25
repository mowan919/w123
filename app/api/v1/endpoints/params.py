"""系统参数端点（Phase 7 / Spec `05 §5`）。

端点清单（INTERIM-7-04 —— 路径属技术推导）
---------------------------------------
| 方法 | 路径 |
|---|---|
| GET | `/params` |
| POST | `/params` |
| GET | `/params/{id}` |
| PUT | `/params/{id}` |
| DELETE | `/params/{id}` |

**Spec 没有给出系统参数的端点**：`05 §5` 只规定"System Parameter 与
Dictionary 分离"以及"参数必须有类型、默认值、状态、描述和审计"，
`08 §9` 的 Endpoint 清单里也只有 Dictionary。而"审计"这一条要求
隐含了"存在可调用的管理接口"（否则参数只能靠直接改库，落不进审计）。

因此路径按 `08 §1` 的 admin Base + 与 `/dicts` 对称的资源名推导：

```text
/api/v1/admin + /params
```

登记为 INTERIM-7-04。改动面：一处 include_router 前缀 + 本文件的路由装饰器。

与 `/dicts` 刻意保持对称
----------------------
字典与参数的资源形状（列表 / 详情 / 修改 / 逻辑删除）完全一致，
因此端点形状也一致。唯一多出来的是 `effective_value`（计算字段）
与 `clear_value`（显式清空当前值）—— 前者表达"哪一个是生效值"这条规则，
后者让 `param_value` 能回到 `null`（否则"默认值"没有落点）。

事务边界
-------
与既有端点同一约定：**端点负责 `commit()`**，Service 只 `flush()`。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import CurrentActorDep, DbSessionDep, SystemParamServiceDep
from app.core.response import success_response
from app.models.param import SysParam
from app.schemas.param import (
    SystemParamCreateRequest,
    SystemParamListQuery,
    SystemParamPageResponse,
    SystemParamResponse,
    SystemParamUpdateRequest,
)
from app.services.system_param import SystemParamPage

router = APIRouter(tags=["SystemParameter"])


def _param_response(param: SysParam) -> SystemParamResponse:
    """把参数 ORM 对象映射为响应模型，并算出**生效值**。

    `effective_value = param_value ?? default_value` 由服务端计算下发：
    若让每个客户端自己写 `param_value or default_value`，
    回退规则就会在客户端各实现一遍，后端一旦调整（例如新增环境层）
    客户端无法跟随 —— 那正是"第二份真相"。
    """
    return SystemParamResponse(
        id=param.id,
        param_key=param.param_key,
        param_name=param.param_name,
        param_type=param.param_type,
        param_value=param.param_value,
        default_value=param.default_value,
        effective_value=(
            param.param_value if param.param_value is not None else param.default_value
        ),
        status=param.status,
        description=param.description,
        created_at=param.created_at,
        updated_at=param.updated_at,
    )


def _page_response(page: SystemParamPage) -> SystemParamPageResponse:
    """把分页结果映射为响应模型（`{list,total,pageNum,pageSize}`）。"""
    return SystemParamPageResponse(
        list=[_param_response(item) for item in page.items],
        total=page.total,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


@router.get("/params", summary="系统参数列表")
async def list_params(
    query: Annotated[SystemParamListQuery, Query()],
    actor: CurrentActorDep,
    service: SystemParamServiceDep,
) -> JSONResponse:
    """分页列出系统参数（`05 §5`）。

    含停用（`status=DISABLED`）的参数 —— 排查"某个开关为什么不起作用"
    恰恰需要看到它已被停用。
    """
    page = await service.list_params(
        actor=actor,
        keyword=query.keyword,
        status=query.status,
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(_page_response(page))


@router.post("/params", summary="创建系统参数")
async def create_param(
    payload: SystemParamCreateRequest,
    actor: CurrentActorDep,
    service: SystemParamServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """创建系统参数。

    `default_value` 与 `param_value` 都必须符合 `param_type`，
    否则返回 400 —— 把"配置错误"挡在写入侧，而不是推迟到读取侧
    （读取侧 fail-closed 会发生在登录这类热路径上）。
    """
    param = await service.create_param(
        actor=actor,
        param_key=payload.param_key,
        param_name=payload.param_name,
        param_type=payload.param_type,
        default_value=payload.default_value,
        param_value=payload.param_value,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(_param_response(param))


@router.get("/params/{param_id}", summary="系统参数详情")
async def get_param(
    param_id: int,
    actor: CurrentActorDep,
    service: SystemParamServiceDep,
) -> JSONResponse:
    """按 ID 读取系统参数。"""
    param = await service.get_param(actor=actor, param_id=param_id)
    return success_response(_param_response(param))


@router.put("/params/{param_id}", summary="修改系统参数")
async def update_param(
    param_id: int,
    payload: SystemParamUpdateRequest,
    actor: CurrentActorDep,
    service: SystemParamServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """修改参数名称 / 默认值 / 当前值 / 描述 / 状态。

    `param_key` 与 `param_type` 不可修改（见 `SystemParameterService` 模块文档）；
    `clear_value=true` 表示把当前值清空以回落到默认值，
    它与"提供了 `param_value`"互斥（同时给出返回 400）。
    """
    param = await service.update_param(
        actor=actor,
        param_id=param_id,
        param_name=payload.param_name,
        default_value=payload.default_value,
        param_value=payload.param_value,
        clear_value=payload.clear_value,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(_param_response(param))


@router.delete("/params/{param_id}", summary="删除系统参数（逻辑删除）")
async def delete_param(
    param_id: int,
    actor: CurrentActorDep,
    service: SystemParamServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """逻辑删除系统参数。

    删除后读取方按"未配置"处理并回退到内置默认值（例如 MFA 的
    system 级默认值回退到环境变量）。这条回退路径的代价与缓解
    见 `SystemParameterService` 模块文档第 1 条；删除本身是有权限、
    有审计的操作，因此"谁把安全开关删掉了"是可追溯的。
    """
    param = await service.delete_param(actor=actor, param_id=param_id)
    await session.commit()
    return success_response(_param_response(param))


__all__ = ["router"]
