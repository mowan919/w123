"""API 契约测试（unit）。

对应 Verification `001-organization-user.md`：
    - 业务 ID 为 Snowflake BIGINT
    - JSON ID 为字符串

对应 Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 统一序列化为字符串；
Spec `10 §4`：`password_hash` 绝不返回；
Spec `02 §5` / `10 §8`：状态与口令变更必须走专用端点（请求模型不得暴露这些字段）。

本文件只测 DTO 本身（不连数据库、不经 HTTP），
以证明契约层独立地守住了上述约束。
"""

from __future__ import annotations

import builtins

import pytest
from pydantic import ValidationError

from app.db.base import utc_now
from app.models.department import Department
from app.models.enums import DepartmentStatus, RoleStatus, UserStatus
from app.models.role import Role
from app.models.user import AdminUser
from app.schemas.department import (
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentTreeNodeResponse,
    DepartmentUpdateRequest,
)
from app.schemas.role import RoleSummaryResponse
from app.schemas.types import MAX_BIGINT
from app.schemas.user import (
    UserCreateRequest,
    UserListQuery,
    UserPageResponse,
    UserResponse,
    UserRolesUpdateRequest,
    UserUpdateRequest,
)

pytestmark = pytest.mark.unit

BIG_ID = 1_234_567_890_123_456_789


def _department() -> Department:
    department = Department(
        id=BIG_ID,
        parent_id=42,
        department_code="RD",
        department_name="研发中心",
        status=DepartmentStatus.ACTIVE,
    )
    department.created_at = utc_now()
    department.updated_at = utc_now()
    return department


def _user() -> AdminUser:
    user = AdminUser(
        id=BIG_ID,
        username="alice",
        password_hash="$argon2id$super-secret-hash",
        display_name="Alice",
        phone="13800001234",
        email="alice@example.com",
        department_id=42,
        status=UserStatus.ACTIVE,
        failed_login_count=0,
        must_change_password=False,
    )
    user.created_at = utc_now()
    user.updated_at = utc_now()
    return user


class TestSnowflakeIdSerialization:
    def test_response_id_is_json_string(self) -> None:
        payload = DepartmentResponse.model_validate(_department()).model_dump(mode="json")
        assert payload["id"] == str(BIG_ID)
        assert isinstance(payload["id"], str)
        assert payload["parent_id"] == "42"

    def test_user_response_id_is_json_string(self) -> None:
        payload = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert payload["id"] == str(BIG_ID)
        assert payload["department_id"] == "42"

    def test_python_mode_keeps_int(self) -> None:
        """Python 侧保持 int，避免影响业务计算（仅 JSON 输出转字符串）。"""
        model = DepartmentResponse.model_validate(_department())
        assert model.id == BIG_ID
        assert isinstance(model.id, int)

    def test_page_response_ids_are_strings(self) -> None:
        page = UserPageResponse(
            list=[UserResponse.model_validate(_user())],
            total=1,
            pageNum=1,
            pageSize=20,
        )
        payload = page.model_dump(mode="json")
        assert payload["list"][0]["id"] == str(BIG_ID)
        assert isinstance(payload["total"], int)  # 计数类字段保持数字
        assert isinstance(payload["pageNum"], int)

    def test_accepts_numeric_string_input(self) -> None:
        request = DepartmentCreateRequest(
            department_code="X", department_name="测试", parent_id=str(BIG_ID)
        )
        assert request.parent_id == BIG_ID

    def test_rejects_boolean_id(self) -> None:
        with pytest.raises(ValidationError):
            DepartmentCreateRequest(department_code="X", department_name="测试", parent_id=True)

    def test_rejects_non_numeric_id(self) -> None:
        with pytest.raises(ValidationError):
            DepartmentCreateRequest(department_code="X", department_name="测试", parent_id="abc")

    def test_rejects_out_of_range_id(self) -> None:
        with pytest.raises(ValidationError):
            DepartmentCreateRequest(
                department_code="X", department_name="测试", parent_id=MAX_BIGINT + 1
            )

    def test_tree_node_children_serialize(self) -> None:
        node = DepartmentTreeNodeResponse(
            id=BIG_ID,
            parent_id=None,
            department_code="RD",
            department_name="研发中心",
            status=DepartmentStatus.ACTIVE,
            children=[
                DepartmentTreeNodeResponse(
                    id=7,
                    parent_id=BIG_ID,
                    department_code="RD-FE",
                    department_name="前端组",
                    status=DepartmentStatus.ACTIVE,
                )
            ],
        )
        payload = node.model_dump(mode="json")
        assert payload["id"] == str(BIG_ID)
        assert payload["children"][0]["id"] == "7"
        assert payload["children"][0]["parent_id"] == str(BIG_ID)


