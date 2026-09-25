"""系统参数服务（Phase 7：`05 §5`）。

Frozen / 已裁定依据
------------------
- Spec `05 §5`：System Parameter 与 Dictionary 分离；参数必须有
  **类型 / 默认值 / 状态 / 描述和审计**。
- Spec `08 §1`：管理端点位于 `/api/v1/admin`（本资源的端点未在 `08 §9` 定义，
  属 INTERIM-7-04，见 `app/api/v1/endpoints/params.py`）。
- Spec `10 §3`：授权判断集中在 `AuthorizationService`。
- `docs/DESIGN-DECISIONS.md` §12.1（已裁定）：MFA 的 **system 级默认值**
  在 Phase 5 保持环境变量，**Phase 7 迁入系统参数表**。

取值语义（本模块最关键的部分）
============================

```text
行不存在（含已逻辑删除）  → 返回调用方提供的 fallback
行存在但 status=DISABLED  → ConfigurationError（fail-closed）
行存在且 ACTIVE           → 生效值 = param_value 非 NULL 则用它，否则 default_value
生效值不符合声明类型      → ConfigurationError（fail-closed）
```

逐条理由
-------

1. **行不存在 → fallback（而不是报错）**
   迁移前 MFA 的 system 级默认值来自环境变量 `MFA_REQUIRED_DEFAULT`
   （§12.1 的既定安排）。因此"参数行缺失 ⇒ 用环境变量"这条回退
   **与迁移前的口径完全一致**，不构成任何弱化，也让"迁移脚本尚未执行"
   不会变成"全员无法登录"的可用性事故。
   代价（明确记录）：**删掉参数行会把取值悄悄退回环境变量**。
   缓解：删除是有权限、有审计的操作（`PARAM_DELETE`），
   且回退时会写一次 WARNING（见 `_warn_missing`）。
   刻意**不**把"行缺失"升级为 fail-closed：那会让一次误删变成
   全员登录失败，而且并不比现状更安全（环境变量仍在，只是优先级更低）。

2. **行存在但 DISABLED → fail-closed**
   参数有 `status` 是 `05 §5` 的硬要求，因此必须有确定语义。
   两种"宽容"读法都会制造**静默的安全降级**：
   - "停用 ⇒ 按默认值生效"：等于让"停用"变成无操作（治理字段失效）；
   - "停用 ⇒ 当作未配置"：让"停用"与"缺失"不可区分，
     于是"有人故意关掉了 MFA 要求"与"没人配过这个参数"看起来一样。
   因此只有 fail-closed 一种写法：**读取方立刻报错**，由人决定
   是重新启用还是移除对它的依赖。（INTERIM-7-02）

3. **类型不匹配 → fail-closed**
   `get_bool` 读到一个 `INT` 参数是**代码与配置的契约被破坏**。
   静默转换（例如把非零当 true）会让一次拼写错误变成一个语义不同的
   配置，而且运行时完全看不出来。因此读取器与声明类型必须一致，
   不一致立即报错。（同一类错误在写入侧被提前拦住：见 `_validate_value`。）

4. **报错文案不含参数值**
   `ConfigurationError.message` 会返回给调用方（`app/core/errors.py`）。
   参数值可能承载敏感配置，因此文案只包含**参数键与期望类型**，
   绝不回显值本身。

审计口径：**记录变更事实，不记录值**
==================================
`06 §2` 要求 before_data / after_data，其余资源（角色 / 字典项）都记录了
完整快照。系统参数**故意例外**：

- 参数可能承载密钥类配置（`13 §2` 只说"不得硬编码"，参数表是自然的落点），
  而脱敏规则按**键名**匹配（`app/core/masking.py`），
  `param_value` 这个键名不在其中 → 明文值会被原样写入；
- 审计表是 **append-only 且保留 2 年**（`06 §1` / `10 §8`），
  一旦写入就无法清理 —— 那是一条**不可撤回的泄漏通道**。

因此这里只记录：参数键、类型、状态、`value_is_set`、值长度、
生效来源（当前值 / 默认值）。审计能回答"谁在什么时候改了哪个参数、
是启用了还是停用了、当前值是被清空还是被改写"，但**不能**回答
"改前是什么值" —— 这个代价是刻意的，登记为 INTERIM-7-08。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.config import settings
from app.core.errors import BadRequestError, ConfigurationError, ConflictError, NotFoundError
from app.db.base import utc_now
from app.models.enums import SystemParamStatus, SystemParamType
from app.models.param import (
    DESCRIPTION_LENGTH,
    PARAM_KEY_LENGTH,
    PARAM_NAME_LENGTH,
    PARAM_VALUE_LENGTH,
    SysParam,
)
from app.repositories.param import SystemParamRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService

logger = logging.getLogger(__name__)

#: 审计资源类型。
RESOURCE_TYPE_SYSTEM_PARAM = "SYSTEM_PARAM"

#: MFA 系统级默认值的参数键（`docs/DESIGN-DECISIONS.md` §12.1）。
#:
#: 该键同时出现在迁移的 Seed 中（字面量）；**由测试钉住二者一致**，
#: 避免"改了常量忘了 Seed"导致读取方永远走 fallback。
MFA_REQUIRED_DEFAULT_KEY = "mfa.required_default"

#: 分页上界（与其它列表接口一致）。
MAX_PAGE_SIZE = 100

#: `INT` 类型的字面量格式：可选负号 + ASCII 数字。
#:
#: 刻意不用 `str.isdigit()`：它会接受全角数字（`'１'`）等 Unicode 数字，
#: 而 `int()` 也接受 —— 于是一个"看起来是数字"的怪字符串能悄悄入库。
#: 也用 `fullmatch` 而不是 `search`：`'12abc'` 必须被拒绝。
_INT_LITERAL_RE = re.compile(r"-?\d+")

#: `BOOL` 类型接受的**唯一**两个字面量（忽略大小写）。
#:
#: 刻意不接受 `1` / `0` / `yes` / `on`：`1` 在不同的读取语境里
#: 到底是"数字 1"还是"真"必须由 `param_type` 决定，
#: 宽容解析只会把拼写错误翻译成语义不同的配置。
_BOOL_LITERALS: dict[str, bool] = {"true": True, "false": False}

#: 已经告警过"参数缺失"的键（进程内去重）。
_warned_missing: set[str] = set()


def _warn_missing(key: str) -> None:
    """对"参数缺失"每个键只告警一次。

    为什么需要去重：读取发生在**每个请求**的热路径上（MFA 系统级默认值
    在每次登录时被解析）。若每次都告警，日志会被同一行淹没 ——
    而告警的价值恰恰在于"它一出现就说明有东西不对"。
    """
    if key in _warned_missing:
        return
    _warned_missing.add(key)
    logger.warning(
        "系统参数未配置，读取方回退到内置默认值 param_key=%s（迁移是否已执行？）",
        key,
    )


def reset_missing_warnings() -> None:
    """清空"已告警键"集合（测试用）。"""
    _warned_missing.clear()


@dataclass(frozen=True, slots=True)
class SystemParamPage:
    """系统参数分页结果（分页协议沿用人类已裁定的 `pageNum` / `pageSize`）。"""

    items: list[SysParam]
    total: int
    page_num: int
    page_size: int


def _param_snapshot(param: SysParam) -> dict[str, Any]:
    """系统参数的审计快照（**不含值本身**，理由见模块文档）。"""
    return {
        "id": param.id,
        "param_key": param.param_key,
        "param_name": param.param_name,
        "param_type": param.param_type.value if param.param_type is not None else None,
        "status": param.status.value if param.status is not None else None,
        "value_is_set": param.param_value is not None,
        "value_length": len(param.param_value) if param.param_value is not None else None,
        "default_length": len(param.default_value),
        "effective_source": "VALUE" if param.param_value is not None else "DEFAULT",
        "deleted_at": param.deleted_at.isoformat() if param.deleted_at else None,
    }


def _parse_literal(*, key: str, param_type: SystemParamType, raw: str) -> str | int | bool:
    """把字面量按声明类型解析；失败即 fail-closed。

    Raises:
        ConfigurationError: 字面量不符合声明类型。
            文案**不含字面量本身**（避免回显可能敏感的值）。
    """
    if param_type is SystemParamType.STRING:
        return raw
    if param_type is SystemParamType.INT:
        if _INT_LITERAL_RE.fullmatch(raw) is None:
            raise ConfigurationError(f"系统参数 {key} 声明的类型为 INT，但当前值不是合法整数")
        return int(raw)
    # BOOL
    parsed = _BOOL_LITERALS.get(raw.strip().lower())
    if parsed is None:
        raise ConfigurationError(f"系统参数 {key} 声明的类型为 BOOL，但当前值不是 true / false")
    return parsed


class SystemParameterService:
    """系统参数服务（CRUD + 类型化读取）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._params = SystemParamRepository(session)
        self._authz = AuthorizationService(session)
        self._guard = AuditGuard(audit or NullAuditRecorder(), RESOURCE_TYPE_SYSTEM_PARAM)

    # ------------------------------------------------------------------
    # 内部：目标加载、授权与校验
    # ------------------------------------------------------------------
    async def _load_param(
        self, *, actor: CurrentActor, param_id: int, action: AuditAction
    ) -> SysParam:
        """**参数目标**的唯一入口：授权校验 + 读取。"""
        with self._guard.denial_audited(actor=actor, action=action, resource_id=param_id):
            await self._authz.assert_can_manage_params(actor=actor)

        param = await self._params.get(param_id)
        if param is None:
            raise NotFoundError("系统参数不存在")
        return param

    @staticmethod
    def _assert_text_lengths(
        *,
        param_key: str | None = None,
        param_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """键 / 名称 / 描述的长度与非空校验。"""
        checks = (
            (param_key, PARAM_KEY_LENGTH, "param_key"),
            (param_name, PARAM_NAME_LENGTH, "param_name"),
            (description, DESCRIPTION_LENGTH, "description"),
        )
        for value, limit, field in checks:
            if value is None:
                continue
            if not value.strip():
                raise BadRequestError(f"{field} 不能为空")
            if len(value) > limit:
                raise BadRequestError(f"{field} 长度不得超过 {limit}")

    @staticmethod
    def _assert_key_format(param_key: str) -> None:
        """`param_key` 是**被代码引用的标识符**，因此不允许空白字符。

        Spec 未规定键格式，这里只排除"含空白"这一种情况（INTERIM-7-09）：
        含空格的键在配置面板里几乎必然被误读（前后空格肉眼不可分辨），
        而"键写错"的表现是**读取方静默走 fallback** —— 正是最难发现的故障。
        """
        if any(ch.isspace() for ch in param_key):
            raise BadRequestError("param_key 不允许包含空白字符")

    @staticmethod
    def _validate_value(
        *,
        param_key: str,
        param_type: SystemParamType,
        value: str,
        field: str,
    ) -> None:
        """写入前校验字面量是否符合声明类型。

        为什么在**写入侧**也校验：读取侧虽然会 fail-closed，但那次失败发生在
        运行期的热路径上（例如登录），影响面最大。把可预见的错误挡在
        写入侧，等于让"错误配置根本进不了库"。

        Raises:
            BadRequestError: 长度超限或与声明类型不符。
        """
        if len(value) > PARAM_VALUE_LENGTH:
            raise BadRequestError(f"{field} 长度不得超过 {PARAM_VALUE_LENGTH}")
        try:
            _parse_literal(key=param_key, param_type=param_type, raw=value)
        except ConfigurationError:
            raise BadRequestError(f"{field} 不符合声明的类型 {param_type.value}") from None

    # ------------------------------------------------------------------
    # 查询（管理侧）
    # ------------------------------------------------------------------
    async def get_param(self, *, actor: CurrentActor, param_id: int) -> SysParam:
        """按 ID 读取参数（授权拒绝留痕）。"""
        return await self._load_param(actor=actor, param_id=param_id, action=AuditAction.PARAM_READ)

    async def list_params(
        self,
        *,
        actor: CurrentActor,
        keyword: str | None = None,
        status: SystemParamStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> SystemParamPage:
        """分页列出系统参数。

        读操作也受 `PARAM_MANAGE` 约束：参数的**清单**本身暴露了
        系统有哪些可调开关（含安全策略），不是公开信息。
        """
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise BadRequestError(f"pageSize 必须在 1..{MAX_PAGE_SIZE} 之间")

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.PARAM_READ, resource_id=None
        ):
            await self._authz.assert_can_manage_params(actor=actor)

        items = await self._params.list_params(
            keyword=keyword, status=status, page_num=page_num, page_size=page_size
        )
        total = await self._params.count_params(keyword=keyword, status=status)
        return SystemParamPage(items=items, total=total, page_num=page_num, page_size=page_size)

    # ------------------------------------------------------------------
    # 写入（管理侧）
    # ------------------------------------------------------------------
    async def create_param(
        self,
        *,
        actor: CurrentActor,
        param_key: str,
        param_name: str,
        param_type: SystemParamType,
        default_value: str,
        param_value: str | None = None,
        description: str | None = None,
        status: SystemParamStatus = SystemParamStatus.ACTIVE,
    ) -> SysParam:
        """创建系统参数。

        `default_value` 必须提供（`05 §5` 明确要求"默认值"），
        且必须符合 `param_type`；`param_value` 可省略（= 未显式设置）。
        """
        self._assert_text_lengths(
            param_key=param_key, param_name=param_name, description=description
        )
        self._assert_key_format(param_key)
        self._validate_value(
            param_key=param_key,
            param_type=param_type,
            value=default_value,
            field="default_value",
        )
        if param_value is not None:
            self._validate_value(
                param_key=param_key,
                param_type=param_type,
                value=param_value,
                field="param_value",
            )

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.PARAM_CREATE, resource_id=None
        ):
            await self._authz.assert_can_manage_params(actor=actor)

        if await self._params.get_by_key(param_key) is not None:
            raise ConflictError(f"参数键已存在：{param_key}")

        param = SysParam(
            param_key=param_key,
            param_name=param_name,
            param_type=param_type,
            param_value=param_value,
            default_value=default_value,
            status=status,
            description=description,
        )
        await self._params.add(param)

        self._guard.success(
            actor=actor,
            action=AuditAction.PARAM_CREATE,
            resource_id=param.id,
            after=_param_snapshot(param),
        )
        return param

    async def update_param(
        self,
        *,
        actor: CurrentActor,
        param_id: int,
        param_name: str | None = None,
        default_value: str | None = None,
        param_value: str | None = None,
        clear_value: bool = False,
        description: str | None = None,
        status: SystemParamStatus | None = None,
    ) -> SysParam:
        """修改系统参数。

        `param_key` 与 `param_type` **不可修改**（INTERIM-7-10）：

        - 键是被代码引用的标识符，改键等于换一个参数，
          而引用它的代码不会跟着变 —— 结果是"配置还在、却不再生效"；
        - 类型是参数与读取代码之间的契约。允许改类型会让
          "代码按 BOOL 读、库里声明 INT"这种不一致**推迟到读取时**才暴露，
          而那通常正是登录路径 —— 影响面最大的位置。

        需要换键或换类型时：新建参数 + 迁移引用（与"角色改码"同口径）。

        `clear_value=True` 表示**显式清空当前值**，使其回落到 `default_value`。
        它与"未提供 `param_value`"必须可区分，否则 `param_value` 永远
        无法回到"未设置"状态，`05 §5` 要求的"默认值"就失去了落点。
        """
        param = await self._load_param(
            actor=actor, param_id=param_id, action=AuditAction.PARAM_UPDATE
        )
        self._assert_text_lengths(param_name=param_name, description=description)

        if clear_value and param_value is not None:
            raise BadRequestError("clear_value 与 param_value 不能同时提供（语义冲突）")

        if default_value is not None:
            self._validate_value(
                param_key=param.param_key,
                param_type=param.param_type,
                value=default_value,
                field="default_value",
            )
        if param_value is not None:
            self._validate_value(
                param_key=param.param_key,
                param_type=param.param_type,
                value=param_value,
                field="param_value",
            )

        before = _param_snapshot(param)
        if param_name is not None:
            param.param_name = param_name
        if default_value is not None:
            param.default_value = default_value
        if clear_value:
            param.param_value = None
        elif param_value is not None:
            param.param_value = param_value
        if description is not None:
            param.description = description
        if status is not None:
            param.status = status
        await self._session.flush()

        self._guard.success(
            actor=actor,
            action=AuditAction.PARAM_UPDATE,
            resource_id=param.id,
            before=before,
            after=_param_snapshot(param),
        )
        return param

    async def delete_param(self, *, actor: CurrentActor, param_id: int) -> SysParam:
        """逻辑删除系统参数（绝不物理删除）。

        删除后读取方按"未配置"处理并回退到内置默认值 ——
        这条回退路径的代价与缓解见模块文档第 1 条。
        """
        param = await self._load_param(
            actor=actor, param_id=param_id, action=AuditAction.PARAM_DELETE
        )

        before = _param_snapshot(param)
        param.status = SystemParamStatus.DISABLED
        param.deleted_at = utc_now()
        await self._session.flush()

        self._guard.success(
            actor=actor,
            action=AuditAction.PARAM_DELETE,
            resource_id=param.id,
            before=before,
            after=_param_snapshot(param),
        )
        return param

    # ------------------------------------------------------------------
    # 类型化读取（基础设施侧：不写审计、不做授权）
    # ------------------------------------------------------------------
    async def _resolve(self, key: str) -> tuple[SystemParamType, str] | None:
        """解析参数的声明类型与生效字面量。

        Returns:
            `None` 表示该键**未配置**（不存在 / 已逻辑删除），
            由调用方决定回退值；否则返回 (类型, 字面量)。

        Raises:
            ConfigurationError: 参数已停用，或生效字面量不符合声明类型。
        """
        param = await self._params.get_by_key(key)
        if param is None:
            _warn_missing(key)
            return None
        if param.status is not SystemParamStatus.ACTIVE:
            raise ConfigurationError(f"系统参数 {key} 已被停用；请重新启用该参数，或移除对它的依赖")
        raw = param.param_value if param.param_value is not None else param.default_value
        return param.param_type, raw

    async def _read_typed(
        self,
        key: str,
        expected: SystemParamType,
        fallback: str | int | bool | None,
    ) -> str | int | bool | None:
        """按期望类型读取；未配置时返回 `fallback`。"""
        resolved = await self._resolve(key)
        if resolved is None:
            return fallback
        param_type, raw = resolved
        if param_type is not expected:
            raise ConfigurationError(
                f"系统参数 {key} 声明的类型为 {param_type.value}，但读取方按 {expected.value} 读取"
            )
        return _parse_literal(key=key, param_type=param_type, raw=raw)

    async def get_bool(self, key: str, *, fallback: bool | None = None) -> bool | None:
        """读取布尔参数（未配置 → `fallback`）。"""
        value = await self._read_typed(key, SystemParamType.BOOL, fallback)
        return None if value is None else bool(value)

    async def get_int(self, key: str, *, fallback: int | None = None) -> int | None:
        """读取整数参数（未配置 → `fallback`）。"""
        value = await self._read_typed(key, SystemParamType.INT, fallback)
        return None if value is None else int(value)

    async def get_str(self, key: str, *, fallback: str | None = None) -> str | None:
        """读取字符串参数（未配置 → `fallback`）。"""
        value = await self._read_typed(key, SystemParamType.STRING, fallback)
        return None if value is None else str(value)


