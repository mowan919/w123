"""日志基础设施。

Spec 13 §5：生产环境必须结构化、带 trace_id、带 request_id、脱敏、支持 retention。
Spec 06 §3：Trace 必须贯穿 HTTP → Controller → Service → Repository → Log。
Spec 06 §4：masking 必须在日志链路生效。

本模块提供：
- `configure_logging()`：一次性配置 root logger；
- `JsonFormatter`：结构化日志，自动注入 trace_id / request_id；
- `MaskingFilter`：对日志 extra 字段递归脱敏。

Retention（日志保留 30d/180d/180d/2y/30d）属于 Phase 6 范围，
本阶段只建立"结构化 + trace + 脱敏"的地基。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id, get_trace_id
from app.core.masking import scrub_field

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
    """对日志记录中的自定义字段做递归脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "vctn_scrubbed", False):
            return True

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_KEYS:
                continue
            record.__dict__[key] = scrub_field(key, value)

        record.vctn_scrubbed = True
        return True


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
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

    def format(self, record: logging.LogRecord) -> str:
        record.trace_id = get_trace_id() or "-"
        record.request_id = get_request_id() or "-"
        return super().format(record)


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = True,
    force: bool = False,
) -> None:
    """配置 root logger。

    Args:
        level: 日志级别字符串。
        json_output: True 输出结构化 JSON，False 输出可读文本。
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

    root.setLevel(level.upper())

    # 避免 uvicorn 自带 handler 造成重复输出
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [h for h in uvicorn_logger.handlers if h in root.handlers]
        uvicorn_logger.propagate = True