class TestPasswordNeverReturned:
    def test_user_response_has_no_password_fields(self) -> None:
        """Spec 10 §4：响应模型不得出现任何口令字段。"""
        fields = set(UserResponse.model_fields)
        assert "password" not in fields
        assert "password_hash" not in fields

    def test_serialized_user_response_omits_hash(self) -> None:
        payload = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert "password_hash" not in payload
        assert "$argon2id$super-secret-hash" not in str(payload)

    def test_page_response_omits_hash(self) -> None:
        page = UserPageResponse(
            list=[UserResponse.model_validate(_user())], total=1, pageNum=1, pageSize=20
        )
        assert "password_hash" not in str(page.model_dump(mode="json"))


class TestMutableFieldsAreRestricted:
    def test_update_request_has_no_status_field(self) -> None:
        """状态必须走 /disable、/enable 专用端点。"""
        assert "status" not in UserUpdateRequest.model_fields
        with pytest.raises(ValidationError):
            UserUpdateRequest(status="DISABLED")  # type: ignore[call-arg]

    def test_update_request_has_no_password_field(self) -> None:
        assert "password" not in UserUpdateRequest.model_fields
        assert "new_password" not in UserUpdateRequest.model_fields

    def test_department_update_request_has_no_status_field(self) -> None:
        assert "status" not in DepartmentUpdateRequest.model_fields
        with pytest.raises(ValidationError):
            DepartmentUpdateRequest(status="DISABLED")  # type: ignore[call-arg]

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserCreateRequest(
                username="a",
                password="Strong-Passw0rd!1",
                display_name="A",
                is_super_admin=True,  # type: ignore[call-arg]
            )


class TestQueryValidation:
    def test_page_size_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            UserListQuery(pageSize=101)

    def test_page_num_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            UserListQuery(pageNum=0)

    def test_defaults(self) -> None:
        query = UserListQuery()
        assert query.pageNum == 1
        assert query.pageSize == 20
        assert query.department_id is None
        assert query.status is None


class TestExcludeUnsetSemantics:
    def test_update_dump_excludes_unset_fields(self) -> None:
        """未提供的字段不得出现在 kwargs 中（保留 Service 的 _UNSET 语义）。"""
        payload = UserUpdateRequest(display_name="新名字").model_dump(exclude_unset=True)
        assert payload == {"display_name": "新名字"}
        assert "parent_id" not in payload  # 部门同理

    def test_update_can_explicitly_clear_department(self) -> None:
        payload = UserUpdateRequest(department_id=None).model_dump(exclude_unset=True)
        assert payload == {"department_id": None}

    def test_department_update_can_explicitly_move_to_root(self) -> None:
        payload = DepartmentUpdateRequest(parent_id=None).model_dump(exclude_unset=True)
        assert payload == {"parent_id": None}


class TestRolesContract:
    def test_role_summary_serializes_id_as_string(self) -> None:
        role = Role(id=99, role_code="AUDITOR", role_name="审计员", status=RoleStatus.ACTIVE)
        payload = RoleSummaryResponse.model_validate(role).model_dump(mode="json")
        assert payload["id"] == "99"
        assert payload["role_code"] == "AUDITOR"

    def test_roles_update_accepts_string_ids(self) -> None:
        request = UserRolesUpdateRequest(role_ids=["99", 100])
        assert request.role_ids == [99, 100]

    def test_roles_update_defaults_to_empty(self) -> None:
        assert UserRolesUpdateRequest().role_ids == []


