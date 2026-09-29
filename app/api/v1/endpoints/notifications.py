"""站内通知端点 —— `DESIGN-DECISIONS §32`。

Spec 里**没有**这一域（`docs/spec/` 全 17 个文档对「消息 / 通知 / 公告」零提及），
因此下面两个路由组都是技术推导，口径见 `§32`。

两个路由组，两个前缀（这是本模块最需要看懂的一点）
==============================================

| 路由组 | 挂载前缀 | 端点 | 权限 |
|---|---|---|---|
| `self_router` | `/api/v1/auth` | `/notifications*` | 无权限位（只能读自己的） |
| `router` | `/api/v1/admin` | `/notifications/announcements*` | `NOTIFICATION_MANAGE` |

**收件箱为什么不在 admin 域**：`08 §1` 把 `/api/v1/admin` 定义为
"管理员资源域"，域名下的每个端点都要求一个 API 权限位。收件箱是
"我自己的消息"，任何已认证用户都有 —— 给它绑一个权限位等于要么
给所有角色都授这个位（权限位失去意义），要么让只读用户看不到自己的消息
（功能坏掉）。因此它按**既有先例**落在认证域：
`/auth/me`、`/auth/permissions`、`/auth/mfa*` 处理的全是"与我本人相关、
不需要数据范围语义"的东西，收件箱与它们同类
（见 `app/main.py` 里 mfa_router 的挂载注释）。

这与 Spec `08 §1` 的字面表述有张力，因此**逐条登记**在 `§32`：
若人类要求收件箱也进 admin 域，改动是"一处 include_router 前缀 +
本文件装饰器路径"，且必须同时给三个既有角色补授该权限位。

为什么端点里没有"读某个用户的收件箱"
==================================
因为它没有正当用途（管理端要看的是公告，不是别人的私信），
而它的存在本身就是一条越权读入口。收件人恒取自 `actor.user_id`。

路由声明顺序（照抄 Phase 8 的教训）
================================
静态路径（`/unread-count`、`/read-all`）必须声明在带参数的路径**之前**。
`/notifications/read-all` 与 `/notifications/{notification_id}/read`
在当前形状下不冲突（段数不同），但把静态路径放前面是一条零成本的纪律 ——
Phase 8 的 `/permission-resources/tree` 被当成 int 解析成 422 就是这么来的，
而且两个装饰器**各自都"正确"**，只能靠真实请求发现。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    NotificationServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.response import success_response
from app.models.notification import Announcement, Notification
from app.schemas.notification import (
    AnnouncementCreateRequest,
    AnnouncementListQuery,
    AnnouncementPageResponse,
    AnnouncementPublishResponse,
    AnnouncementResponse,
    AnnouncementRevokeResponse,
    MarkAllReadResponse,
    NotificationListQuery,
    NotificationPageResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from app.services.authorization import ApiPermissionCode
from app.services.notification import (
    RESOURCE_TYPE_ANNOUNCEMENT,
    AnnouncementPage,
    NotificationPage,
)

#: 自助收件箱路由组（挂载在认证域 `/api/v1/auth`）。
self_router = APIRouter(tags=["Notification"])
#: 管理端公告路由组（挂载在 `/api/v1/admin`）。
router = APIRouter(tags=["Notification"])

_MANAGE = ApiPermissionCode.NOTIFICATION_MANAGE


def _notification_response(notification: Notification) -> NotificationResponse:
    """把通知 ORM 对象映射为响应模型。

    刻意**不**下发 `user_id`：调用方只可能是收件人本人，
    回显一个"这条消息属于谁"的字段既无用又多一处可比对的面。
    """
    return NotificationResponse(
        id=notification.id,
        category=notification.category,
        event_code=notification.event_code,
        announcement_id=notification.announcement_id,
        title=notification.title,
        body=notification.body,
        link=notification.link,
        level=notification.level,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


def _page_response(page: NotificationPage) -> NotificationPageResponse:
    return NotificationPageResponse(
        list=[_notification_response(item) for item in page.items],
        total=page.total,
        unread=page.unread,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


def _announcement_response(announcement: Announcement) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=announcement.id,
        title=announcement.title,
        body=announcement.body,
        level=announcement.level,
        audience_type=announcement.audience_type,
        audience_role_id=announcement.audience_role_id,
        recipient_count=announcement.recipient_count,
        created_by_username=announcement.created_by_username,
        created_at=announcement.created_at,
    )


def _announcement_page_response(page: AnnouncementPage) -> AnnouncementPageResponse:
    return AnnouncementPageResponse(
        list=[_announcement_response(item) for item in page.items],
        total=page.total,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


# ---------------------------------------------------------------- 自助收件箱


@self_router.get("/notifications", summary="我的站内通知列表")
async def list_my_notifications(
    query: Annotated[NotificationListQuery, Query()],
    actor: CurrentActorDep,
    service: NotificationServiceDep,
) -> JSONResponse:
    """分页列出我的收件箱（新的在前），并附上未读总数。

    响应里带 `unread` 是刻意的：角标与列表在界面上总是同时出现，
    分两次请求会让两者在慢网络上短暂不一致（见 schema 模块文档）。
    """
    page = await service.list_mine(
        actor=actor,
        unread_only=query.unreadOnly,
        category=query.category,
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(_page_response(page))


@self_router.get("/notifications/unread-count", summary="我的未读通知数（角标）")
async def my_unread_count(
    actor: CurrentActorDep,
    service: NotificationServiceDep,
) -> JSONResponse:
    """只返回一个整数（顶栏角标轮询用）。

    单独成一个端点而不是"取第一页顺便算"：角标每 60 秒轮询一次，
    走列表接口意味着每次都要读一页完整正文。
    """
    unread = await service.unread_count(actor=actor)
    return success_response(NotificationUnreadCountResponse(unread=unread))


@self_router.post("/notifications/read-all", summary="全部标记为已读")
async def mark_all_my_notifications_read(
    actor: CurrentActorDep,
    service: NotificationServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """把我**全部未读**标记为已读。

    幂等：没有未读时返回 `updated=0` 而不是报错 ——
    界面上"点一条已读"和"点全部已读"可能几乎同时发生，
    报错会让用户以为操作失败。
    """
    updated = await service.mark_all_read(actor=actor)
    await session.commit()
    return success_response(MarkAllReadResponse(updated=updated))


@self_router.post("/notifications/{notification_id}/read", summary="标记一条为已读")
async def mark_my_notification_read(
    notification_id: int,
    actor: CurrentActorDep,
    service: NotificationServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """把**我的一条**通知标记为已读。

    不属于我的 ID 返回 **404**（而不是 403）：区分"不存在"与"存在但不是你的"
    等于把"这个 ID 上有别人的消息"这件事泄给调用方。
    """
    notification = await service.mark_read(actor=actor, notification_id=notification_id)
    await session.commit()
    return success_response(_notification_response(notification))


# ---------------------------------------------------------------- 管理端公告


@router.get(
    "/notifications/announcements",
    summary="已发布公告列表",
    dependencies=[
        Depends(
            require_api_permission(
                _MANAGE,
                action=AuditAction.NOTIFICATION_ANNOUNCE,
                resource_type=RESOURCE_TYPE_ANNOUNCEMENT,
            )
        )
    ],
)
async def list_announcements(
    query: Annotated[AnnouncementListQuery, Query()],
    actor: CurrentActorDep,
    service: NotificationServiceDep,
) -> JSONResponse:
    """分页列出已发布（未撤回）的公告，含发布人与当时的收件人数。"""
    page = await service.list_announcements(
        actor=actor, page_num=query.pageNum, page_size=query.pageSize
    )
    return success_response(_announcement_page_response(page))


@router.post(
    "/notifications/announcements",
    summary="发布公告",
    dependencies=[
        Depends(
            require_api_permission(
                _MANAGE,
                action=AuditAction.NOTIFICATION_ANNOUNCE,
                resource_type=RESOURCE_TYPE_ANNOUNCEMENT,
            )
        )
    ],
)
async def publish_announcement(
    payload: AnnouncementCreateRequest,
    actor: CurrentActorDep,
    service: NotificationServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """发布一条公告并扇出到受众的收件箱。

    `audience_type=ROLE` 时必须给 `audience_role_id`，`ALL` 时不得给 ——
    两者矛盾返回 400（数据库上的 `ck_announcements_audience_role_consistent`
    是最终保证，这里的校验只负责给出可读报错而不是 500）。
    """
    result = await service.announce(
        actor=actor,
        title=payload.title,
        body=payload.body,
        level=payload.level,
        audience_type=payload.audience_type,
        audience_role_id=payload.audience_role_id,
    )
    await session.commit()
    return success_response(
        AnnouncementPublishResponse(
            announcement=_announcement_response(result.announcement),
            recipient_count=result.recipient_count,
        )
    )


@router.post(
    "/notifications/announcements/{announcement_id}/revoke",
    summary="撤回公告",
    dependencies=[
        Depends(
            require_api_permission(
                _MANAGE,
                action=AuditAction.NOTIFICATION_REVOKE,
                resource_type=RESOURCE_TYPE_ANNOUNCEMENT,
            )
        )
    ],
)
async def revoke_announcement(
    announcement_id: int,
    actor: CurrentActorDep,
    service: NotificationServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """撤回公告：连同它扇出的收件箱行一起逻辑删除。

    ⚠️ 已经被人读过的内容**收不回来**。界面上必须明说这一点
    （`§32` 记为已知代价），否则撤回会给人"消息没发出去"的错觉。
    """
    purged = await service.revoke_announcement(actor=actor, announcement_id=announcement_id)
    await session.commit()
    return success_response(AnnouncementRevokeResponse(id=announcement_id, purged=purged))


__all__ = ["router", "self_router"]