async def resolve_mfa_required_default(session: AsyncSession) -> bool:
    """返回 system 级 MFA 默认值（`04 §7` 策略链的最低一层）。

    这是 `docs/DESIGN-DECISIONS.md` §12.1 已裁定的迁移落点：
    Phase 5 时该值来自环境变量 `MFA_REQUIRED_DEFAULT`，Phase 7 起由
    **系统参数表**提供；参数未配置时回退到同一个环境变量
    （因此迁移前后行为一致，绝不静默降低要求）。

    Raises:
        ConfigurationError: 参数被停用或取值不符合声明类型（fail-closed）。
    """
    service = SystemParameterService(session)
    value = await service.get_bool(MFA_REQUIRED_DEFAULT_KEY, fallback=settings.mfa_required_default)
    # 参数未配置时 `get_bool` 返回 fallback（环境变量），`None` 只在
    # 调用方显式传 `fallback=None` 时出现；这里必然有值。
    return bool(value)


__all__ = [
    "MAX_PAGE_SIZE",
    "MFA_REQUIRED_DEFAULT_KEY",
    "RESOURCE_TYPE_SYSTEM_PARAM",
    "SystemParamPage",
    "SystemParameterService",
    "reset_missing_warnings",
    "resolve_mfa_required_default",
]