# ---------------------------------------------------------------------------
# FIX-003：`list` 字段名遮蔽内建 list
# ---------------------------------------------------------------------------
class TestPageListFieldShadowing:
    """`UserPageResponse` 的字段名由人类裁定为 `list`，会遮蔽内建 `list`。

    若注解写成裸 `list[UserResponse]`，Pydantic 解析注解时会在**类命名空间**
    里取到 `FieldInfo` 对象（即字段默认值），从而抛
    `TypeError: 'FieldInfo' object is not subscriptable`。
    修复方式：注解与 `default_factory` 显式走 `builtins.list`，
    **不得**通过改字段名规避。

    本用例集的作用是"防回归"：任何人把注解改回裸 `list` 都会立刻失败。
    """

    def test_field_is_still_named_list(self) -> None:
        """字段名必须保持 API 契约要求的 `list`。"""
        assert "list" in UserPageResponse.model_fields

    def test_annotation_resolves_to_builtin_list(self) -> None:
        """注解必须解析为 `builtins.list`，而不是 `FieldInfo`。"""
        annotation = UserPageResponse.model_fields["list"].annotation
        assert annotation == builtins.list[UserResponse]

    def test_default_factory_produces_builtin_list(self) -> None:
        page = UserPageResponse(total=0, pageNum=1, pageSize=20)
        assert isinstance(page.list, builtins.list)
        assert page.list == []

    def test_accepts_items_and_serializes_without_error(self) -> None:
        page = UserPageResponse(
            list=[_user()],  # type: ignore[list-item]  # Pydantic 负责转换
            total=1,
            pageNum=1,
            pageSize=20,
        )
        assert len(page.list) == 1
        assert isinstance(page.list[0], UserResponse)

        payload = page.model_dump(mode="json")
        assert set(payload) == {"list", "total", "pageNum", "pageSize"}
        assert payload["list"][0]["id"] == str(BIG_ID)

    def test_field_name_does_not_leak_field_info(self) -> None:
        """回归点：曾经这里会抛 `'FieldInfo' object is not subscriptable`。"""
        page = UserPageResponse(list=[], total=0, pageNum=1, pageSize=20)
        assert page.model_dump(mode="json")["list"] == []

    def test_builtin_list_is_not_shadowed_at_module_level(self) -> None:
        """模块层不得存在遮蔽内建 `list` 的名字（否则后续注解会再次踩坑）。"""
        module = __import__("app.schemas.user", fromlist=["__dict__"])
        assert "list" not in vars(module)


# ---------------------------------------------------------------------------
# RISK-003：API 返回真实手机号 / 邮箱，但绝不返回凭据类字段
# ---------------------------------------------------------------------------
class TestContactFieldsAreReturnedVerbatim:
    """Spec `00 §8` / `06 §4` 的脱敏规则只约束**日志与审计**链路。

    面向"已通过数据范围校验的管理员"的响应必须返回真实值，
    否则管理员无法维护用户联系信息。脱敏入口只有一个：
    `app.core.masking`（见 `test_user_service.py` 的审计快照断言）。
    """

    def test_phone_is_returned_unmasked(self) -> None:
        payload = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert payload["phone"] == "13800001234"
        assert "****" not in payload["phone"]

    def test_email_is_returned_unmasked(self) -> None:
        payload = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert payload["email"] == "alice@example.com"
        assert "***" not in payload["email"]

    def test_audit_snapshot_masks_the_same_values(self) -> None:
        """同一份数据：响应返回真实值，审计快照必须是脱敏值。

        两侧行为必须**不同**，恰好证明脱敏只作用于日志/审计链路。
        """
        from app.services.user import _snapshot

        snapshot = _snapshot(_user())
        assert snapshot["phone"] == "138****1234"
        assert snapshot["email"] == "alice***@example.com"

    def test_credentials_are_never_exposed(self) -> None:
        """password / hash / MFA secret / token 一律不得出现在响应字段中。"""
        forbidden = {
            "password",
            "password_hash",
            "hashed_password",
            "must_change_password_hash",
            "mfa_secret",
            "totp_secret",
            "otp_secret",
            "secret",
            "token",
            "access_token",
            "refresh_token",
            "id_token",
            "session_token",
        }
        assert set(UserResponse.model_fields).isdisjoint(forbidden)

        dumped = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert set(dumped).isdisjoint(forbidden)
        assert "argon2id" not in str(dumped)
        assert "$argon2id$" not in str(dumped)

    def test_login_metadata_is_exposed_but_not_credentials(self) -> None:
        """可运维字段（失败次数 / 锁定时间 / 强制改密）应当返回。"""
        payload = UserResponse.model_validate(_user()).model_dump(mode="json")
        assert payload["failed_login_count"] == 0
        assert payload["locked_until"] is None
        assert payload["must_change_password"] is False
