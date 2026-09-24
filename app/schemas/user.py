"""用户 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `08 §4`：`GET/POST /users`、`GET/PUT /users/{id}`、
  `POST /users/{id}/disable`、`/enable`、`/reset-password`
  （人类裁定补齐 `POST /users/{id}/delete` 与 `GET|PUT /users/{id}/roles`）。
- Spec `08 §2`：`/api/v1/admin` 前缀；响应信封 `{code, message, data}`。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `02 §2` 用户字段；`02 §3` 状态 ACTIVE / DISABLED / LOCKED。
- Spec `02 §4` 多角色；`02 §5` 删除 = disable + logical delete。
- Spec `10 §4`：`password_hash` 绝不返回、绝不记录 → 响应模型**不含**该字段。
- 人类裁定：分页请求参数为 `pageNum` + `pageSize`，
  响应形如 `{list, total, pageNum, pageSize}`。

本 Phase 边界
------------
HTTP 端点层按人类裁定**暂不挂载**（认证在 Phase 4 落地后才有 `CurrentActor`）。
本模块只交付契约，不含路由装饰器，也不调用 Service。

关于手机号 / 邮箱是否脱敏
----------------------
Spec `00 §8` / `06 §4` 要求**日志与审计**脱敏；
本模块的响应模型面向"有数据范围权限的管理员"，返回真实值（否则无法维护用户），
脱敏由 `app.core.masking` 在日志 / 审计链路完成。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserStatus
from app.schemas.role import RoleSummaryResponse
from app.schemas.types import SnowflakeId

#: Spec 未冻结字段长度，此处与 model 列长度保持一致（INTERIM 技术取值）。
_USERNAME_MAX = 64
_DISPLAY_NAME_MAX = 128
_PHONE_MAX = 32
_EMAIL_MAX = 255
#: 口令长度上界仅用于拒绝明显异常的输入；
#: **复杂度策略的唯一判定点是** `app.core.security.password`
#: （SSOT），schema 层不重复实现，避免两处规则漂移。
_PASSWORD_MAX = 256

_PAGE_SIZE_MAX = 100


class UserListQuery(BaseModel):
    """`GET /users` 查询参数。

    注意 `pageNum` / `pageSize` 为人类裁定的驼峰命名，
    其余字段遵循 AGENTS.md §6 的 snake_case。
    """

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX, description="每页条数，1..100")
    department_id: SnowflakeId | None = Field(
        default=None, description="按部门过滤（与数据范围取交集）"
    )
    status: UserStatus | None = Field(default=None, description="按状态过滤")
    keyword: str | None = Field(
        default=None, max_length=64, description="按登录名 / 显示名模糊匹配"
    )


class UserCreateRequest(BaseModel):
    """`POST /users` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=_USERNAME_MAX, description="登录名")
    password: str = Field(
        min_length=1,
        max_length=_PASSWORD_MAX,
        description="初始口令；复杂度由服务端策略校验，绝不回显、绝不记录",
    )
    display_name: str = Field(min_length=1, max_length=_DISPLAY_NAME_MAX, description="显示名称")
    department_id: SnowflakeId | None = Field(
        default=None, description="所属部门；非全局数据范围必须落在范围内"
    )
    phone: str | None = Field(default=None, max_length=_PHONE_MAX)
    email: str | None = Field(default=None, max_length=_EMAIL_MAX)
    role_ids: list[SnowflakeId] | None = Field(
        default=None,
        description="初始角色集合；授予 SUPER_ADMIN 仅 SUPER_ADMIN 可操作",
    )


class UserUpdateRequest(BaseModel):
    """`PUT /users/{id}` 请求体。

    有意**不包含** `status` 与口令字段：
    禁用 / 启用走 `/disable`、`/enable`，口令走 `/reset-password`，
    以保证对应审计动作不可被绕过（Spec `10 §8`）。
    """

    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1, max_length=_USERNAME_MAX)
    display_name: str | None = Field(default=None, min_length=1, max_length=_DISPLAY_NAME_MAX)
    phone: str | None = Field(default=None, max_length=_PHONE_MAX)
    email: str | None = Field(default=None, max_length=_EMAIL_MAX)
    department_id: SnowflakeId | None = Field(
        default=None, description="目标部门；显式 null 表示移出部门（仅全局范围允许）"
    )


class UserResetPasswordRequest(BaseModel):
    """`POST /users/{id}/reset-password` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(
        min_length=1,
        max_length=_PASSWORD_MAX,
        description="新口令；重置后该用户首次登录必须改密",
    )


class UserRolesUpdateRequest(BaseModel):
    """`PUT /users/{id}/roles` 请求体（整体替换语义）。"""

    model_config = ConfigDict(extra="forbid")

    role_ids: list[SnowflakeId] = Field(
        default_factory=list,
        description="替换后的完整角色集合；空数组表示清空角色",
    )


class UserResponse(BaseModel):
    """用户实体响应。

    **绝不包含** `password_hash`（Spec `10 §4`）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="用户 ID（JSON 为字符串）")
    username: str
    display_name: str
    phone: str | None = None
    email: str | None = None
    department_id: SnowflakeId | None = None
    status: UserStatus
    failed_login_count: int
    locked_until: datetime | None = None
    password_changed_at: datetime | None = None
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class UserPageResponse(BaseModel):
    """`GET /users` 分页响应（人类裁定的字段命名）。

    `list` 字段名由人类裁定固定，但会遮蔽内建 `list`：
    注解与默认工厂均显式走 `builtins.list`，避免 Pydantic 解析注解时
    在类命名空间里取到 `FieldInfo` 而报 "not subscriptable"。
    """

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[UserResponse] = Field(default_factory=builtins.list)
    total: int = Field(description="范围内的总条数")
    pageNum: int
    pageSize: int


class UserRolesResponse(BaseModel):
    """`GET /users/{id}/roles` 响应。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: SnowflakeId
    roles: list[RoleSummaryResponse] = Field(default_factory=list)


__all__ = [
    "UserCreateRequest",
    "UserListQuery",
    "UserPageResponse",
    "UserResetPasswordRequest",
    "UserResponse",
    "UserRolesResponse",
    "UserRolesUpdateRequest",
    "UserUpdateRequest",
]
