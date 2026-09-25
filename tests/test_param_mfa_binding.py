"""MFA system 级默认值迁移到系统参数表的绑定测试（Phase 7）。

这条迁移是**已裁定**的既定安排
--------------------------------
`docs/DESIGN-DECISIONS.md` §12.1：MFA 的 system 级默认值（Spec `04 §7`
策略链的最低一层）在 Phase 5 来自环境变量 `MFA_REQUIRED_DEFAULT`，
**Phase 7 起由系统参数表提供**；Phase 5 已把该层抽象成构造参数，
因此迁移"无需改动 MFA 代码"。

本文件验证"迁移真的发生了，而且没有降低安全要求"
------------------------------------------------
1. 行存在 → 取值来自**参数表**（而不是环境变量）；
2. 行缺失 → 回退环境变量（与迁移前口径**完全一致**，不制造可用性事故）；
3. 行停用 / 类型不符 → fail-closed；
4. **端到端**：登录行为随参数值变化，且 fail-closed 时
   **不创建任何会话**（口令对但配置坏 → 不得出现"半个登录"）；
5. 代码常量 / 迁移 Seed / Seed 主键三者一致（改了常量忘了 Seed
   会让读取方永远走 fallback，而且运行时完全看不出来）。

为什么 `_warned_missing` 需要逐用例重置
-------------------------------------
它是**进程内全局**集合。若不重置，"只告警一次"的断言会依赖用例执行顺序。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

from app.core.config import settings
from app.core.errors import ConfigurationError
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import SystemParamStatus, SystemParamType
from app.models.param import SysParam
from app.services.mfa import MfaProviderRegistry
from app.services.system_param import (
    MFA_REQUIRED_DEFAULT_KEY,
    SystemParameterService,
    reset_missing_warnings,
    resolve_mfa_required_default,
)
from tests.factories import make_department, make_user

pytestmark = pytest.mark.integration

AUTH_PREFIX = "/api/v1/auth"

DEPT_ID = 59001
USER_ID = 59101
USERNAME = "mfa-binding-user"
PASSWORD = "Mfa-Binding-Passw0rd!07"

#: 迁移 Seed 写入的 `mfa.required_default` 行主键。
#: 与 `_SEED_MFA_REQUIRED_DEFAULT_ID` 必须一致（由下面的迁移一致性用例钉住）。
SEEDED_MFA_PARAM_ID = 700001

MIGRATION_FILE = "20260925_0946_phase7_dict_params.py"


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """`_warned_missing` 是进程内全局集合，必须逐用例隔离。"""
    reset_missing_warnings()
    yield
    reset_missing_warnings()


@pytest.fixture
async def api(app: FastAPI, db_session) -> AsyncIterator[AsyncClient]:
    """HTTP 客户端；并显式保证"出厂零 Provider"这一前提。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://vctn.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """把登录路径用到的 Provider 登记处钉成**空**（DD-01 方案 A 的出厂状态）。

    不依赖"全局登记处恰好为空"这一事实：`AuthService` 的默认 registry
    来自 `app.services.mfa.get_mfa_provider_registry`，只要那个名字被
    其它测试（或将来的人）注册过 Provider，本文件的 fail-closed 断言
    就会变成假阴性。显式钉住前提，测试才在测被测对象。
    """
    monkeypatch.setattr("app.services.mfa.get_mfa_provider_registry", lambda: MfaProviderRegistry())


def _data(response: Response):
    return response.json()["data"]


async def _seed_user(session) -> None:
    await make_department(session, department_id=DEPT_ID, department_code="MFA-BINDING-DEPT")
    await make_user(
        session,
        user_id=USER_ID,
        username=USERNAME,
        department_id=DEPT_ID,
        password=PASSWORD,
        password_changed_at=utc_now(),
    )


async def _seeded_param(session) -> SysParam:
    """取出迁移 Seed 的那一行（不存在即视为迁移未执行，直接失败）。"""
    param = await session.get(SysParam, SEEDED_MFA_PARAM_ID)
    assert param is not None, "迁移 Seed 缺失：sys_params 里没有 mfa.required_default"
    return param


async def _login(api: AsyncClient) -> Response:
    return await api.post(f"{AUTH_PREFIX}/login", json={"username": USERNAME, "password": PASSWORD})


# ---------------------------------------------------------------------------
# 常量 / 迁移一致性
# ---------------------------------------------------------------------------
class TestMigrationConsistency:
    """常量、迁移 Seed 与 Seed 主键必须三处一致。"""

    def _migration_source(self) -> str:
        root = Path(__file__).resolve().parents[1]
        return (root / "alembic" / "versions" / MIGRATION_FILE).read_text(encoding="utf-8")

    def test_migration_file_exists_with_expected_revision_chain(self) -> None:
        """迁移必须接在 Phase 6 之后，且 revision 命名沿用既有惯例。

        （Alembic 模板生成的行使用单引号，因此按单引号断言。
        这条用例的价值在于"有人把 `down_revision` 指到别处"会立刻暴露 ——
        那会让 `alembic upgrade head` 的执行顺序与 Phase 编号脱节。）
        """
        source = self._migration_source()
        assert "revision: str = 'phase7_dict'" in source
        assert "down_revision: str | None = 'phase6_dd08'" in source

    def test_migration_seeds_the_same_key_and_id_as_the_code_constant(self) -> None:
        """`MFA_REQUIRED_DEFAULT_KEY` 与 Seed 字面量必须一致。

        若有人改了常量却没改 Seed，读取方会在**每个请求**上走 fallback
        （并只写一条 WARNING），表现是"参数表里明明配了却不生效" ——
        这类故障在运行时几乎无法定位，所以必须在测试期钉死。
        """
        source = self._migration_source()
        assert f'"{MFA_REQUIRED_DEFAULT_KEY}"' in source
        assert f"_SEED_MFA_REQUIRED_DEFAULT_ID = {SEEDED_MFA_PARAM_ID}" in source

    async def test_seeded_row_shape_is_the_migration_contract(self, db_session) -> None:
        """Seed 必须写入一个 **ACTIVE / BOOL / 当前值未设置 / 默认 false** 的行。

        这也是"Phase 7 的迁移已在当前环境执行过"的证据：
        没有这一行，`resolve_mfa_required_default` 会回退环境变量
        （可用，但等于迁移没生效）。
        """
        param = await _seeded_param(db_session)
        assert param.param_key == MFA_REQUIRED_DEFAULT_KEY
        assert param.param_type is SystemParamType.BOOL
        assert param.status is SystemParamStatus.ACTIVE
        assert param.param_value is None, "Seed 不应预设当前值（否则默认值没有落点）"
        assert param.default_value == "false", "Seed 的默认值必须与迁移前的环境变量语义一致"
        assert param.deleted_at is None


# ---------------------------------------------------------------------------
# 解析来源
# ---------------------------------------------------------------------------
class TestResolution:
    async def test_current_value_wins(self, db_session) -> None:
        param = await _seeded_param(db_session)
        param.param_value = "true"
        await db_session.flush()
        assert await resolve_mfa_required_default(db_session) is True

    async def test_default_value_is_used_when_current_value_is_unset(self, db_session) -> None:
        param = await _seeded_param(db_session)
        param.param_value = None
        param.default_value = "true"
        await db_session.flush()
        assert await resolve_mfa_required_default(db_session) is True

    async def test_explicit_false_is_not_confused_with_missing(self, db_session) -> None:
        """显式 `false` 必须能被表达，且结果就是 `False`（不是 None / 异常）。"""
        param = await _seeded_param(db_session)
        param.param_value = "false"
        await db_session.flush()
        assert await resolve_mfa_required_default(db_session) is False

    async def test_missing_row_falls_back_to_the_environment(self, db_session) -> None:
        """行不存在 → 环境变量（= 迁移前的口径）。

        注意"删掉参数行"会走到这里：回退**不是**弱化（环境变量仍在，
        只是优先级更低），但"谁把安全开关删掉了"是可通过审计追查的。
        """
        await db_session.execute(
            text("update sys_params set deleted_at = now() where id = :id"),
            {"id": SEEDED_MFA_PARAM_ID},
        )
        value = await resolve_mfa_required_default(db_session)
        assert value is settings.mfa_required_default

    async def test_missing_row_warns_once(
        self, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        await db_session.execute(
            text("update sys_params set deleted_at = now() where id = :id"),
            {"id": SEEDED_MFA_PARAM_ID},
        )
        with caplog.at_level(logging.WARNING, logger="app.services.system_param"):
            await resolve_mfa_required_default(db_session)
            await resolve_mfa_required_default(db_session)

        records = [r for r in caplog.records if MFA_REQUIRED_DEFAULT_KEY in r.getMessage()]
        assert len(records) == 1

    async def test_disabled_row_fails_closed(self, db_session) -> None:
        """停用 → fail-closed（而不是"按默认值生效"或"当作未配置"）。"""
        param = await _seeded_param(db_session)
        param.status = SystemParamStatus.DISABLED
        await db_session.flush()
        with pytest.raises(ConfigurationError):
            await resolve_mfa_required_default(db_session)

    async def test_wrong_declared_type_fails_closed(self, db_session) -> None:
        """声明成 INT → 按 BOOL 读取必须报错（契约被破坏）。

        若静默转换，`0`/`1` 就会变成 `False`/`True` ——
        一个"看起来是配置"的东西会拥有没人声明的语义。
        """
        param = await _seeded_param(db_session)
        param.param_type = SystemParamType.INT
        await db_session.flush()
        with pytest.raises(ConfigurationError):
            await resolve_mfa_required_default(db_session)

    async def test_reader_does_not_need_an_actor(self, db_session) -> None:
        """类型化读取是基础设施侧能力：登录流程没有"操作者"这一概念。"""
        service = SystemParameterService(db_session)
        param = await _seeded_param(db_session)
        param.param_value = "true"
        await db_session.flush()
        assert await service.get_bool(MFA_REQUIRED_DEFAULT_KEY, fallback=False) is True


# ---------------------------------------------------------------------------
# 端到端：登录行为随参数值变化
# ---------------------------------------------------------------------------
class TestLoginBinding:
    """参数表是登录路径上**真正被读到**的那一层（而不是摆设）。"""

    async def test_login_succeeds_when_the_parameter_does_not_require_mfa(
        self, api: AsyncClient, db_session, no_provider: None
    ) -> None:
        await _seed_user(db_session)
        param = await _seeded_param(db_session)
        param.param_value = "false"
        await db_session.flush()

        response = await _login(api)
        assert response.status_code == 200, response.text
        data = _data(response)
        assert data["access_token"]
        assert "mfa_token" not in data

    async def test_login_fails_closed_when_the_parameter_requires_mfa_without_a_provider(
        self, api: AsyncClient, db_session, no_provider: None
    ) -> None:
        """**关键用例**：把参数改成 `true` + 无 Provider → 登录必须失败。

        这是"参数表真的接进策略链"最强的一条证据：
        改成 `false` 能登录、改成 `true` 就不能 —— 差异只可能来自参数值。

        失败形式是 500（`ConfigurationError` = 服务端配置错误）而不是 200：
        "要求了二次验证却没有可验证的手段"绝不能静默放行。
        """
        await _seed_user(db_session)
        param = await _seeded_param(db_session)
        param.param_value = "true"
        await db_session.flush()

        before = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        response = await _login(api)
        after = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()

        assert response.status_code == 500
        assert response.json()["code"] == 500000
        assert response.json()["data"] is None
        assert "access_token" not in response.text
        assert "refresh_token" not in response.text
        # fail-closed 必须是**无副作用**的：不得留下"半个登录"
        assert after == before

    async def test_login_fails_closed_when_the_parameter_is_disabled(
        self, api: AsyncClient, db_session, no_provider: None
    ) -> None:
        """停用 → 500，且不创建会话（与"要求但无 Provider"同一条 fail-closed 口径）。"""
        await _seed_user(db_session)
        param = await _seeded_param(db_session)
        param.status = SystemParamStatus.DISABLED
        await db_session.flush()

        before = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()
        response = await _login(api)
        after = (await db_session.execute(text("select count(*) from sessions"))).scalar_one()

        assert response.status_code == 500
        assert response.json()["code"] == 500000
        assert after == before

    async def test_wrong_password_still_fails_before_the_parameter_is_consulted(
        self, api: AsyncClient, db_session, no_provider: None
    ) -> None:
        """口令错误必须是 401 而不是 500：MFA 检查在口令之后（Spec `04 §1`）。

        若顺序颠倒，"参数配置坏了"会把口令错误的用户也变成 500 ——
        那会掩盖真实的认证失败信号。
        """
        await _seed_user(db_session)
        param = await _seeded_param(db_session)
        param.param_value = "true"
        await db_session.flush()

        response = await api.post(
            f"{AUTH_PREFIX}/login", json={"username": USERNAME, "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == 401001


__all__ = ["TestLoginBinding", "TestMigrationConsistency", "TestResolution"]
