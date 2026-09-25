"""字典服务测试（Phase 7 / 验收裁判 `007-dictionary.md`）。

裁判条目与本文件的对应关系
--------------------------
| 裁判条目 | 用例 |
|---|---|
| Dictionary Type：dict_code / dict_name / description / status | `TestDictTypeCrud` |
| Dictionary Type：soft delete | `TestDictTypeCrud::test_delete_is_soft_and_cascades_items` |
| Dictionary Item：全部字段 | `TestDictItemCrud` |
| Dictionary Item：soft delete | `TestDictItemCrud::test_delete_is_soft_and_value_can_be_reused` |
| Rule：same dict type item_value 软删除感知唯一 | `TestDictItemUniqueness` |
| Rule：CRUD API | `TestDictTypeCrud` / `TestDictItemCrud` / `tests/test_dict_api.py` |
| Rule：public dictionary query | `TestPublicQuery` / `tests/test_dict_api.py` |
| Rule：dictionary 与 system parameter 分离 | `tests/test_system_param.py::TestSeparation` |

为什么服务层与 HTTP 层分成两个文件
--------------------------------
本文件验证**业务判定**（唯一性、软删除感知、级联、授权、审计），
`tests/test_dict_api.py` 验证**接线**（路由形状、状态码、信封、ID 序列化）。
混在一起时失败原因会变模糊（"409 是因为唯一性还是因为路由写错？"）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import AuditAction
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models.dict import SysDictItem, SysDictType
from app.models.enums import DictStatus, PermissionResourceType, PermissionStatus
from app.services.dict import DictService
from tests.conftest import RecordingAuditRecorder
from tests.factories import (
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

DEPT_ID = 55001
ROLE_DICT_ADMIN = 55011
ROLE_NO_PERM = 55012
RES_API_DICT_MANAGE = 55021
U_DICT_ADMIN = 55101
U_NO_PERM = 55102

#: 直接写库用例使用的固定 ID（显式指定主键，`07 §2` 允许）。
ITEM_A = 55211
ITEM_B = 55212


async def _grant_api(session, *, role_id: int, resource_id: int, code: str) -> None:
    """给角色授予一个 API 权限资源。

    `api_method` / `api_path` 必须给出：`permission_resources` 有一条
    形状检查约束（`ck_permission_resources_resource_type_fields`），
    API 行缺这两列会被数据库直接拒绝。
    """
    await make_permission_resource(
        session,
        resource_id=resource_id,
        resource_type=PermissionResourceType.API,
        resource_code=code,
        api_method="GET",
        api_path="/api/v1/admin/dicts",
        status=PermissionStatus.ACTIVE,
    )
    await link_role_permission(session, role_id=role_id, resource_id=resource_id)


async def _seed(session) -> None:
    """一个持有 `DICT_MANAGE` 的角色 + 一个没有该权限的角色。"""
    await make_department(session, department_id=DEPT_ID, department_code="DICT-DEPT")
    await make_role(session, role_id=ROLE_DICT_ADMIN, role_code="DICT_ADMIN")
    await make_role(session, role_id=ROLE_NO_PERM, role_code="NO_PERM")
    await _grant_api(
        session, role_id=ROLE_DICT_ADMIN, resource_id=RES_API_DICT_MANAGE, code="DICT_MANAGE"
    )
    await make_user(session, user_id=U_DICT_ADMIN, username="dict-admin", department_id=DEPT_ID)
    await make_user(session, user_id=U_NO_PERM, username="no-perm", department_id=DEPT_ID)
    await link_user_role(session, user_id=U_DICT_ADMIN, role_id=ROLE_DICT_ADMIN)
    await link_user_role(session, user_id=U_NO_PERM, role_id=ROLE_NO_PERM)


def _admin() -> CurrentActor:
    """持有 `DICT_MANAGE` 的操作者。"""
    return CurrentActor(
        user_id=U_DICT_ADMIN,
        username="dict-admin",
        role_codes=frozenset({"DICT_ADMIN"}),
        data_scope=DataScope.ALL,
        ip="10.1.0.1",
        user_agent="pytest-dict/1.0",
    )


def _no_perm() -> CurrentActor:
    """无 `DICT_MANAGE` 的操作者。"""
    return CurrentActor(
        user_id=U_NO_PERM,
        username="no-perm",
        role_codes=frozenset({"NO_PERM"}),
        data_scope=DataScope.SELF,
        ip="10.1.0.2",
        user_agent="pytest-dict/1.0",
    )


def _super() -> CurrentActor:
    """SUPER_ADMIN（集中式 bypass，不需要任何授权行）。"""
    return CurrentActor(
        user_id=U_NO_PERM,
        username="no-perm",
        role_codes=frozenset({SUPER_ADMIN_ROLE_CODE}),
        data_scope=DataScope.ALL,
        ip="10.1.0.3",
        user_agent="pytest-dict/1.0",
    )


def _service(session, *, audit: RecordingAuditRecorder | None = None) -> DictService:
    return DictService(session, audit=audit)


async def _make_type(
    session,
    *,
    actor: CurrentActor | None = None,
    dict_code: str = "user_status",
    dict_name: str = "用户状态",
    **kwargs,
) -> SysDictType:
    """创建字典类型（走服务层，保证审计与校验路径被覆盖）。

    不覆盖 Snowflake 生成的主键：把已 flush 的对象主键改成固定值
    会让 SQLAlchemy 认为"主键被修改"，后续 flush 会把它当成 UPDATE 主键，
    属测试制造的假故障。需要固定 ID 的用例改为直接写库（见
    `TestDictItemUniqueness.test_database_index_is_the_final_guard`）。
    """
    service = _service(session)
    return await service.create_type(
        actor=actor or _admin(), dict_code=dict_code, dict_name=dict_name, **kwargs
    )


class TestDictTypeCrud:
    """Spec `05 §2` / `05 §4`：字典类型的字段与 CRUD。"""

    async def test_create_persists_all_spec_fields(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        dict_type = await service.create_type(
            actor=_admin(),
            dict_code="user_status",
            dict_name="用户状态",
            description="用户账号状态枚举",
            status=DictStatus.ACTIVE,
        )

        assert dict_type.id > 0
        assert dict_type.dict_code == "user_status"
        assert dict_type.dict_name == "用户状态"
        assert dict_type.description == "用户账号状态枚举"
        assert dict_type.status is DictStatus.ACTIVE
        assert dict_type.created_at is not None
        assert dict_type.updated_at is not None
        assert dict_type.deleted_at is None

        event = recorder.find(AuditAction.DICT_TYPE_CREATE)
        assert event is not None
        assert event.resource_type == "DICT_TYPE"
        assert event.resource_id == dict_type.id
        assert event.after_data["dict_code"] == "user_status"

    async def test_get_and_list_round_trip(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)

        service = _service(db_session)
        fetched = await service.get_type(actor=_admin(), dict_type_id=created.id)
        assert fetched.id == created.id

        page = await service.list_types(actor=_admin(), keyword="user", status=DictStatus.ACTIVE)
        assert page.total == 1
        assert page.items[0].dict_code == "user_status"
        assert page.page_num == 1 and page.page_size == 20

    async def test_duplicate_code_is_rejected(self, db_session) -> None:
        """编码唯一（软删除感知）。"""
        await _seed(db_session)
        await _make_type(db_session)

        with pytest.raises(ConflictError):
            await _make_type(db_session)

    async def test_code_can_be_reused_after_delete(self, db_session) -> None:
        """`07 §3`：逻辑删除后必须能用同一编码重建。"""
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        await service.delete_type(actor=_admin(), dict_type_id=created.id)

        again = await service.create_type(actor=_admin(), dict_code="user_status", dict_name="再建")
        assert again.id != created.id
        assert again.deleted_at is None

    async def test_update_writes_before_and_after_audit(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)

        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)
        updated = await service.update_type(
            actor=_admin(),
            dict_type_id=created.id,
            dict_name="用户状态（改）",
            status=DictStatus.DISABLED,
        )

        assert updated.dict_name == "用户状态（改）"
        assert updated.status is DictStatus.DISABLED
        event = recorder.find(AuditAction.DICT_TYPE_UPDATE)
        assert event is not None
        assert event.before_data["dict_name"] == "用户状态"
        assert event.after_data["dict_name"] == "用户状态（改）"
        assert event.before_data["status"] == "ACTIVE"
        assert event.after_data["status"] == "DISABLED"

    async def test_delete_is_soft_and_cascades_items(self, db_session) -> None:
        """删除类型 → 逻辑删除（不是物理删除），并级联清理其字典项。

        级联的理由：编码唯一性是软删除感知的，删掉类型后可以用**同一编码**
        重建；若旧项留在库里，重建后的字典会立刻"长出"一批没人配置过的项。
        """
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
        )

        recorder = RecordingAuditRecorder()
        outcome = await _service(db_session, audit=recorder).delete_type(
            actor=_admin(), dict_type_id=created.id
        )

        assert outcome.deleted_item_ids == [item.id]
        # ORM 对象被标记为删除态（逻辑删除）
        assert outcome.dict_type.deleted_at is not None
        assert outcome.dict_type.status is DictStatus.DISABLED
        # 行仍然在库里（绝不是物理删除）
        stored = await db_session.get(SysDictType, created.id)
        assert stored is not None and stored.deleted_at is not None
        stored_item = await db_session.get(SysDictItem, item.id)
        assert stored_item is not None and stored_item.deleted_at is not None

        event = recorder.find(AuditAction.DICT_TYPE_DELETE)
        assert event is not None
        assert event.after_data["deleted_item_count"] == 1
        assert event.after_data["deleted_item_ids"] == [item.id]

    async def test_pagination_bounds_are_enforced(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        with pytest.raises(BadRequestError):
            await service.list_types(actor=_admin(), page_num=0)
        with pytest.raises(BadRequestError):
            await service.list_types(actor=_admin(), page_size=101)

    async def test_missing_type_is_404(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        with pytest.raises(NotFoundError):
            await service.get_type(actor=_admin(), dict_type_id=999999)


class TestDictItemCrud:
    """Spec `05 §3` / `05 §4`：字典项的字段与 CRUD。"""

    async def test_create_persists_all_spec_fields(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        recorder = RecordingAuditRecorder()

        item = await _service(db_session, audit=recorder).create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
            sort_order=10,
            status=DictStatus.ACTIVE,
            is_default=True,
            description="账号可用",
        )

        assert item.dict_type_id == created.id
        assert item.item_label == "启用"
        assert item.item_value == "ACTIVE"
        assert item.item_code == "active"
        assert item.sort_order == 10
        assert item.status is DictStatus.ACTIVE
        assert item.is_default is True
        assert item.description == "账号可用"
        assert item.deleted_at is None

        event = recorder.find(AuditAction.DICT_ITEM_CREATE)
        assert event is not None
        assert event.resource_type == "DICT_ITEM"
        assert event.after_data["item_value"] == "ACTIVE"
        # 审计里带上 dict_code，使"改了哪个字典的项"无需二次查询
        assert event.after_data["dict_code"] == "user_status"

    async def test_items_are_ordered_by_sort_order_then_id(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        for label, value, order in (("丙", "C", 5), ("甲", "A", 1), ("乙", "B", 1)):
            await service.create_item(
                actor=_admin(),
                dict_type_id=created.id,
                item_label=label,
                item_value=value,
                item_code=value.lower(),
                sort_order=order,
            )

        items = await service.list_items(actor=_admin(), dict_type_id=created.id)
        assert [item.item_value for item in items] == ["A", "B", "C"]

    async def test_list_defaults_to_including_disabled_items(self, db_session) -> None:
        """管理界面必须能看到被停用的项，否则"它为什么不见了"无法排查。"""
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="停用项",
            item_value="X",
            item_code="x",
            status=DictStatus.DISABLED,
        )

        all_items = await service.list_items(actor=_admin(), dict_type_id=created.id)
        assert [item.item_value for item in all_items] == ["X"]

        active_only = await service.list_items(
            actor=_admin(), dict_type_id=created.id, status=DictStatus.ACTIVE
        )
        assert active_only == []

    async def test_update_changes_fields_and_audits_snapshots(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
            sort_order=0,
        )

        recorder = RecordingAuditRecorder()
        updated = await _service(db_session, audit=recorder).update_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_id=item.id,
            item_label="已启用",
            item_value="ENABLED",
            item_code="enabled",
            sort_order=7,
            status=DictStatus.DISABLED,
            description="改过的描述",
        )

        assert (updated.item_label, updated.item_value, updated.item_code) == (
            "已启用",
            "ENABLED",
            "enabled",
        )
        assert updated.sort_order == 7
        assert updated.status is DictStatus.DISABLED
        assert updated.description == "改过的描述"

        event = recorder.find(AuditAction.DICT_ITEM_UPDATE)
        assert event is not None
        assert event.before_data["item_value"] == "ACTIVE"
        assert event.after_data["item_value"] == "ENABLED"

    async def test_item_from_another_type_is_404(self, db_session) -> None:
        """路径里有字典 ID 与项 ID 两个标识 → 必须校验**归属**。

        否则可以用"A 字典的路径"改 B 字典的项，
        使审计里的 dict_type_id 与实际被改对象不一致（审计失真）。
        """
        await _seed(db_session)
        first = await _make_type(db_session, dict_code="d1")
        second = await _make_type(db_session, dict_code="d2")
        service = _service(db_session)
        other_item = await service.create_item(
            actor=_admin(),
            dict_type_id=second.id,
            item_label="另一个",
            item_value="OTHER",
            item_code="other",
        )

        with pytest.raises(NotFoundError):
            await service.update_item(
                actor=_admin(),
                dict_type_id=first.id,
                item_id=other_item.id,
                item_label="越界修改",
            )

    async def test_delete_is_soft_and_value_can_be_reused(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
        )

        recorder = RecordingAuditRecorder()
        deleted = await _service(db_session, audit=recorder).delete_item(
            actor=_admin(), dict_type_id=created.id, item_id=item.id
        )
        assert deleted.deleted_at is not None
        assert deleted.status is DictStatus.DISABLED

        stored = await db_session.get(SysDictItem, item.id)
        assert stored is not None and stored.deleted_at is not None

        # 软删除感知唯一性：同值可以重新创建
        again = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="再建启用",
            item_value="ACTIVE",
            item_code="active2",
        )
        assert again.id != item.id

        event = recorder.find(AuditAction.DICT_ITEM_DELETE)
        assert event is not None
        assert event.before_data["item_value"] == "ACTIVE"

    async def test_deleting_the_default_item_is_allowed(self, db_session) -> None:
        """Spec 未规定该场景；这里取"允许"，并把理由登记为 INTERIM-7-07。

        禁止删除默认项会强迫管理员"先改默认项再删"，多一步且无安全收益。
        """
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="默认项",
            item_value="D",
            item_code="d",
            is_default=True,
        )
        deleted = await service.delete_item(
            actor=_admin(), dict_type_id=created.id, item_id=item.id
        )
        assert deleted.is_default is False
        assert deleted.deleted_at is not None


class TestDictItemUniqueness:
    """`05 §3`：**同一 dict type 下 item_value 软删除感知唯一**。"""

    async def test_same_value_in_same_type_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
        )
        with pytest.raises(ConflictError):
            await service.create_item(
                actor=_admin(),
                dict_type_id=created.id,
                item_label="另一个启用",
                item_value="ACTIVE",
                item_code="active2",
            )

    async def test_same_value_in_another_type_is_allowed(self, db_session) -> None:
        """唯一性是**按字典**的，不是全局的。"""
        await _seed(db_session)
        first_type = await _make_type(db_session, dict_code="d1")
        second_type = await _make_type(db_session, dict_code="d2")
        service = _service(db_session)
        for dict_type_id in (first_type.id, second_type.id):
            await service.create_item(
                actor=_admin(),
                dict_type_id=dict_type_id,
                item_label="启用",
                item_value="ACTIVE",
                item_code="active",
            )

        first = await service.list_items(actor=_admin(), dict_type_id=first_type.id)
        second = await service.list_items(actor=_admin(), dict_type_id=second_type.id)
        assert [item.item_value for item in first] == ["ACTIVE"]
        assert [item.item_value for item in second] == ["ACTIVE"]

    async def test_update_to_an_existing_value_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="A",
            item_value="A",
            item_code="a",
        )
        second = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="B",
            item_value="B",
            item_code="b",
        )

        with pytest.raises(ConflictError):
            await service.update_item(
                actor=_admin(),
                dict_type_id=created.id,
                item_id=second.id,
                item_value="A",
            )

    async def test_update_to_its_own_value_is_allowed(self, db_session) -> None:
        """把 `item_value` 改成它自己（同时改别的字段）不得被唯一性误伤。"""
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="A",
            item_value="A",
            item_code="a",
        )
        updated = await service.update_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_id=item.id,
            item_value="A",
            item_label="A2",
        )
        assert updated.item_label == "A2"

    async def test_database_index_is_the_final_guard(self, db_session) -> None:
        """服务层预校验给出友好错误，数据库 partial unique index 给出最终保证。

        直接绕过服务层写库（模拟并发下两个请求同时通过预校验）
        必须被数据库拒绝 —— 否则唯一性只是"服务层的约定"。
        """
        await _seed(db_session)
        created = await _make_type(db_session)
        db_session.add(
            SysDictItem(
                id=ITEM_A,
                dict_type_id=created.id,
                item_label="A",
                item_value="A",
                item_code="a",
                sort_order=0,
                status=DictStatus.ACTIVE,
                is_default=False,
            )
        )
        await db_session.flush()

        # 用**保存点**包住这次"故意失败"的写入。
        #
        # 为什么必须这样：PostgreSQL 在语句报错后会把**当前事务**标记为
        # aborted，此后任何语句都只能收到 "current transaction is aborted"。
        # 若直接撞在外层事务上，外层事务就废了 ——
        # 夹具回滚时会抛出 `SAWarning: transaction already deassociated
        # from connection`，一条与用例无关的噪声混进整套测试的输出。
        # 保存点把失败限制在它自己的作用域里，回滚到保存点即可继续使用外层事务。
        nested = await db_session.begin_nested()
        db_session.add(
            SysDictItem(
                id=ITEM_B,
                dict_type_id=created.id,
                item_label="A2",
                item_value="A",
                item_code="a2",
                sort_order=0,
                status=DictStatus.ACTIVE,
                is_default=False,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()


class TestOneDefaultPerType:
    """每个字典至多一个默认项（INTERIM-7-03）。"""

    async def test_second_default_replaces_the_first(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        first = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="A",
            item_value="A",
            item_code="a",
            is_default=True,
        )
        second = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="B",
            item_value="B",
            item_code="b",
            is_default=True,
        )

        await db_session.refresh(first)
        defaults = (
            (
                await db_session.execute(
                    select(SysDictItem.item_value).where(
                        SysDictItem.dict_type_id == created.id,
                        SysDictItem.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert list(defaults) == [second.item_value]
        assert first.is_default is False

    async def test_update_to_default_replaces_the_previous_one(self, db_session) -> None:
        """顺序很关键：必须先清掉其他默认项再写入，否则会撞唯一索引。"""
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        first = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="A",
            item_value="A",
            item_code="a",
            is_default=True,
        )
        second = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="B",
            item_value="B",
            item_code="b",
        )

        await service.update_item(
            actor=_admin(), dict_type_id=created.id, item_id=second.id, is_default=True
        )

        await db_session.refresh(first)
        await db_session.refresh(second)
        assert (first.is_default, second.is_default) == (False, True)

    async def test_clearing_the_only_default_leaves_none(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_type(db_session)
        service = _service(db_session)
        item = await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="A",
            item_value="A",
            item_code="a",
            is_default=True,
        )
        await service.update_item(
            actor=_admin(), dict_type_id=created.id, item_id=item.id, is_default=False
        )
        count = (
            (
                await db_session.execute(
                    select(SysDictItem.id).where(
                        SysDictItem.dict_type_id == created.id,
                        SysDictItem.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert count == []


class TestAuthorization:
    """Spec `08 §10` / `10 §3`：后端强制授权 + 拒绝留痕。"""

    async def test_read_without_permission_is_denied_and_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.list_types(actor=_no_perm())

        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action is AuditAction.DICT_TYPE_READ
        assert failures[0].error_code == PermissionDeniedError.code

    async def test_item_write_without_permission_is_audited_under_item_resource(
        self, db_session
    ) -> None:
        """字典项动作的拒绝审计必须是 `DICT_ITEM` 资源类型。

        若写成 `DICT_TYPE`，按资源检索"谁试图改字典项"会漏掉这些记录。
        """
        await _seed(db_session)
        created = await _make_type(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.create_item(
                actor=_no_perm(),
                dict_type_id=created.id,
                item_label="A",
                item_value="A",
                item_code="a",
            )

        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action is AuditAction.DICT_ITEM_CREATE
        assert failures[0].resource_type == "DICT_ITEM"

    async def test_super_admin_bypasses_without_any_grant(self, db_session) -> None:
        """SUPER_ADMIN 的放行是**集中式 bypass**（`10 §3`），不依赖授权行。"""
        await _seed(db_session)
        service = _service(db_session)
        created = await _make_type(db_session, actor=_super())
        page = await service.list_types(actor=_super())
        assert page.total == 1
        assert page.items[0].id == created.id

    async def test_public_query_needs_no_permission(self, db_session) -> None:
        """公开查询不经过 `DICT_MANAGE`（JUDGMENT-7-03）。"""
        await _seed(db_session)
        await _make_type(db_session)
        outcome = await _service(db_session).get_public(dict_code="user_status")
        assert outcome.dict_type.dict_code == "user_status"


class TestPublicQuery:
    """Spec `05 §4`：公开字典查询。"""

    async def _prepare(self, session) -> SysDictType:
        await _seed(session)
        created = await _make_type(session)
        service = _service(session)
        await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="启用",
            item_value="ACTIVE",
            item_code="active",
            sort_order=1,
            is_default=True,
        )
        await service.create_item(
            actor=_admin(),
            dict_type_id=created.id,
            item_label="停用",
            item_value="DISABLED",
            item_code="disabled",
            sort_order=2,
            status=DictStatus.DISABLED,
        )
        return created

    async def test_only_active_items_are_returned(self, db_session) -> None:
        await self._prepare(db_session)
        outcome = await _service(db_session).get_public(dict_code="user_status")

        assert outcome.dict_type.dict_name == "用户状态"
        assert [item.item_value for item in outcome.items] == ["ACTIVE"]
        assert outcome.items[0].is_default is True

    async def test_disabled_type_is_not_found(self, db_session) -> None:
        created = await self._prepare(db_session)
        await _service(db_session).update_type(
            actor=_admin(), dict_type_id=created.id, status=DictStatus.DISABLED
        )
        with pytest.raises(NotFoundError):
            await _service(db_session).get_public(dict_code="user_status")

    async def test_deleted_type_is_not_found(self, db_session) -> None:
        created = await self._prepare(db_session)
        await _service(db_session).delete_type(actor=_admin(), dict_type_id=created.id)
        with pytest.raises(NotFoundError):
            await _service(db_session).get_public(dict_code="user_status")

    async def test_unknown_code_is_not_found(self, db_session) -> None:
        await _seed(db_session)
        with pytest.raises(NotFoundError):
            await _service(db_session).get_public(dict_code="no_such_dict")

    async def test_public_query_records_no_audit(self, db_session) -> None:
        """公开查询不写审计（INTERIM-7-05）。

        它是每个登录用户每次加载页面都会调用的读操作；
        逐次写审计会把审计表变成访问日志，并稀释 FAILURE 信号。
        代价（"谁读过字典"不可追溯）已在决策台账登记。
        """
        await self._prepare(db_session)
        recorder = RecordingAuditRecorder()
        service = DictService(db_session, audit=recorder)
        await service.get_public(dict_code="user_status")
        assert recorder.events == []
