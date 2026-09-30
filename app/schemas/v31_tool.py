"""V3.1 结构层 CRUD 契约（VCTN §33，自动生成）。

本文件由 `scripts/gen_v31_crud.py` 生成；业务规则（§09-D 未冻结项）不在此处。
"""

from __future__ import annotations

import builtins
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ToolAccessSubjectType, ToolExecutionMode, ToolLifecycleStatus
from app.schemas.types import SnowflakeId


class ToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    category_id: SnowflakeId
    code: str
    name: str
    description: str | None
    component_key: str | None
    execution_mode: ToolExecutionMode
    lifecycle_status: ToolLifecycleStatus
    visibility: str
    sort_order: int
    is_recommended: bool
    tags: dict[str, Any] | None
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ToolListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    category_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    visibility: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_id: SnowflakeId = Field()
    code: str = Field(max_length=128)
    name: str = Field(max_length=128)
    description: str | None = Field(default=None)
    component_key: str | None = Field(default=None)
    execution_mode: ToolExecutionMode = Field(max_length=16)
    lifecycle_status: ToolLifecycleStatus | None = Field(default=None)
    visibility: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    is_recommended: bool | None = Field(default=None)
    tags: dict[str, Any] | None = Field(default=None)


class ToolUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    component_key: str | None = Field(default=None)
    execution_mode: ToolExecutionMode | None = Field(default=None)
    lifecycle_status: ToolLifecycleStatus | None = Field(default=None)
    visibility: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    is_recommended: bool | None = Field(default=None)
    tags: dict[str, Any] | None = Field(default=None)


