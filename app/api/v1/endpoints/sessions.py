"""会话管理端点（Session Phase / Spec `08 §4`、`08 §5`）。

已实现的端点
-----------
| 方法 | 路径 | Spec 依据 |
|---|---|---|
| GET | `/sessions` | `08 §5` |
| POST | `/sessions/{id}/revoke` | `08 §5` |
| GET | `/users/{id}/sessions` | `08 §4` |
| POST | `/users/{id}/sessions/revoke-all` | `08 §4` |

为什么 `/users/{id}/sessions*` 也放在本模块
----------------------------------------
Spec `08 §4` 把这两个端点归在 Users 资源下（因为路径前缀是用户），
但它们的**业务语义是会话管理**：读的是 `sessions` 表，
做的是 `04 §4` 的踢下线，与 `/sessions/{id}/revoke` 共用
`SessionManagementService`、同一份数据范围与同一个 SUPER_ADMIN 保护。

若把它们拆到 users 模块，就会出现"同一条安全规则写在两个文件里" ——
这正是本项目在 Phase 2 已经踩过的坑。因此**按业务归属**放在一起，
并在本 docstring 显式说明路径归属与实现归属的差异。

用户 CRUD 端点（`08 §4` 其余部分）不属于本阶段，**刻意未实现**。

关于审计落库
----------
端点装配的服务默认使用 `NullAuditRecorder`（与 `/auth/*` 一致）：
审计事件在 Phase 2 起就通过端口产生，**落库属 Phase 6**
（`16 §34#8` DD-08 日志分区尚未冻结）。测试中注入内存记录器断言事件内容。

事务边界
-------
与 `/auth/*` 同一约定：**端点负责 `commit()`**，Service 只 flush。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    SessionManagementServiceDep,
)
from app.core.response import success_response
from app.schemas.session import (
    SessionListQuery,
    SessionPageResponse,
    SessionResponse,
    SessionRevokeResponse,
    UserSessionsRevokeResponse,
)
from app.services.session_management import SessionPage, SessionView

router = APIRouter(tags=["Session"])


def _session_response(view: SessionView) -> SessionResponse:
    """把会话视图映射为响应模型。"""
    user_session = view.session
    return SessionResponse(
        id=user_session.id,
        user_id=user_session.user_id,
        username=view.user.username,
        display_name=view.user.display_name,
        login_at=user_session.login_at,
        last_active_at=user_session.last_active_at,
        ip=user_session.ip,
        user_agent=user_session.user_agent,
        device=user_session.device,
        access_expires_at=user_session.expires_at,
        refresh_expires_at=user_session.refresh_expires_at,
        revoked_at=user_session.revoked_at,
        revoke_reason=user_session.revoke_reason,
        online=view.online,
    )


def _page_response(page: SessionPage) -> SessionPageResponse:
    """把分页结果映射为响应模型（人类裁定的 `{list,total,pageNum,pageSize}`）。"""
    return SessionPageResponse(
        list=[_session_response(view) for view in page.items],
        total=page.total,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


@router.get("/sessions", summary="会话列表（含在线用户查询）")
async def list_sessions(
    query: Annotated[SessionListQuery, Query()],
    actor: CurrentActorDep,
    service: SessionManagementServiceDep,
) -> JSONResponse:
    """分页列出数据范围内的会话。

    `?online=true` 即 Spec `04 §5` 的"后台在线用户查询"：
    只返回在线会话（未撤销、会话总寿命未过、所属用户 ACTIVE）。

    默认（`online=false`）返回**全部**会话，含已撤销 / 已过期 ——
    排查"某个登录为什么失效"恰恰需要看到已结束的会话。
    """
    page = await service.list_sessions(
        actor=actor,
        page_num=query.pageNum,
        page_size=query.pageSize,
        online_only=query.online,
    )
    return success_response(_page_response(page))


@router.post("/sessions/{session_id}/revoke", summary="撤销单个会话（踢下线）")
async def revoke_session(
    session_id: int,
    actor: CurrentActorDep,
    service: SessionManagementServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """撤销指定会话。

    幂等：已撤销的会话再次提交同样成功（`10 §7` 在两种情况下都已成立）。
    SUPER_ADMIN 的会话**任何**管理员都不能经此端点撤销（`00 §1#7` / `004 §13`），
    只能本人通过 `POST /auth/logout` 结束。
    """
    outcome = await service.revoke_session(actor=actor, session_id=session_id)
    await session.commit()

    return success_response(
        SessionRevokeResponse(
            id=outcome.session_id,
            revoked=outcome.revoked,
            already_revoked=outcome.already_revoked,
        )
    )


@router.get("/users/{user_id}/sessions", summary="查看某用户的会话")
async def list_user_sessions(
    user_id: int,
    query: Annotated[SessionListQuery, Query()],
    actor: CurrentActorDep,
    service: SessionManagementServiceDep,
) -> JSONResponse:
    """分页列出指定用户的会话（`08 §4`）。

    与 `/sessions` 使用同一份数据范围判定：目标用户不在范围内时返回 403，
    而不是返回空列表 —— 空列表会把"这个人不在我的范围里"与
    "这个人确实没有会话"混为一谈。
    """
    page = await service.list_user_sessions(
        actor=actor,
        user_id=user_id,
        page_num=query.pageNum,
        page_size=query.pageSize,
        online_only=query.online,
    )
    return success_response(_page_response(page))


@router.post("/users/{user_id}/sessions/revoke-all", summary="撤销某用户全部会话（踢下线）")
async def revoke_all_sessions(
    user_id: int,
    actor: CurrentActorDep,
    service: SessionManagementServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """撤销该用户**当前仍有效**的全部会话（`10 §7`：全部对应 Session 必须失效）。

    已到期或已撤销的会话不在本次操作范围内：
    给它们补写 `ADMIN_REVOKE` 会让审计无法区分"到期"与"被踢"。
    SUPER_ADMIN 的会话不能经此端点撤销（同 `POST /sessions/{id}/revoke`）。
    """
    outcome = await service.revoke_all_sessions(actor=actor, user_id=user_id)
    await session.commit()

    return success_response(
        UserSessionsRevokeResponse(
            user_id=outcome.user_id,
            revoked_count=outcome.revoked_count,
        )
    )


__all__ = ["router"]
