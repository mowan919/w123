"""系统参数服务测试（Phase 7 / 验收裁判 `007-dictionary.md`）。

裁判条目与本文件的对应关系
--------------------------
| 裁判条目 | 用例 |
|---|---|
| System Parameter：类型 / 默认值 / 状态 / 描述 | `TestParamCrud` |
| System Parameter：审计 | `TestAuditRecordsFactsNotValues` |
| Rule：dictionary 与 system parameter 分离 | `TestSeparation` |
| Rule：CRUD API + 授权 | `TestAuthorization` / `tests/test_param_api.py` |
| Rule：MFA system 级默认值来自参数表 | `tests/test_param_mfa_binding.py` |

本文件只验证**服务层语义**。HTTP 层（路由面 / 状态码 / 信封）在
`tests/test_param_api.py`；把两者分开的理由见 `tests/test_dict_api.py` 的模块文档。

取值语义是 Phase 7 最容易出错的地方
--------------------------------
"行缺失 / 行停用 / 类型不符"三种异常输入必须产生**三种不同**的结果，
而且每一种都要能与"正常"区分：

```text
行不存在      → fallback（迁移前口径，不制造可用性事故）
行存在 DISABLED → ConfigurationError（fail-closed，避免"停用=无操作"）
类型不符      → ConfigurationError（避免把拼写错误翻译成语义不同的配置）
```
"""

from __future__ import annotations

import json
import logging

import pytest