class ToolPageResponse(BaseModel):
    list: builtins.list[ToolResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolAccessPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_id: SnowflakeId
    subject_type: ToolAccessSubjectType
    user_level_id: SnowflakeId
    enabled: bool
    quota_config: dict[str, Any] | None
    id: int
    created_at: datetime
    updated_at: datetime


class ToolAccessPolicyListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    tool_id: SnowflakeId | None = Field(default=None)
    user_level_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolAccessPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: SnowflakeId = Field()
    subject_type: ToolAccessSubjectType = Field(max_length=16)
    user_level_id: SnowflakeId | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    quota_config: dict[str, Any] | None = Field(default=None)


class ToolAccessPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: SnowflakeId | None = Field(default=None)
    subject_type: ToolAccessSubjectType | None = Field(default=None)
    user_level_id: SnowflakeId | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    quota_config: dict[str, Any] | None = Field(default=None)


class ToolAccessPolicyPageResponse(BaseModel):
    list: builtins.list[ToolAccessPolicyResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    parent_id: SnowflakeId
    code: str
    name: str
    icon_url: str | None
    sort_order: int
    status: str
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ToolCategoryListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    parent_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: SnowflakeId | None = Field(default=None)
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    icon_url: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    status: str | None = Field(default=None)


class ToolCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    icon_url: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    status: str | None = Field(default=None)


class ToolCategoryPageResponse(BaseModel):
    list: builtins.list[ToolCategoryResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolComponentRegistryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    component_key: str
    component_type: str
    implementation_ref: str
    status: str
    id: int
    created_at: datetime
    updated_at: datetime


class ToolComponentRegistryListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolComponentRegistryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_key: str = Field(max_length=128)
    component_type: str = Field(max_length=32)
    implementation_ref: str = Field(max_length=255)
    status: str | None = Field(default=None)


class ToolComponentRegistryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_key: str | None = Field(default=None)
    component_type: str | None = Field(default=None)
    implementation_ref: str | None = Field(default=None)
    status: str | None = Field(default=None)


class ToolComponentRegistryPageResponse(BaseModel):
    list: builtins.list[ToolComponentRegistryResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolPopularityDailyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_id: int
    stat_date: date
    score: float
    rank_no: int | None
    id: int


class ToolPopularityDailyListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolPopularityDailyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int = Field()
    stat_date: date = Field()
    score: float | None = Field(default=None)
    rank_no: int | None = Field(default=None)


class ToolPopularityDailyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int | None = Field(default=None)
    stat_date: date | None = Field(default=None)
    score: float | None = Field(default=None)
    rank_no: int | None = Field(default=None)


class ToolPopularityDailyPageResponse(BaseModel):
    list: builtins.list[ToolPopularityDailyResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolRecentUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    tool_id: SnowflakeId
    last_used_at: datetime
    use_count: int
    id: int


class ToolRecentUsageListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)
    tool_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolRecentUsageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    tool_id: SnowflakeId = Field()
    last_used_at: datetime | None = Field(default=None)
    use_count: int | None = Field(default=None)


class ToolRecentUsageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    tool_id: SnowflakeId | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)
    use_count: int | None = Field(default=None)


class ToolRecentUsagePageResponse(BaseModel):
    list: builtins.list[ToolRecentUsageResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolUsageDailyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_id: int
    stat_date: date
    total_count: int
    success_count: int
    failure_count: int
    guest_count: int
    user_count: int
    unique_user_count: int
    avg_duration_ms: float | None
    id: int


class ToolUsageDailyListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolUsageDailyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int = Field()
    stat_date: date = Field()
    total_count: int | None = Field(default=None)
    success_count: int | None = Field(default=None)
    failure_count: int | None = Field(default=None)
    guest_count: int | None = Field(default=None)
    user_count: int | None = Field(default=None)
    unique_user_count: int | None = Field(default=None)
    avg_duration_ms: float | None = Field(default=None)


class ToolUsageDailyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int | None = Field(default=None)
    stat_date: date | None = Field(default=None)
    total_count: int | None = Field(default=None)
    success_count: int | None = Field(default=None)
    failure_count: int | None = Field(default=None)
    guest_count: int | None = Field(default=None)
    user_count: int | None = Field(default=None)
    unique_user_count: int | None = Field(default=None)
    avg_duration_ms: float | None = Field(default=None)


class ToolUsageDailyPageResponse(BaseModel):
    list: builtins.list[ToolUsageDailyResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolUsageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_id: int
    user_id: SnowflakeId
    anonymous_id_hash: str | None
    result: str | None
    duration_ms: int | None
    execution_mode: str | None
    trace_id: str | None
    created_at: datetime
    id: int


class ToolUsageEventListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolUsageEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int = Field()
    user_id: SnowflakeId | None = Field(default=None)
    anonymous_id_hash: str | None = Field(default=None)
    result: str | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    execution_mode: str | None = Field(default=None)
    trace_id: str | None = Field(default=None)


class ToolUsageEventUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: int | None = Field(default=None)
    user_id: SnowflakeId | None = Field(default=None)
    anonymous_id_hash: str | None = Field(default=None)
    result: str | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    execution_mode: str | None = Field(default=None)
    trace_id: str | None = Field(default=None)


class ToolUsageEventPageResponse(BaseModel):
    list: builtins.list[ToolUsageEventResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class ToolVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tool_id: SnowflakeId
    version: str
    config: dict[str, Any] | None
    status: str
    published_at: datetime | None
    created_at: datetime
    id: int


class ToolVersionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    tool_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class ToolVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: SnowflakeId = Field()
    version: str = Field(max_length=64)
    config: dict[str, Any] | None = Field(default=None)
    status: str | None = Field(default=None)
    published_at: datetime | None = Field(default=None)


class ToolVersionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: SnowflakeId | None = Field(default=None)
    version: str | None = Field(default=None)
    config: dict[str, Any] | None = Field(default=None)
    status: str | None = Field(default=None)
    published_at: datetime | None = Field(default=None)


class ToolVersionPageResponse(BaseModel):
    list: builtins.list[ToolVersionResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


__all__ = [
    "ToolAccessPolicyCreateRequest",
    "ToolAccessPolicyListQuery",
    "ToolAccessPolicyPageResponse",
    "ToolAccessPolicyResponse",
    "ToolAccessPolicyUpdateRequest",
    "ToolCategoryCreateRequest",
    "ToolCategoryListQuery",
    "ToolCategoryPageResponse",
    "ToolCategoryResponse",
    "ToolCategoryUpdateRequest",
    "ToolComponentRegistryCreateRequest",
    "ToolComponentRegistryListQuery",
    "ToolComponentRegistryPageResponse",
    "ToolComponentRegistryResponse",
    "ToolComponentRegistryUpdateRequest",
    "ToolCreateRequest",
    "ToolListQuery",
    "ToolPageResponse",
    "ToolPopularityDailyCreateRequest",
    "ToolPopularityDailyListQuery",
    "ToolPopularityDailyPageResponse",
    "ToolPopularityDailyResponse",
    "ToolPopularityDailyUpdateRequest",
    "ToolRecentUsageCreateRequest",
    "ToolRecentUsageListQuery",
    "ToolRecentUsagePageResponse",
    "ToolRecentUsageResponse",
    "ToolRecentUsageUpdateRequest",
    "ToolResponse",
    "ToolUpdateRequest",
    "ToolUsageDailyCreateRequest",
    "ToolUsageDailyListQuery",
    "ToolUsageDailyPageResponse",
    "ToolUsageDailyResponse",
    "ToolUsageDailyUpdateRequest",
    "ToolUsageEventCreateRequest",
    "ToolUsageEventListQuery",
    "ToolUsageEventPageResponse",
    "ToolUsageEventResponse",
    "ToolUsageEventUpdateRequest",
    "ToolVersionCreateRequest",
    "ToolVersionListQuery",
    "ToolVersionPageResponse",
    "ToolVersionResponse",
    "ToolVersionUpdateRequest",
]
