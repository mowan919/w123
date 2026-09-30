"""V3.1 结构层 CRUD 契约（VCTN §33，自动生成）。

本文件由 `scripts/gen_v31_crud.py` 生成；业务规则（§09-D 未冻结项）不在此处。
"""

from __future__ import annotations

import builtins
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BizUserLoginIdentityType
from app.schemas.types import SnowflakeId


class BizUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str
    status: str
    user_level_id: SnowflakeId
    must_change_password: bool
    password_changed_at: datetime | None
    password_expires_at: datetime | None
    last_login_at: datetime | None
    last_login_ip: str | None
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BizUserListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    status: str | None = Field(default=None)
    user_level_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    status: str | None = Field(default=None)
    user_level_id: SnowflakeId | None = Field(default=None)
    must_change_password: bool | None = Field(default=None)
    password_changed_at: datetime | None = Field(default=None)
    password_expires_at: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)
    last_login_ip: str | None = Field(default=None)


class BizUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None)
    status: str | None = Field(default=None)
    user_level_id: SnowflakeId | None = Field(default=None)
    must_change_password: bool | None = Field(default=None)
    password_changed_at: datetime | None = Field(default=None)
    password_expires_at: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)
    last_login_ip: str | None = Field(default=None)


class BizUserPageResponse(BaseModel):
    list: builtins.list[BizUserResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserLevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    level_value: int
    required_growth_points: int
    icon_url: str | None
    status: str
    sort_order: int
    description: str | None
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BizUserLevelListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    code: str | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserLevelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    level_value: int = Field()
    required_growth_points: int = Field()
    icon_url: str | None = Field(default=None)
    status: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    description: str | None = Field(default=None)


class BizUserLevelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    level_value: int | None = Field(default=None)
    required_growth_points: int | None = Field(default=None)
    icon_url: str | None = Field(default=None)
    status: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    description: str | None = Field(default=None)


class BizUserLevelPageResponse(BaseModel):
    list: builtins.list[BizUserLevelResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserLoginIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    identity_type: BizUserLoginIdentityType
    normalized_value: str
    verified: bool
    is_primary: bool
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserLoginIdentityListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserLoginIdentityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    identity_type: BizUserLoginIdentityType = Field(max_length=16)
    normalized_value: str = Field(max_length=255)
    verified: bool | None = Field(default=None)
    is_primary: bool | None = Field(default=None)


class BizUserLoginIdentityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    identity_type: BizUserLoginIdentityType | None = Field(default=None)
    normalized_value: str | None = Field(default=None)
    verified: bool | None = Field(default=None)
    is_primary: bool | None = Field(default=None)


class BizUserLoginIdentityPageResponse(BaseModel):
    list: builtins.list[BizUserLoginIdentityResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserLoginLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    success: bool
    fail_reason: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime
    id: int


class BizUserLoginLogListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserLoginLogCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    success: bool = Field()
    fail_reason: str | None = Field(default=None)
    ip: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)


class BizUserLoginLogUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    success: bool | None = Field(default=None)
    fail_reason: str | None = Field(default=None)
    ip: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)


class BizUserLoginLogPageResponse(BaseModel):
    list: builtins.list[BizUserLoginLogResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserPasswordHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserPasswordHistoryListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserPasswordHistoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()


class BizUserPasswordHistoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)


class BizUserPasswordHistoryPageResponse(BaseModel):
    list: builtins.list[BizUserPasswordHistoryResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    nickname: str | None
    avatar_url: str | None
    bio: str | None
    gender: str | None
    birthday: date | None
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserProfileListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    nickname: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None)
    bio: str | None = Field(default=None)
    gender: str | None = Field(default=None)
    birthday: date | None = Field(default=None)


class BizUserProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    nickname: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None)
    bio: str | None = Field(default=None)
    gender: str | None = Field(default=None)
    birthday: date | None = Field(default=None)


class BizUserProfilePageResponse(BaseModel):
    list: builtins.list[BizUserProfileResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    session_id: str
    ip: str | None
    user_agent: str | None
    login_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    id: int


class BizUserSessionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    session_id: str = Field(max_length=128)
    ip: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    login_at: datetime = Field()
    last_seen_at: datetime | None = Field(default=None)
    expires_at: datetime = Field()
    revoked_at: datetime | None = Field(default=None)
    revoke_reason: str | None = Field(default=None)


class BizUserSessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    session_id: str | None = Field(default=None)
    ip: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    login_at: datetime | None = Field(default=None)
    last_seen_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)
    revoke_reason: str | None = Field(default=None)


class BizUserSessionPageResponse(BaseModel):
    list: builtins.list[BizUserSessionResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    identity_type: str
    token_hash: str
    expires_at: datetime | None
    verified: bool
    created_at: datetime
    id: int


class BizUserVerificationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserVerificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    identity_type: str = Field(max_length=32)
    token_hash: str = Field(max_length=255)
    expires_at: datetime | None = Field(default=None)
    verified: bool | None = Field(default=None)


class BizUserVerificationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    identity_type: str | None = Field(default=None)
    token_hash: str | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    verified: bool | None = Field(default=None)


class BizUserVerificationPageResponse(BaseModel):
    list: builtins.list[BizUserVerificationResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


__all__ = [
    "BizUserCreateRequest",
    "BizUserLevelCreateRequest",
    "BizUserLevelListQuery",
    "BizUserLevelPageResponse",
    "BizUserLevelResponse",
    "BizUserLevelUpdateRequest",
    "BizUserListQuery",
    "BizUserLoginIdentityCreateRequest",
    "BizUserLoginIdentityListQuery",
    "BizUserLoginIdentityPageResponse",
    "BizUserLoginIdentityResponse",
    "BizUserLoginIdentityUpdateRequest",
    "BizUserLoginLogCreateRequest",
    "BizUserLoginLogListQuery",
    "BizUserLoginLogPageResponse",
    "BizUserLoginLogResponse",
    "BizUserLoginLogUpdateRequest",
    "BizUserPageResponse",
    "BizUserPasswordHistoryCreateRequest",
    "BizUserPasswordHistoryListQuery",
    "BizUserPasswordHistoryPageResponse",
    "BizUserPasswordHistoryResponse",
    "BizUserPasswordHistoryUpdateRequest",
    "BizUserProfileCreateRequest",
    "BizUserProfileListQuery",
    "BizUserProfilePageResponse",
    "BizUserProfileResponse",
    "BizUserProfileUpdateRequest",
    "BizUserResponse",
    "BizUserSessionCreateRequest",
    "BizUserSessionListQuery",
    "BizUserSessionPageResponse",
    "BizUserSessionResponse",
    "BizUserSessionUpdateRequest",
    "BizUserUpdateRequest",
    "BizUserVerificationCreateRequest",
    "BizUserVerificationListQuery",
    "BizUserVerificationPageResponse",
    "BizUserVerificationResponse",
    "BizUserVerificationUpdateRequest",
]
