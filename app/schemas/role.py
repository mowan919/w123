"""角色 API 契约（Pydantic DTO）。

范围边界
-------
Phase 2 只交付"用户-角色关联"所需的**只读**角色摘要：
`GET /users/{id}/roles` 需要展示角色基本信息。

角色 CRUD、权限授予、数据范围配置属于 Phase 3（`PHASE-003-PERMISSION`），
本模块**不**定义其请求模型。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RoleStatus
from app.schemas.types import SnowflakeId


class RoleSummaryResponse(BaseModel):
    """角色摘要（用户角色关联接口使用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="角色 ID（JSON 为字符串）")
    role_code: str = Field(description="角色编码；SUPER_ADMIN 等特权角色以此为标识")
    role_name: str
    status: RoleStatus


__all__ = ["RoleSummaryResponse"]
