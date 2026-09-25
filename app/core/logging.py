"""日志基础设施。

Spec 13 §5：生产环境必须结构化、带 trace_id、带 request_id、脱敏、支持 retention。
Spec 06 §3：Trace 必须贯穿 HTTP → Controller → Service → Repository → Log。
Spec 06 §4：masking 必须在日志链路生效。

本模块提供：
- `configure_logging()`：一次性配置 root logger；
- `JsonFormatter`：结构化日志，自动注入 trace_id / request_id；
- `MaskingFilter`：对日志 extra 字段与**消息正文**递归脱敏；
- `DbLogHandler`：把日志投递到 `application_logs`（Phase 6）。

脱敏覆盖到哪一层（Phase 6 补齐）
----------------------------
`MaskingFilter` 最初只处理 `record.__dict__` 里的自定义字段，
而 `msg` / `args` 属**保留键**被跳过 —— 于是 `logger.info("... %s", pwd)`
渲染出来的正文完全没有脱敏。`06 §4` 的规则因此只在一半路径上生效。

Phase 6 起，过滤器会**重写 `record.msg`** 为已脱敏的渲染结果
（并把 `args` 置空），使所有 handler 拿到的是同一份安全文本；
异常堆栈由两个 formatter 的 `formatException` 覆盖（堆栈里同样会出现
连接串、请求体等敏感值）。

Retention（30d/180d/180d/2y/30d）的执行入口是
`app/services/log_retention.py`，不在本模块 —— 日志配置与日志清理
是两件事，混在一起会让"配置错误"与"清理误删"难以区分。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from app.core.context import get_request_id, get_trace_id
from app.core.masking import scrub_field, scrub_text

_RESERVED_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
        "vctn_scrubbed",
    }
)


class MaskingFilter(logging.Filter):
    """对日志记录的自定义字段与消息正文做脱敏。

    重写 `record.msg` 而不是只在 formatter 里处理，是为了让
    **每一个** handler（stdout / 数据库 / 第三方）看到同一份安全文本 ——
    否则"漏脱敏"会取决于谁挂了哪个 handler。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "vctn_scrubbed", False):
            return True

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_KEYS:
                continue
            record.__dict__[key] = scrub_field(key, value)

        _scrub_record_message(record)

        record.vctn_scrubbed = True
        return True


def _scrub_record_message(record: logging.LogRecord) -> None:
    """把渲染后的消息正文替换为已脱敏版本。

    渲染失败时（`args` 与占位符不匹配）**不抛异常**：
    过滤器的契约是"决定这条记录是否通过"，不是"校验日志调用"。
    抛出去会让 `record.getMessage()` 在所有 handler 里重复失败，
    包括那些本来只关心 `levelname` 的 handler —— 一处写错拖垮整条链路。
    这里保持原样，让 formatter 以它一贯的方式暴露问题。
    """
    try:
        rendered = record.getMessage()
    except Exception:
        return

    scrubbed = scrub_text(rendered)
    if scrubbed == rendered and record.args is None:
        return

    record.msg = scrubbed
    record.args = None
    # `logging` 会在首次 `getMessage()` 时缓存 `message`，改动 `msg` 后
    # 必须丢弃缓存，否则后续 handler 仍读到旧文本。
    record.__dict__.pop("message", None)