from app.audit import AuditAction
from app.audit.classify import OPERATION_ACTIONS, READ_ONLY_ACTIONS, SECURITY_ACTIONS
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import (
    BadRequestError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.scope import DataScope
from app.models.dict import SysDictItem, SysDictType
from app.models.enums import (
    PermissionResourceType,
    PermissionStatus,
    SystemParamStatus,
    SystemParamType,
)
from app.models.param import SysParam
from app.services.dict import DictService
from app.services.system_param import (
    MAX_PAGE_SIZE,
    SystemParameterService,
    reset_missing_warnings,
)
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

DEPT_ID = 57001
ROLE_PARAM_ADMIN = 57011
ROLE_DICT_ADMIN = 57012
ROLE_NO_PERM = 57013
RES_API_PARAM_MANAGE = 57021
RES_API_DICT_MANAGE = 57022
U_PARAM_ADMIN = 57101
U_DICT_ADMIN = 57102
U_NO_PERM = 57103

#: 一个"看起来敏感"的值，用于钉住"审计不得记录参数值"。
SECRET_LIKE_VALUE = "S3CRET-VALUE-9f21c7"


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """`_warned_missing` 是**进程内全局**集合，必须逐用例隔离。

    否则"只告警一次"这类断言会依赖用例执行顺序：
    当另一个用例先读过同一个键时，本用例的告警会被去重掉，
    于是断言"有告警"失败 —— 或反过来，断言"无告警"假通过。
    """
    reset_missing_warnings()
    yield
    reset_missing_warnings()


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------
async def _seed(session) -> None:
    """三个角色：参数管理员 / 字典管理员 / 无权限。"""
    await make_department(session, department_id=DEPT_ID, department_code="PARAM-DEPT")
    await make_role(session, role_id=ROLE_PARAM_ADMIN, role_code="PARAM_ADMIN")
    await make_role(session, role_id=ROLE_DICT_ADMIN, role_code="DICT_ADMIN_ONLY")
    await make_role(session, role_id=ROLE_NO_PERM, role_code="PARAM_NONE")

    for role_id, resource_id, code in (
        (ROLE_PARAM_ADMIN, RES_API_PARAM_MANAGE, "PARAM_MANAGE"),
        (ROLE_DICT_ADMIN, RES_API_DICT_MANAGE, "DICT_MANAGE"),
    ):
        await make_permission_resource(
            session,
            resource_id=resource_id,
            resource_type=PermissionResourceType.API,
            resource_code=code,
            api_method="GET",
            api_path="/api/v1/admin/params",
            status=PermissionStatus.ACTIVE,
        )
        await link_role_permission(session, role_id=role_id, resource_id=resource_id)

    for user_id, username, role_id in (
        (U_PARAM_ADMIN, "param-admin", ROLE_PARAM_ADMIN),
        (U_DICT_ADMIN, "dict-admin-only", ROLE_DICT_ADMIN),
        (U_NO_PERM, "param-none", ROLE_NO_PERM),
    ):
        await make_user(session, user_id=user_id, username=username, department_id=DEPT_ID)
        await link_user_role(session, user_id=user_id, role_id=role_id)


def _param_admin() -> CurrentActor:
    return CurrentActor(
        user_id=U_PARAM_ADMIN,
        username="param-admin",
        role_codes=frozenset({"PARAM_ADMIN"}),
        data_scope=DataScope.ALL,
        ip="10.2.0.1",
        user_agent="pytest-param/1.0",
    )


def _dict_admin() -> CurrentActor:
    return CurrentActor(
        user_id=U_DICT_ADMIN,
        username="dict-admin-only",
        role_codes=frozenset({"DICT_ADMIN_ONLY"}),
        data_scope=DataScope.ALL,
        ip="10.2.0.2",
        user_agent="pytest-param/1.0",
    )


def _no_perm() -> CurrentActor:
    return CurrentActor(
        user_id=U_NO_PERM,
        username="param-none",
        role_codes=frozenset({"PARAM_NONE"}),
        data_scope=DataScope.SELF,
        ip="10.2.0.3",
        user_agent="pytest-param/1.0",
    )


def _super() -> CurrentActor:
    return CurrentActor(
        user_id=U_NO_PERM,
        username="param-none",
        role_codes=frozenset({SUPER_ADMIN_ROLE_CODE}),
        data_scope=DataScope.ALL,
        ip="10.2.0.4",
        user_agent="pytest-param/1.0",
    )


def _service(session, *, audit: RecordingAuditRecorder | None = None) -> SystemParameterService:
    return SystemParameterService(session, audit=audit)


async def _put_param(
    session,
    *,
    key: str = "feature.flag",
    param_type: SystemParamType = SystemParamType.BOOL,
    default_value: str = "false",
    param_value: str | None = None,
    status: SystemParamStatus = SystemParamStatus.ACTIVE,
) -> SysParam:
    """**直接写库**构造参数行。

    刻意绕开 Service：服务层的写入侧校验会拒掉"非法字面量"这类形态，
    而"库里已经存在一个非法值"恰恰是读取侧必须 fail-closed 的场景
    （例如运维直接改库、或旧版本遗留数据）。
    """
    param = SysParam(
        param_key=key,
        param_name=key,
        param_type=param_type,
        param_value=param_value,
        default_value=default_value,
        status=status,
    )
    session.add(param)
    await session.flush()
    return param


async def _make_param(session, *, actor: CurrentActor | None = None, **kwargs) -> SysParam:
    """走服务层创建参数（保证授权、校验与审计路径被覆盖）。"""
    payload = {
        "param_key": "feature.flag",
        "param_name": "功能开关",
        "param_type": SystemParamType.BOOL,
        "default_value": "false",
    }
    payload.update(kwargs)
    return await _service(session).create_param(actor=actor or _param_admin(), **payload)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class TestParamCrud:
    """Spec `05 §5`：类型 / 默认值 / 状态 / 描述 + CRUD。"""

    async def test_create_persists_all_spec_fields(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        param = await _service(db_session, audit=recorder).create_param(
            actor=_param_admin(),
            param_key="session.idle_timeout",
            param_name="会话空闲超时",
            param_type=SystemParamType.INT,
            default_value="1800",
            description="单位：秒",
        )

        assert param.id > 0
        assert param.param_key == "session.idle_timeout"
        assert param.param_name == "会话空闲超时"
        assert param.param_type is SystemParamType.INT
        assert param.default_value == "1800"
        # 未显式设置当前值 → 生效值回落到默认值（由读取器保证）
        assert param.param_value is None
        assert param.status is SystemParamStatus.ACTIVE
        assert param.description == "单位：秒"
        assert param.deleted_at is None

        event = recorder.find(AuditAction.PARAM_CREATE)
        assert event is not None
        assert event.resource_type == "SYSTEM_PARAM"
        assert event.resource_id == param.id

    async def test_get_and_list_round_trip(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_param(db_session)
        service = _service(db_session)

        assert (await service.get_param(actor=_param_admin(), param_id=created.id)).id == created.id

        page = await service.list_params(
            actor=_param_admin(), keyword="feature", status=SystemParamStatus.ACTIVE
        )
        assert page.total == 1
        assert page.items[0].param_key == "feature.flag"
        assert page.page_num == 1 and page.page_size == 20

    async def test_list_includes_disabled_params(self, db_session) -> None:
        """排查"某个开关为什么不起作用"必须先能看到它已被停用。"""
        await _seed(db_session)
        await _make_param(db_session, param_key="a.on")
        await _make_param(
            db_session,
            param_key="b.off",
            status=SystemParamStatus.DISABLED,
            param_type=SystemParamType.STRING,
            default_value="x",
        )

        service = _service(db_session)
        page = await service.list_params(actor=_param_admin())
        keys = {item.param_key for item in page.items}
        # 用**子集**断言而不是集合相等：库里已有迁移 Seed 的
        # `mfa.required_default`（`05 §5` 的落地内容），
        # 相等断言会把"迁移是否执行过"变成隐藏的前置条件 ——
        # 那样测试就不再只测本用例构造的数据。
        assert {"a.on", "b.off"} <= keys

        only_disabled = await service.list_params(
            actor=_param_admin(), status=SystemParamStatus.DISABLED, keyword="b."
        )
        assert [item.param_key for item in only_disabled.items] == ["b.off"]

    async def test_duplicate_key_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        await _make_param(db_session)
        with pytest.raises(ConflictError):
            await _make_param(db_session)

    async def test_key_can_be_reused_after_delete(self, db_session) -> None:
        """`07 §3`：逻辑删除后必须能用同一个键重建。"""
        await _seed(db_session)
        created = await _make_param(db_session)
        service = _service(db_session)
        await service.delete_param(actor=_param_admin(), param_id=created.id)

        again = await service.create_param(
            actor=_param_admin(),
            param_key="feature.flag",
            param_name="重建",
            param_type=SystemParamType.BOOL,
            default_value="true",
        )
        assert again.id != created.id
        assert again.deleted_at is None

    async def test_key_with_whitespace_is_rejected(self, db_session) -> None:
        """INTERIM-7-09：键是被代码引用的标识符，含空白必然导致"配了却不生效"。"""
        await _seed(db_session)
        service = _service(db_session)
        for bad in ("feature flag", " feature.flag", "feature.flag\t"):
            with pytest.raises(BadRequestError):
                await service.create_param(
                    actor=_param_admin(),
                    param_key=bad,
                    param_name="X",
                    param_type=SystemParamType.BOOL,
                    default_value="false",
                )

    async def test_default_value_must_match_declared_type(self, db_session) -> None:
        """写入侧即拦截：非法字面量根本不进库。

        读取侧的 fail-closed 虽然也在，但它发生在运行期热路径上
        （例如登录），影响面最大 —— 能挡在写入侧就不该留到那时。
        """
        await _seed(db_session)
        service = _service(db_session)
        with pytest.raises(BadRequestError):
            await service.create_param(
                actor=_param_admin(),
                param_key="bad.bool",
                param_name="坏的布尔",
                param_type=SystemParamType.BOOL,
                default_value="yes",  # 只接受 true / false
            )

        with pytest.raises(BadRequestError):
            await service.create_param(
                actor=_param_admin(),
                param_key="bad.int",
                param_name="坏的整数",
                param_type=SystemParamType.INT,
                default_value="12abc",
            )

    async def test_negative_and_zero_are_valid_ints(self, db_session) -> None:
        """`-1` / `0` 是合法整数：不能用"是否为正"误判为非法。"""
        await _seed(db_session)
        for value in ("-1", "0", "007"):
            param = await _make_param(
                db_session,
                param_key=f"int.{value}",
                param_type=SystemParamType.INT,
                default_value=value,
            )
            assert param.default_value == value

    async def test_update_writes_before_and_after_audit(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_param(db_session)

        recorder = RecordingAuditRecorder()
        updated = await _service(db_session, audit=recorder).update_param(
            actor=_param_admin(),
            param_id=created.id,
            param_name="功能开关（改）",
            default_value="true",
            status=SystemParamStatus.DISABLED,
        )

        assert updated.param_name == "功能开关（改）"
        assert updated.default_value == "true"
        assert updated.status is SystemParamStatus.DISABLED

        event = recorder.find(AuditAction.PARAM_UPDATE)
        assert event is not None
        assert event.before_data["param_name"] == "功能开关"
        assert event.after_data["param_name"] == "功能开关（改）"
        assert event.before_data["status"] == "ACTIVE"
        assert event.after_data["status"] == "DISABLED"

    async def test_update_can_set_then_clear_the_current_value(self, db_session) -> None:
        """`clear_value` 让 `param_value` 回到 `null`。

        若没有这条路径，`05 §5` 的"默认值"就没有落点：
        当前值一旦被写过就永远压着默认值。
        """
        await _seed(db_session)
        created = await _make_param(db_session)
        service = _service(db_session)

        set_value = await service.update_param(
            actor=_param_admin(), param_id=created.id, param_value="true"
        )
        assert set_value.param_value == "true"

        cleared = await service.update_param(
            actor=_param_admin(), param_id=created.id, clear_value=True
        )
        assert cleared.param_value is None
        assert cleared.default_value == "false"

    async def test_clear_value_conflicts_with_param_value(self, db_session) -> None:
        """两者同时给出是**语义冲突**，必须报错而不是二选一。"""
        await _seed(db_session)
        created = await _make_param(db_session)
        with pytest.raises(BadRequestError):
            await _service(db_session).update_param(
                actor=_param_admin(),
                param_id=created.id,
                clear_value=True,
                param_value="true",
            )

    async def test_key_and_type_are_not_updatable(self, db_session) -> None:
        """INTERIM-7-10：键与类型不可改 —— 由**端口形状**保证，而非运行期检查。

        因此这里断言的是"接口根本不接受这两个参数"：
        一旦有人给 `update_param` 加上 `param_type` 形参，测试立刻失败。
        """
        import inspect

        from app.schemas.param import SystemParamUpdateRequest

        signature = inspect.signature(SystemParameterService.update_param)
        assert "param_key" not in signature.parameters
        assert "param_type" not in signature.parameters
        assert "param_key" not in SystemParamUpdateRequest.model_fields
        assert "param_type" not in SystemParamUpdateRequest.model_fields

    async def test_delete_is_soft(self, db_session) -> None:
        await _seed(db_session)
        created = await _make_param(db_session)
        recorder = RecordingAuditRecorder()

        deleted = await _service(db_session, audit=recorder).delete_param(
            actor=_param_admin(), param_id=created.id
        )
        assert deleted.status is SystemParamStatus.DISABLED
        assert deleted.deleted_at is not None

        # 行仍在库里（绝不是物理删除）
        stored = await db_session.get(SysParam, created.id)
        assert stored is not None and stored.deleted_at is not None

        event = recorder.find(AuditAction.PARAM_DELETE)
        assert event is not None
        assert event.after_data["deleted_at"] is not None

    async def test_missing_param_is_404(self, db_session) -> None:
        await _seed(db_session)
        with pytest.raises(NotFoundError):
            await _service(db_session).get_param(actor=_param_admin(), param_id=999999)

    async def test_pagination_bounds_are_enforced(self, db_session) -> None:
        await _seed(db_session)
        service = _service(db_session)
        with pytest.raises(BadRequestError):
            await service.list_params(actor=_param_admin(), page_num=0)
        with pytest.raises(BadRequestError):
            await service.list_params(actor=_param_admin(), page_size=MAX_PAGE_SIZE + 1)


# ---------------------------------------------------------------------------
# 类型化读取
# ---------------------------------------------------------------------------
class TestTypedRead:
    """`05 §5` 的"参数必须有类型"只有在**读取侧**才产生实际约束。"""

    async def test_current_value_wins_over_default(self, db_session) -> None:
        await _seed(db_session)
        await _put_param(db_session, default_value="false", param_value="true")
        assert await _service(db_session).get_bool("feature.flag", fallback=False) is True

    async def test_default_value_is_used_when_current_value_is_null(self, db_session) -> None:
        await _seed(db_session)
        await _put_param(db_session, default_value="true", param_value=None)
        assert await _service(db_session).get_bool("feature.flag", fallback=False) is True

    async def test_int_and_str_readers(self, db_session) -> None:
        await _seed(db_session)
        await _put_param(
            db_session, key="n.count", param_type=SystemParamType.INT, default_value="-42"
        )
        await _put_param(
            db_session, key="s.name", param_type=SystemParamType.STRING, default_value="vctn"
        )
        service = _service(db_session)
        assert await service.get_int("n.count", fallback=0) == -42
        assert await service.get_str("s.name", fallback="") == "vctn"

    async def test_missing_row_falls_back(self, db_session) -> None:
        """行不存在 → fallback（与迁移前的环境变量口径一致）。

        刻意**不**升级为 fail-closed：一次误删不该变成"全员登录失败"，
        而且环境变量仍然在，只是优先级更低（模块文档第 1 条）。
        """
        await _seed(db_session)
        assert await _service(db_session).get_bool("nope.missing", fallback=True) is True

    async def test_missing_row_warns_exactly_once(
        self, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """missing 只告警一次：读取发生在**每个请求**的热路径上。

        每次都告警会把日志淹没，而这条告警的价值恰恰是"它一出现就说明有问题"。
        """
        await _seed(db_session)
        service = _service(db_session)
        with caplog.at_level(logging.WARNING, logger="app.services.system_param"):
            await service.get_bool("nope.missing", fallback=True)
            await service.get_bool("nope.missing", fallback=True)
            await service.get_bool("nope.missing", fallback=True)

        records = [r for r in caplog.records if "nope.missing" in r.getMessage()]
        assert len(records) == 1

    async def test_disabled_row_fails_closed(self, db_session) -> None:
        """**关键用例**：停用必须是 fail-closed，不能静默降级。

        两种"宽容"读法都会制造静默的安全降级：
        "停用⇒按默认值生效"让治理字段失效；"停用⇒当作未配置"
        让"有人故意关掉 MFA 要求"与"没人配过"无法区分。
        """
        await _seed(db_session)
        await _put_param(db_session, default_value="true", status=SystemParamStatus.DISABLED)
        with pytest.raises(ConfigurationError):
            await _service(db_session).get_bool("feature.flag", fallback=False)

    async def test_type_mismatch_fails_closed(self, db_session) -> None:
        """代码按 BOOL 读、库里声明 INT → 契约被破坏，必须报错。

        `1` 到底是"数字 1"还是"真"应当由 `param_type` 决定；
        宽容解析只会把一个拼写错误翻译成语义不同的配置。
        """
        await _seed(db_session)
        await _put_param(db_session, param_type=SystemParamType.INT, default_value="1")
        with pytest.raises(ConfigurationError):
            await _service(db_session).get_bool("feature.flag", fallback=False)
        # 按声明类型读则正常
        assert await _service(db_session).get_int("feature.flag", fallback=0) == 1

    async def test_illegal_literal_already_in_the_database_fails_closed(self, db_session) -> None:
        """库里已有非法字面量（运维改库 / 旧数据）→ 读取立即失败。"""
        await _seed(db_session)
        await _put_param(db_session, default_value="maybe")
        with pytest.raises(ConfigurationError):
            await _service(db_session).get_bool("feature.flag", fallback=False)

    async def test_configuration_error_does_not_echo_the_value(self, db_session) -> None:
        """报错文案不得回显参数值（它可能承载敏感配置）。"""
        await _seed(db_session)
        await _put_param(db_session, default_value=SECRET_LIKE_VALUE)
        with pytest.raises(ConfigurationError) as excinfo:
            await _service(db_session).get_bool("feature.flag", fallback=False)

        message = str(excinfo.value)
        assert SECRET_LIKE_VALUE not in message
        assert "feature.flag" in message  # 键名可以出现：它不敏感且是排查所需

    async def test_reader_does_not_require_authorization(self, db_session) -> None:
        """类型化读取是**基础设施侧**能力：不写审计、不看权限。

        读取方是登录流程本身（还没有"操作者"这一概念）。
        若这里要求授权，MFA 策略解析会依赖"谁在登录"而自相矛盾。
        """
        await _seed(db_session)
        await _put_param(db_session, default_value="true")
        service = _service(db_session)
        assert await service.get_bool("feature.flag", fallback=False) is True


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
class TestAuditRecordsFactsNotValues:
    """审计记录**变更事实**，不记录值（INTERIM-7-08）。"""

    async def test_create_and_update_snapshots_contain_no_value(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        created = await service.create_param(
            actor=_param_admin(),
            param_key="smtp.password",
            param_name="邮件口令",
            param_type=SystemParamType.STRING,
            default_value=SECRET_LIKE_VALUE,
            param_value=SECRET_LIKE_VALUE,
        )
        await service.update_param(
            actor=_param_admin(), param_id=created.id, param_value=SECRET_LIKE_VALUE + "-2"
        )

        dumped = json.dumps(
            [{"before": event.before_data, "after": event.after_data} for event in recorder.events],
            default=str,
            ensure_ascii=False,
        )
        # 逐字节扫描：审计表是 append-only 且保留 2 年，写进去就撤不回来。
        assert SECRET_LIKE_VALUE not in dumped

    async def test_snapshot_carries_the_facts_needed_for_troubleshooting(self, db_session) -> None:
        """ "不记值"不等于"记不出问题"：这些字段能回答谁改了什么、生效来源是什么。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        created = await _service(db_session, audit=recorder).create_param(
            actor=_param_admin(),
            param_key="smtp.password",
            param_name="邮件口令",
            param_type=SystemParamType.STRING,
            default_value=SECRET_LIKE_VALUE,
            param_value=SECRET_LIKE_VALUE,
        )

        event = recorder.find(AuditAction.PARAM_CREATE)
        assert event is not None
        for field in (
            "param_key",
            "param_type",
            "status",
            "value_is_set",
            "value_length",
            "default_length",
            "effective_source",
        ):
            assert field in event.after_data, field

        assert event.after_data["value_is_set"] is True
        assert event.after_data["value_length"] == len(SECRET_LIKE_VALUE)
        assert event.after_data["effective_source"] == "VALUE"

        # 清空当前值 → 生效来源从 VALUE 回到 DEFAULT
        recorder.events.clear()
        await _service(db_session, audit=recorder).update_param(
            actor=_param_admin(), param_id=created.id, clear_value=True
        )
        cleared = recorder.find(AuditAction.PARAM_UPDATE)
        assert cleared is not None
        assert cleared.after_data["value_is_set"] is False
        assert cleared.after_data["effective_source"] == "DEFAULT"
        assert cleared.before_data["value_is_set"] is True

    async def test_phase_seven_actions_are_classified(self) -> None:
        """新增审计动作必须落入三类之一，否则 `audit_classify` 的并集断言会崩。

        这里把 Phase 7 的分类**显式钉住**，避免有人无意间把它挪到
        "只读"或"操作"里 —— 参数的写操作直接改变运行时安全策略
        （例如 system 级 MFA 默认值），按安全审计留存。
        """
        for action in (
            AuditAction.PARAM_CREATE,
            AuditAction.PARAM_UPDATE,
            AuditAction.PARAM_DELETE,
        ):
            assert action in SECURITY_ACTIONS, action
        for action in (
            AuditAction.DICT_TYPE_CREATE,
            AuditAction.DICT_TYPE_UPDATE,
            AuditAction.DICT_TYPE_DELETE,
            AuditAction.DICT_ITEM_CREATE,
            AuditAction.DICT_ITEM_UPDATE,
            AuditAction.DICT_ITEM_DELETE,
        ):
            assert action in OPERATION_ACTIONS, action
        for action in (
            AuditAction.DICT_TYPE_READ,
            AuditAction.DICT_ITEM_READ,
            AuditAction.PARAM_READ,
        ):
            assert action in READ_ONLY_ACTIONS, action


# ---------------------------------------------------------------------------
# 授权
# ---------------------------------------------------------------------------
class TestAuthorization:
    """`08 §10`：每个受保护 API 必须经过后端授权判定。"""

    async def test_denied_without_param_manage_and_failure_is_audited(self, db_session) -> None:
        """拒绝必须留痕，且不得因提前 raise 而绕过审计。"""
        await _seed(db_session)
        created = await _make_param(db_session)
        recorder = RecordingAuditRecorder()
        service = _service(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.list_params(actor=_no_perm())
        with pytest.raises(PermissionDeniedError):
            await service.create_param(
                actor=_no_perm(),
                param_key="x.y",
                param_name="X",
                param_type=SystemParamType.STRING,
                default_value="v",
            )
        with pytest.raises(PermissionDeniedError):
            await service.get_param(actor=_no_perm(), param_id=created.id)
        with pytest.raises(PermissionDeniedError):
            await service.update_param(actor=_no_perm(), param_id=created.id, param_name="Y")
        with pytest.raises(PermissionDeniedError):
            await service.delete_param(actor=_no_perm(), param_id=created.id)

        failures = recorder.failures()
        assert len(failures) == 5
        assert {event.action for event in failures} == {
            AuditAction.PARAM_READ,
            AuditAction.PARAM_CREATE,
            AuditAction.PARAM_UPDATE,
            AuditAction.PARAM_DELETE,
        }

    async def test_super_admin_bypasses_the_permission_bit(self, db_session) -> None:
        """`10 §3`：SUPER_ADMIN 的集中式 bypass 只在一处出现。"""
        await _seed(db_session)
        param = await _make_param(db_session, actor=_super())
        assert param.id > 0

    async def test_create_rejection_is_audited_before_the_duplicate_check(self, db_session) -> None:
        """拒绝优先级：**先授权后业务**。

        否则"无权限的人"能通过 409/404 与 200 的差异探测出
        "某个参数键是否已存在"。
        """
        await _seed(db_session)
        await _make_param(db_session)
        with pytest.raises(PermissionDeniedError):
            await _make_param(db_session, actor=_no_perm())


# ---------------------------------------------------------------------------
# 分离（`05 §5`）
# ---------------------------------------------------------------------------
class TestSeparation:
    """`05 §5`：System Parameter 必须与 Dictionary **分离**。"""

    def test_tables_are_distinct(self) -> None:
        assert SysParam.__tablename__ == "sys_params"
        assert SysDictType.__tablename__ == "sys_dict_type"
        assert SysDictItem.__tablename__ == "sys_dict_item"
        assert (
            len({SysParam.__tablename__, SysDictType.__tablename__, SysDictItem.__tablename__}) == 3
        )

    def test_no_cross_imports_between_the_two_modules(self) -> None:
        """分离首先是**代码结构**上的：一条 import 就能让两者重新纠缠。

        用 AST 扫导入而不是文本匹配：注释里提到对方的名字是可以的，
        真正危险的是"某一边开始直接读写对方的表 / 仓储"。
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        pairs = {
            "dict": ("services/dict.py", "repositories/dict.py"),
            "param": ("services/system_param.py", "repositories/param.py"),
        }

        for this_side, files in pairs.items():
            other = "param" if this_side == "dict" else "dict"
            for relative in files:
                source = (root / relative).read_text(encoding="utf-8")
                imported: set[str] = set()
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported.add(node.module)
                offenders = {
                    name for name in imported if f".{other}" in name or name.endswith(other)
                }
                assert not offenders, f"{relative} 引入了对方的模块：{offenders}"

    async def test_dictionary_permission_does_not_grant_param_management(self, db_session) -> None:
        """权限位分离：`DICT_MANAGE` 不隐含 `PARAM_MANAGE`。

        参数能改变运行时安全策略，因此"能改字典"不得隐含"能改参数"。
        """
        await _seed(db_session)
        with pytest.raises(PermissionDeniedError):
            await _service(db_session).list_params(actor=_dict_admin())

    async def test_param_permission_does_not_grant_dictionary_management(self, db_session) -> None:
        """反向亦然：不能靠"能改参数"去改字典。"""
        await _seed(db_session)
        with pytest.raises(PermissionDeniedError):
            await DictService(db_session).list_types(actor=_param_admin())

    async def test_dict_service_has_no_param_surface(self) -> None:
        """字典服务不得长出任何"参数"概念的方法。"""
        public_names = {name for name in dir(DictService) if not name.startswith("_")}
        assert not [name for name in public_names if "param" in name.lower()]

    async def test_public_dict_response_cannot_carry_params(self) -> None:
        """公开字典响应是**封闭字段集**：参数不可能顺带被下发。"""
        from app.schemas.dict import PublicDictResponse
        from app.schemas.param import SystemParamResponse

        assert "params" not in PublicDictResponse.model_fields
        assert "param_value" not in PublicDictResponse.model_fields
        # 管理侧参数响应**有**值字段：分离不等于"参数不可见"，而是"入口不同"
        assert "param_value" in SystemParamResponse.model_fields


__all__ = [
    "TestAuditRecordsFactsNotValues",
    "TestAuthorization",
    "TestParamCrud",
    "TestSeparation",
    "TestTypedRead",
]
