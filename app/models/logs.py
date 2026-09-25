"""五类日志模型（Spec `06 §1` / `06 §2` / `07 §8`）。

Spec 依据
---------
`06 §1` 定义五类日志及其保留期：

| 表 | 类别 | 保留期 |
|---|---|---|
| `access_logs` | 请求访问信息 | 30 天 |
| `security_logs` | 登录、锁定、MFA、密码、Session、安全事件 | 180 天 |
| `operation_logs` | 普通业务操作 | 180 天 |
| `audit_logs` | 高价值业务变更与管理员行为 | 2 年 |
| `application_logs` | 应用运行日志 | 30 天 |

`06 §2` 规定 Audit 必须包含 15 个字段（外加 `audit_log_id`，即本表主键）。
`07 §8` 要求"独立日志模型/存储"，并点名 `access_logs` / `security_logs` /
`operation_logs` / `audit_logs`。

为什么这五张表**都没有 `updated_at`**
-----------------------------------
`10 §8` / `06 §2` 要求 **Audit append-only**。只删掉 ORM 层的 update 入口
只是"约定"；把"没有可更新的列"变成**结构性事实**才是保证。
五类日志都是"某时刻发生过什么"的**事实记录**，事实不存在"更新"语义，
因此统一只保留 `created_at`。

数据库层还有第二道防线：`audit_logs` 等表上有
`BEFORE UPDATE` **触发器直接拒绝**（见迁移 `phase6_dd08`）。
两道防线并列，是因为"忘记别更新"这类错误一旦发生就无法回滚取证。

为什么 `security_logs` / `operation_logs` 与 `audit_logs` 有重叠
-------------------------------------------------------------
三者是**同一批事件的三种切片**，不是三套独立写入点：

```text
一条审计事件 ──┬─→ audit_logs      （全部事件，保留 2 年）
               ├─→ security_logs   （action 属安全类，保留 180 天）
               └─→ operation_logs  （action 属业务类，保留 180 天）
```

保留期不同是**必须拆开**的原因：把安全事件只写进 2 年的审计表，
就无法按 `06 §1` 的 180 天做安全日志清理；反之把业务操作写进安全表，
会让"安全事件检索"被海量常规操作淹没。

`application_logs` 表名
---------------------
`07 §8` 写的是 "application logs"（其余四张写了 `_logs` 后缀）。
此处统一为 `application_logs`，登记为 INTERIM —— 缺后缀会让
ORM 模型名与表名不成对应，且与其余四张表的命名规则不一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, utc_now

#: `trace_id` / `request_id` 的长度上界。
#:
#: 与 `app/middleware/trace.py::MAX_ID_LENGTH` 一致：中间件已拒绝超长传入值，
#: 这里再用同宽列兜底，避免任何旁路写入撑爆列宽。
TRACE_ID_LENGTH = 128

#: `action` / `event` / `resource_type` 列宽。
#:
#: 取值来自 `AuditAction` 等 `StrEnum`，最长者远短于此；
#: 定宽是为了让索引可预期，而不是因为恰好够用。
ACTION_LENGTH = 64

#: User-Agent 列宽。
#:
#: 512 足够容纳任何真实浏览器 UA（Chrome / Firefox 均在 150 字符内）。
#: 它同时是**截断上界**：超长值由 `LogRepository._clamp` 截断后入库。
#: 截断确实损失了取证信息，但不截断的代价更大 —— `varchar` 超长会抛错，
#: 而那发生在日志落库的独立事务里，结果是**整批日志一起丢失**。
#: 于是"发一个 64KB 的 UA"就成了一条让审计静默消失的通道。
USER_AGENT_LENGTH = 512

#: IP 列宽（含 IPv6 与可能的端口后缀）。
IP_LENGTH = 64


class AuditLog(PrimaryKeyMixin, Base):
    """高价值业务变更与管理员行为（Spec `06 §2`，`10 §8` append-only）。

    字段与 `06 §2` **一一对应**，缺一不可：

    ```text
    audit_log_id ← id（PrimaryKeyMixin）
    trace_id / request_id / operator_id / operator_username /
    action / resource_type / resource_id / before_data / after_data /
    result / error_code / ip / user_agent / created_at
    ```

    `before_data` / `after_data` 用 `JSONB` 而不是 `Text`
    ------------------------------------------------
    `06 §4` 要求二者必须脱敏。脱敏在**写入前**由
    `app/audit/buffer.py` 完成；用 `JSONB` 是为了让"按变更前的某个字段值
    检索历史"成为数据库能做的工作 —— 存成 JSON 字符串就只能全表扫。
    代价是**必须先脱敏再入库**（`JSONB` 无法事后补救）。

    `operator_id` 为什么可空
    ----------------------
    有一类事件的"操作者"**天然未知**：登录时用户名不存在、令牌无效、
    挑战令牌未知。为这类事件编造一个操作者会写出"看起来是某用户做的"
    假记录 —— 比不记录更糟（该理由已在 `app/services/auth_audit.py` 固化）。
    """

    __tablename__ = "audit_logs"

    trace_id: Mapped[str | None] = mapped_column(
        String(TRACE_ID_LENGTH), nullable=True, comment="链路追踪 ID（Spec 06 §3）"
    )
    request_id: Mapped[str | None] = mapped_column(
        String(TRACE_ID_LENGTH), nullable=True, comment="请求 ID（Spec 06 §3）"
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作者用户 ID；NULL = 操作者未知"
    )
    operator_username: Mapped[str | None] = mapped_column(
        String(ACTION_LENGTH), nullable=True, comment="操作者登录名（审计用）"
    )
    action: Mapped[str] = mapped_column(
        String(ACTION_LENGTH), nullable=False, comment="动作（AuditAction 取值）"
    )
    resource_type: Mapped[str] = mapped_column(
        String(ACTION_LENGTH), nullable=False, comment="资源类型"
    )
    resource_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="资源 ID；NULL = 非单一资源（如全踢）"
    )
    before_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前数据（**已脱敏**，Spec 06 §4）"
    )
    after_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后数据（**已脱敏**，Spec 06 §4）"
    )
    result: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="结果 SUCCESS / FAILURE"
    )
    error_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="失败时的业务错误码"
    )
    ip: Mapped[str | None] = mapped_column(String(IP_LENGTH), nullable=True, comment="来源 IP")
    user_agent: Mapped[str | None] = mapped_column(
        String(USER_AGENT_LENGTH),
        nullable=True,
        comment="User-Agent（非安全信号；超长时在写入前截断）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="发生时间 (UTC)"
    )

    __table_args__ = (
        # Spec `07 §9` 明列 "audit trace/request indexes"：
        # 排查一次请求做过什么时，两个 ID 是唯一入口。
        Index("ix_audit_logs_trace_id_request_id", "trace_id", "request_id"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_operator_id_created_at", "operator_id", "created_at"),
        Index("ix_audit_logs_resource_type_resource_id", "resource_type", "resource_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )


class SecurityLog(PrimaryKeyMixin, Base):
    """安全事件日志（Spec `06 §1`：登录、锁定、MFA、密码、Session、安全事件）。

    与 `audit_logs` 的关系见模块文档：本表是审计事件中**安全类**那一切片，
    按 180 天清理。`event` 列对应审计的 `action`，便于两表按同一名字对齐。
    """

    __tablename__ = "security_logs"

    trace_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operator_username: Mapped[str | None] = mapped_column(String(ACTION_LENGTH), nullable=True)
    event: Mapped[str] = mapped_column(
        String(ACTION_LENGTH), nullable=False, comment="安全事件名（同审计 action）"
    )
    resource_type: Mapped[str] = mapped_column(String(ACTION_LENGTH), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, comment="SUCCESS / FAILURE")
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(
        String(ACTION_LENGTH), nullable=True, comment="拒绝/失败原因（供检索，如 LOCKED）"
    )
    ip: Mapped[str | None] = mapped_column(String(IP_LENGTH), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        Index("ix_security_logs_event_created_at", "event", "created_at"),
        Index("ix_security_logs_operator_id_created_at", "operator_id", "created_at"),
        Index("ix_security_logs_created_at", "created_at"),
    )


class OperationLog(PrimaryKeyMixin, Base):
    """普通业务操作日志（Spec `06 §1`，180 天）。

    只记录"谁在什么时候对哪个资源做了什么、结果如何"，
    不重复 `audit_logs` 的 `before_data` / `after_data`：
    业务操作的字段级变更由审计表承担，本表的价值是**高频可检索**。
    """

    __tablename__ = "operation_logs"

    trace_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operator_username: Mapped[str | None] = mapped_column(String(ACTION_LENGTH), nullable=True)
    action: Mapped[str] = mapped_column(String(ACTION_LENGTH), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(ACTION_LENGTH), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(IP_LENGTH), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        Index("ix_operation_logs_action_created_at", "action", "created_at"),
        Index("ix_operation_logs_operator_id_created_at", "operator_id", "created_at"),
        Index("ix_operation_logs_created_at", "created_at"),
    )


class AccessLog(PrimaryKeyMixin, Base):
    """请求访问日志（Spec `06 §1`，30 天）。

    写入点在 `app/middleware/trace.py`：那已经是为每个请求绑定
    trace / request id 的地方，再放第二个入口会让两者可能不一致。

    `operator_id` 可空：大量请求是未认证的（登录、健康检查、404）。
    """

    __tablename__ = "access_logs"

    trace_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="已认证时的用户 ID；未认证为 NULL"
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="HTTP 方法")
    path: Mapped[str] = mapped_column(String(512), nullable=False, comment="请求路径（不含 query）")
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, comment="响应状态码")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="处理耗时（毫秒）")
    ip: Mapped[str | None] = mapped_column(String(IP_LENGTH), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        Index("ix_access_logs_path_created_at", "path", "created_at"),
        Index("ix_access_logs_status_code_created_at", "status_code", "created_at"),
        Index("ix_access_logs_created_at", "created_at"),
    )


class ApplicationLog(PrimaryKeyMixin, Base):
    """应用运行日志（Spec `06 §1`，30 天）。

    与其余四类的区别：前四类都由**业务语义**驱动（谁做了什么），
    本表由 **Python logging** 驱动（进程内发生了什么）。
    因此写入点是 `logging.Handler`（`app/core/logging.py::DbLogHandler`），
    而不是服务层调用。

    `message` 用 `Text`：日志正文长度无自然上界，截断会让排障时
    恰好丢掉最需要的那一段。已在投递前经过 `MaskingFilter` 脱敏。
    """

    __tablename__ = "application_logs"

    trace_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(TRACE_ID_LENGTH), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, comment="日志级别")
    logger: Mapped[str] = mapped_column(String(255), nullable=False, comment="logger 名称")
    message: Mapped[str] = mapped_column(Text, nullable=False, comment="日志正文（已脱敏）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        Index("ix_application_logs_level_created_at", "level", "created_at"),
        Index("ix_application_logs_logger_created_at", "logger", "created_at"),
        Index("ix_application_logs_created_at", "created_at"),
    )


#: 五类日志模型的联合类型。
#:
#: 用联合而不是 `type[Base]`：`Base` 上没有任何列，
#: 保留期服务要访问 `created_at` 就只能退化成 `attr-defined` 错误或 `cast`。
#: 联合类型保留了"这五张表都有 `created_at`"这一事实，
#: 使清理逻辑可以**真的**按类型检查，而不是靠约定。
LogModel = AuditLog | SecurityLog | OperationLog | AccessLog | ApplicationLog

#: 五类日志的模型集合（供保留期服务与迁移共用）。
#:
#: 以**表名**为键，与 `06 §1` 的类别名一一对应，避免在多个地方
#: 各写一份"有哪些日志表"的清单。
LOG_MODELS: dict[str, type[LogModel]] = {
    "access": AccessLog,
    "security": SecurityLog,
    "operation": OperationLog,
    "audit": AuditLog,
    "application": ApplicationLog,
}


__all__ = [
    "ACTION_LENGTH",
    "IP_LENGTH",
    "LOG_MODELS",
    "TRACE_ID_LENGTH",
    "USER_AGENT_LENGTH",
    "AccessLog",
    "ApplicationLog",
    "AuditLog",
    "LogModel",
    "OperationLog",
    "SecurityLog",
]