#: `logging.Formatter.formatException` 的入参类型。
#:
#: 必须原样照抄 `logging` 的声明（含 `(None, None, None)` 分支），
#: 否则覆盖方法违反 Liskov 替换原则 —— mypy `--strict` 会拒绝，
#: 而放宽类型是**错误的方向**：`formatException(None, None, None)` 真的会被调用。
ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。"""

    def formatException(self, ei: ExcInfo) -> str:
        """脱敏异常堆栈。

        堆栈里最常见的泄漏不是异常消息本身，而是**局部变量与连接串**
        （`repr()` 出来的请求体、DSN、令牌）。`06 §4` 的脱敏义务不区分
        "正文"与"堆栈"，因此这里同样过一遍。
        """
        return scrub_text(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            # 正文可能未经 `MaskingFilter`（例如直接调用 formatter 的场景），
            # 因此在这里再脱一次；`scrub_text` 幂等，重复调用不会二次破坏。
            "message": scrub_text(record.getMessage()),
            "trace_id": get_trace_id(),
            "request_id": get_request_id(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS:
                continue
            payload[key] = scrub_field(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    """开发态可读格式，同样携带 trace / request id。"""

    def formatException(self, ei: ExcInfo) -> str:
        """开发态同样脱敏 —— 本地日志也会被复制粘贴到工单里。"""
        return scrub_text(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        record.trace_id = get_trace_id() or "-"
        record.request_id = get_request_id() or "-"
        return super().format(record)


class DbLogHandler(logging.Handler):
    """把日志投递到 `application_logs`（Spec `06 §1` Application Log，30 天）。

    只**入内存缓冲**，不直接写库
    --------------------------
    写入由 `app/audit/buffer.py::flush_logs()` 在响应发出前用**独立事务**
    完成。handler 若自己开事务，就会与业务事务的提交时机耦合：
    业务回滚时日志跟着没了，而"出错时的应用日志"恰恰最不能丢。

    这里**不**再脱敏
    ---------------
    本 handler 自己挂了一份 `MaskingFilter`（见 `_configure_db_handler`），
    因此进入 `emit` 时正文已安全。二次脱敏会把 `138****1234` 再处理一遍，
    虽然结果仍安全，却使"脱敏到底发生在哪一层"变得难以回答 ——
    脱敏是**一次且在最外层**的职责（`MaskingFilter` 用 `vctn_scrubbed`
    标记保证同一条记录只被处理一次，无论有几个 handler）。

    递归防护
    -------
    落库失败时 `flush_logs()` 会记 ERROR。那条日志若又被本 handler 收下，
    下一次 flush 再失败、再记 —— 数据库长时间不可用就会无限增长。
    因此 flush 期间产生的日志直接丢弃（见 `is_flushing`）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        """把记录写入当前缓冲（请求缓冲，或兜底缓冲）。"""
        from app.audit.buffer import is_flushing, record_application
        from app.audit.records import ApplicationRecord

        if is_flushing():
            return

        try:
            message = record.getMessage()
        except Exception:
            self.handleError(record)
            return

        try:
            record_application(
                ApplicationRecord.build(
                    level=record.levelname,
                    logger=record.name,
                    message=message,
                )
            )
        except Exception:
            self.handleError(record)


#: `application_logs` 的入库级别下界。
#:
#: 刻意高于 root 可能的 `DEBUG`：`06 §1` 的 Application Log 是"应用运行日志"
#: （面向运维与取证），不是开发态诊断。若跟随 `DEBUG`，
#: 单机几条调试语句就能在 30 天内写入千万行，把真正的事件淹没 ——
#: 这属于 INTERIM-6-04（Spec 未规定入库级别）。
DB_LOG_LEVEL = logging.INFO


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = True,
    db_output: bool = True,
    force: bool = False,
) -> None:
    """配置 root logger。

    Args:
        level: 日志级别字符串。
        json_output: True 输出结构化 JSON，False 输出可读文本。
        db_output: 是否额外挂载 `DbLogHandler`（写入 `application_logs`）。
        force: 为 True 时先清空已有 handler（便于测试与重复调用）。
    """
    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if json_output:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                PlainFormatter(
                    "%(asctime)s %(levelname)-8s [%(name)s] "
                    "[trace=%(trace_id)s req=%(request_id)s] %(message)s"
                )
            )
        handler.addFilter(MaskingFilter())
        root.addHandler(handler)

    _configure_db_handler(root, enabled=db_output)

    root.setLevel(level.upper())

    # 避免 uvicorn 自带 handler 造成重复输出
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [h for h in uvicorn_logger.handlers if h in root.handlers]
        uvicorn_logger.propagate = True


def _configure_db_handler(root: logging.Logger, *, enabled: bool) -> None:
    """幂等地挂载 / 摘除 `DbLogHandler`。

    `configure_logging` 可能被多次调用（测试、reload、多 worker 启动），
    因此这里以"是否已存在"为准，而不是无条件 add —— 重复挂载会让
    同一条日志在 `application_logs` 里出现多行，且难以察觉。
    """
    existing = [h for h in root.handlers if isinstance(h, DbLogHandler)]

    if not enabled:
        for handler in existing:
            root.removeHandler(handler)
        return

    if existing:
        return

    db_handler = DbLogHandler(level=DB_LOG_LEVEL)
    db_handler.addFilter(MaskingFilter())
    root.addHandler(db_handler)
