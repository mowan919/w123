"""V3.1 结构层 CRUD 契约（VCTN §33，自动生成）。

本文件由 `scripts/gen_v31_crud.py` 生成；业务规则（§09-D 未冻结项）不在此处。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CosmeticType
from app.schemas.types import SnowflakeId


class BizAchievementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    icon_url: str | None
    achievement_type: str
    target_value: int | None
    reward_growth_points: int
    reward_points: int
    reward_cosmetic_id: SnowflakeId
    status: str
    id: int
    created_at: datetime
    updated_at: datetime


class BizAchievementListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    code: str | None = Field(default=None)
    reward_cosmetic_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizAchievementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    icon_url: str | None = Field(default=None)
    achievement_type: str = Field(max_length=64)
    target_value: int | None = Field(default=None)
    reward_growth_points: int | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    reward_cosmetic_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)


class BizAchievementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    icon_url: str | None = Field(default=None)
    achievement_type: str | None = Field(default=None)
    target_value: int | None = Field(default=None)
    reward_growth_points: int | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    reward_cosmetic_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)


class BizAchievementPageResponse(BaseModel):
    list: builtins.list[BizAchievementResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizCosmeticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    cosmetic_type: CosmeticType
    image_url: str | None
    animation_url: str | None
    rarity: str | None
    status: str
    description: str | None
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BizCosmeticListQuery(BaseModel):
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


class BizCosmeticCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=128)
    name: str = Field(max_length=128)
    cosmetic_type: CosmeticType = Field(max_length=16)
    image_url: str | None = Field(default=None)
    animation_url: str | None = Field(default=None)
    rarity: str | None = Field(default=None)
    status: str | None = Field(default=None)
    description: str | None = Field(default=None)


class BizCosmeticUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    cosmetic_type: CosmeticType | None = Field(default=None)
    image_url: str | None = Field(default=None)
    animation_url: str | None = Field(default=None)
    rarity: str | None = Field(default=None)
    status: str | None = Field(default=None)
    description: str | None = Field(default=None)


class BizCosmeticPageResponse(BaseModel):
    list: builtins.list[BizCosmeticResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizGrowthEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    user_id: int
    source_type: str
    source_id: str | None
    event_type: str
    idempotency_key: str
    event_data: dict[str, Any] | None
    processed: bool
    created_at: datetime
    processed_at: datetime | None
    id: int


class BizGrowthEventListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizGrowthEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(max_length=128)
    user_id: int = Field()
    source_type: str = Field(max_length=64)
    source_id: str | None = Field(default=None)
    event_type: str = Field(max_length=128)
    idempotency_key: str = Field(max_length=255)
    event_data: dict[str, Any] | None = Field(default=None)
    processed: bool | None = Field(default=None)
    processed_at: datetime | None = Field(default=None)


class BizGrowthEventUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str | None = Field(default=None)
    user_id: int | None = Field(default=None)
    source_type: str | None = Field(default=None)
    source_id: str | None = Field(default=None)
    event_type: str | None = Field(default=None)
    idempotency_key: str | None = Field(default=None)
    event_data: dict[str, Any] | None = Field(default=None)
    processed: bool | None = Field(default=None)
    processed_at: datetime | None = Field(default=None)


class BizGrowthEventPageResponse(BaseModel):
    list: builtins.list[BizGrowthEventResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizGrowthRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    source_type: str
    event_type: str
    reward_points: int
    daily_limit: int | None
    weekly_limit: int | None
    monthly_limit: int | None
    cooldown_seconds: int | None
    requires_success: bool
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    description: str | None
    id: int
    created_at: datetime
    updated_at: datetime


class BizGrowthRuleListQuery(BaseModel):
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


class BizGrowthRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    source_type: str = Field(max_length=64)
    event_type: str = Field(max_length=128)
    reward_points: int = Field()
    daily_limit: int | None = Field(default=None)
    weekly_limit: int | None = Field(default=None)
    monthly_limit: int | None = Field(default=None)
    cooldown_seconds: int | None = Field(default=None)
    requires_success: bool | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)
    description: str | None = Field(default=None)


class BizGrowthRuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    source_type: str | None = Field(default=None)
    event_type: str | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    daily_limit: int | None = Field(default=None)
    weekly_limit: int | None = Field(default=None)
    monthly_limit: int | None = Field(default=None)
    cooldown_seconds: int | None = Field(default=None)
    requires_success: bool | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)
    description: str | None = Field(default=None)


class BizGrowthRulePageResponse(BaseModel):
    list: builtins.list[BizGrowthRuleResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizPointRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    source_type: str
    event_type: str
    reward_points: int
    daily_limit: int | None
    weekly_limit: int | None
    monthly_limit: int | None
    cooldown_seconds: int | None
    requires_success: bool
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    description: str | None
    id: int
    created_at: datetime
    updated_at: datetime


class BizPointRuleListQuery(BaseModel):
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


class BizPointRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    source_type: str = Field(max_length=64)
    event_type: str = Field(max_length=128)
    reward_points: int = Field()
    daily_limit: int | None = Field(default=None)
    weekly_limit: int | None = Field(default=None)
    monthly_limit: int | None = Field(default=None)
    cooldown_seconds: int | None = Field(default=None)
    requires_success: bool | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)
    description: str | None = Field(default=None)


class BizPointRuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    source_type: str | None = Field(default=None)
    event_type: str | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    daily_limit: int | None = Field(default=None)
    weekly_limit: int | None = Field(default=None)
    monthly_limit: int | None = Field(default=None)
    cooldown_seconds: int | None = Field(default=None)
    requires_success: bool | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)
    description: str | None = Field(default=None)


class BizPointRulePageResponse(BaseModel):
    list: builtins.list[BizPointRuleResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    task_type: str
    target_value: int | None
    reward_growth_points: int
    reward_points: int
    repeat_type: str
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    id: int
    created_at: datetime
    updated_at: datetime


class BizTaskListQuery(BaseModel):
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


class BizTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    task_type: str = Field(max_length=64)
    target_value: int | None = Field(default=None)
    reward_growth_points: int | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    repeat_type: str | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)


class BizTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    task_type: str | None = Field(default=None)
    target_value: int | None = Field(default=None)
    reward_growth_points: int | None = Field(default=None)
    reward_points: int | None = Field(default=None)
    repeat_type: str | None = Field(default=None)
    status: str | None = Field(default=None)
    effective_from: datetime | None = Field(default=None)
    effective_to: datetime | None = Field(default=None)


class BizTaskPageResponse(BaseModel):
    list: builtins.list[BizTaskResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserAchievementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    achievement_id: SnowflakeId
    progress: int
    completed_at: datetime | None
    created_at: datetime
    id: int


class BizUserAchievementListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    achievement_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserAchievementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    achievement_id: SnowflakeId = Field()
    progress: int | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class BizUserAchievementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    achievement_id: SnowflakeId | None = Field(default=None)
    progress: int | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class BizUserAchievementPageResponse(BaseModel):
    list: builtins.list[BizUserAchievementResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserCosmeticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    cosmetic_id: SnowflakeId
    source_type: str
    source_id: str | None
    acquired_at: datetime
    id: int


class BizUserCosmeticListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    cosmetic_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserCosmeticCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    cosmetic_id: SnowflakeId = Field()
    source_type: str = Field(max_length=64)
    source_id: str | None = Field(default=None)
    acquired_at: datetime | None = Field(default=None)


class BizUserCosmeticUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    cosmetic_id: SnowflakeId | None = Field(default=None)
    source_type: str | None = Field(default=None)
    source_id: str | None = Field(default=None)
    acquired_at: datetime | None = Field(default=None)


class BizUserCosmeticPageResponse(BaseModel):
    list: builtins.list[BizUserCosmeticResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserEquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    avatar_cosmetic_id: SnowflakeId
    avatar_frame_cosmetic_id: SnowflakeId
    crown_cosmetic_id: SnowflakeId
    badge_cosmetic_id: SnowflakeId
    title_cosmetic_id: SnowflakeId
    name_effect_cosmetic_id: SnowflakeId
    updated_at: datetime
    id: int


class BizUserEquipmentListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    avatar_cosmetic_id: SnowflakeId | None = Field(default=None)
    avatar_frame_cosmetic_id: SnowflakeId | None = Field(default=None)
    crown_cosmetic_id: SnowflakeId | None = Field(default=None)
    badge_cosmetic_id: SnowflakeId | None = Field(default=None)
    title_cosmetic_id: SnowflakeId | None = Field(default=None)
    name_effect_cosmetic_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserEquipmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    avatar_cosmetic_id: SnowflakeId | None = Field(default=None)
    avatar_frame_cosmetic_id: SnowflakeId | None = Field(default=None)
    crown_cosmetic_id: SnowflakeId | None = Field(default=None)
    badge_cosmetic_id: SnowflakeId | None = Field(default=None)
    title_cosmetic_id: SnowflakeId | None = Field(default=None)
    name_effect_cosmetic_id: SnowflakeId | None = Field(default=None)


class BizUserEquipmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    avatar_cosmetic_id: SnowflakeId | None = Field(default=None)
    avatar_frame_cosmetic_id: SnowflakeId | None = Field(default=None)
    crown_cosmetic_id: SnowflakeId | None = Field(default=None)
    badge_cosmetic_id: SnowflakeId | None = Field(default=None)
    title_cosmetic_id: SnowflakeId | None = Field(default=None)
    name_effect_cosmetic_id: SnowflakeId | None = Field(default=None)


class BizUserEquipmentPageResponse(BaseModel):
    list: builtins.list[BizUserEquipmentResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserGrowthAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    total_growth_points: int
    current_level_id: SnowflakeId
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserGrowthAccountListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    current_level_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserGrowthAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    total_growth_points: int | None = Field(default=None)
    current_level_id: SnowflakeId | None = Field(default=None)


class BizUserGrowthAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    total_growth_points: int | None = Field(default=None)
    current_level_id: SnowflakeId | None = Field(default=None)


class BizUserGrowthAccountPageResponse(BaseModel):
    list: builtins.list[BizUserGrowthAccountResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserGrowthTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    change_points: int
    balance_after: int
    rule_id: SnowflakeId
    source_type: str
    source_id: str | None
    event_id: str | None
    transaction_type: str
    description: str | None
    operator_type: str
    operator_id: int | None
    created_at: datetime
    id: int


class BizUserGrowthTransactionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    rule_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserGrowthTransactionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    change_points: int = Field()
    balance_after: int = Field()
    rule_id: SnowflakeId | None = Field(default=None)
    source_type: str = Field(max_length=64)
    source_id: str | None = Field(default=None)
    event_id: str | None = Field(default=None)
    transaction_type: str = Field(max_length=32)
    description: str | None = Field(default=None)
    operator_type: str = Field(max_length=32)


class BizUserGrowthTransactionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    change_points: int | None = Field(default=None)
    balance_after: int | None = Field(default=None)
    rule_id: SnowflakeId | None = Field(default=None)
    source_type: str | None = Field(default=None)
    source_id: str | None = Field(default=None)
    event_id: str | None = Field(default=None)
    transaction_type: str | None = Field(default=None)
    description: str | None = Field(default=None)
    operator_type: str | None = Field(default=None)


class BizUserGrowthTransactionPageResponse(BaseModel):
    list: builtins.list[BizUserGrowthTransactionResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserLevelBenefitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    level_id: SnowflakeId
    benefit_type: str
    benefit_code: str
    benefit_value: dict[str, Any] | None
    status: str
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserLevelBenefitListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    level_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserLevelBenefitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level_id: SnowflakeId = Field()
    benefit_type: str = Field(max_length=64)
    benefit_code: str = Field(max_length=128)
    benefit_value: dict[str, Any] | None = Field(default=None)
    status: str | None = Field(default=None)


class BizUserLevelBenefitUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level_id: SnowflakeId | None = Field(default=None)
    benefit_type: str | None = Field(default=None)
    benefit_code: str | None = Field(default=None)
    benefit_value: dict[str, Any] | None = Field(default=None)
    status: str | None = Field(default=None)


class BizUserLevelBenefitPageResponse(BaseModel):
    list: builtins.list[BizUserLevelBenefitResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserLevelHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    from_level_id: SnowflakeId
    to_level_id: SnowflakeId
    growth_points: int
    change_type: str
    reason: str | None
    created_at: datetime
    id: int


class BizUserLevelHistoryListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    from_level_id: SnowflakeId | None = Field(default=None)
    to_level_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserLevelHistoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    from_level_id: SnowflakeId | None = Field(default=None)
    to_level_id: SnowflakeId = Field()
    growth_points: int = Field()
    change_type: str = Field(max_length=32)
    reason: str | None = Field(default=None)


class BizUserLevelHistoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    from_level_id: SnowflakeId | None = Field(default=None)
    to_level_id: SnowflakeId | None = Field(default=None)
    growth_points: int | None = Field(default=None)
    change_type: str | None = Field(default=None)
    reason: str | None = Field(default=None)


class BizUserLevelHistoryPageResponse(BaseModel):
    list: builtins.list[BizUserLevelHistoryResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserPointAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    total_earned_points: int
    total_spent_points: int
    balance_points: int
    id: int
    created_at: datetime
    updated_at: datetime


class BizUserPointAccountListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserPointAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    total_earned_points: int | None = Field(default=None)
    total_spent_points: int | None = Field(default=None)
    balance_points: int | None = Field(default=None)


class BizUserPointAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    total_earned_points: int | None = Field(default=None)
    total_spent_points: int | None = Field(default=None)
    balance_points: int | None = Field(default=None)


class BizUserPointAccountPageResponse(BaseModel):
    list: builtins.list[BizUserPointAccountResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserPointTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    change_points: int
    balance_after: int
    rule_id: SnowflakeId
    source_type: str
    source_id: str | None
    event_id: str | None
    transaction_type: str
    description: str | None
    operator_type: str
    operator_id: int | None
    created_at: datetime
    id: int


class BizUserPointTransactionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    rule_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserPointTransactionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    change_points: int = Field()
    balance_after: int = Field()
    rule_id: SnowflakeId | None = Field(default=None)
    source_type: str = Field(max_length=64)
    source_id: str | None = Field(default=None)
    event_id: str | None = Field(default=None)
    transaction_type: str = Field(max_length=32)
    description: str | None = Field(default=None)
    operator_type: str = Field(max_length=32)


class BizUserPointTransactionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    change_points: int | None = Field(default=None)
    balance_after: int | None = Field(default=None)
    rule_id: SnowflakeId | None = Field(default=None)
    source_type: str | None = Field(default=None)
    source_id: str | None = Field(default=None)
    event_id: str | None = Field(default=None)
    transaction_type: str | None = Field(default=None)
    description: str | None = Field(default=None)
    operator_type: str | None = Field(default=None)


class BizUserPointTransactionPageResponse(BaseModel):
    list: builtins.list[BizUserPointTransactionResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BizUserTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    task_id: SnowflakeId
    progress: int
    status: str
    completed_at: datetime | None
    claimed_at: datetime | None
    created_at: datetime
    id: int


class BizUserTaskListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    task_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BizUserTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    task_id: SnowflakeId = Field()
    progress: int | None = Field(default=None)
    status: str | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    claimed_at: datetime | None = Field(default=None)


class BizUserTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    task_id: SnowflakeId | None = Field(default=None)
    progress: int | None = Field(default=None)
    status: str | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    claimed_at: datetime | None = Field(default=None)


class BizUserTaskPageResponse(BaseModel):
    list: builtins.list[BizUserTaskResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


__all__ = [
    "BizAchievementCreateRequest",
    "BizAchievementListQuery",
    "BizAchievementPageResponse",
    "BizAchievementResponse",
    "BizAchievementUpdateRequest",
    "BizCosmeticCreateRequest",
    "BizCosmeticListQuery",
    "BizCosmeticPageResponse",
    "BizCosmeticResponse",
    "BizCosmeticUpdateRequest",
    "BizGrowthEventCreateRequest",
    "BizGrowthEventListQuery",
    "BizGrowthEventPageResponse",
    "BizGrowthEventResponse",
    "BizGrowthEventUpdateRequest",
    "BizGrowthRuleCreateRequest",
    "BizGrowthRuleListQuery",
    "BizGrowthRulePageResponse",
    "BizGrowthRuleResponse",
    "BizGrowthRuleUpdateRequest",
    "BizPointRuleCreateRequest",
    "BizPointRuleListQuery",
    "BizPointRulePageResponse",
    "BizPointRuleResponse",
    "BizPointRuleUpdateRequest",
    "BizTaskCreateRequest",
    "BizTaskListQuery",
    "BizTaskPageResponse",
    "BizTaskResponse",
    "BizTaskUpdateRequest",
    "BizUserAchievementCreateRequest",
    "BizUserAchievementListQuery",
    "BizUserAchievementPageResponse",
    "BizUserAchievementResponse",
    "BizUserAchievementUpdateRequest",
    "BizUserCosmeticCreateRequest",
    "BizUserCosmeticListQuery",
    "BizUserCosmeticPageResponse",
    "BizUserCosmeticResponse",
    "BizUserCosmeticUpdateRequest",
    "BizUserEquipmentCreateRequest",
    "BizUserEquipmentListQuery",
    "BizUserEquipmentPageResponse",
    "BizUserEquipmentResponse",
    "BizUserEquipmentUpdateRequest",
    "BizUserGrowthAccountCreateRequest",
    "BizUserGrowthAccountListQuery",
    "BizUserGrowthAccountPageResponse",
    "BizUserGrowthAccountResponse",
    "BizUserGrowthAccountUpdateRequest",
    "BizUserGrowthTransactionCreateRequest",
    "BizUserGrowthTransactionListQuery",
    "BizUserGrowthTransactionPageResponse",
    "BizUserGrowthTransactionResponse",
    "BizUserGrowthTransactionUpdateRequest",
    "BizUserLevelBenefitCreateRequest",
    "BizUserLevelBenefitListQuery",
    "BizUserLevelBenefitPageResponse",
    "BizUserLevelBenefitResponse",
    "BizUserLevelBenefitUpdateRequest",
    "BizUserLevelHistoryCreateRequest",
    "BizUserLevelHistoryListQuery",
    "BizUserLevelHistoryPageResponse",
    "BizUserLevelHistoryResponse",
    "BizUserLevelHistoryUpdateRequest",
    "BizUserPointAccountCreateRequest",
    "BizUserPointAccountListQuery",
    "BizUserPointAccountPageResponse",
    "BizUserPointAccountResponse",
    "BizUserPointAccountUpdateRequest",
    "BizUserPointTransactionCreateRequest",
    "BizUserPointTransactionListQuery",
    "BizUserPointTransactionPageResponse",
    "BizUserPointTransactionResponse",
    "BizUserPointTransactionUpdateRequest",
    "BizUserTaskCreateRequest",
    "BizUserTaskListQuery",
    "BizUserTaskPageResponse",
    "BizUserTaskResponse",
    "BizUserTaskUpdateRequest",
]
