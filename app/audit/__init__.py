"""审计模块。

分层
----
```text
events.py     事件模型与记录**端口**（Phase 2 起，服务层唯一依赖的东西）
classify.py   审计动作 → `06 §1` 五类日志的归属（Phase 6）
records.py    非审计类记录值对象：Access / Application（Phase 6）
buffer.py     请求级缓冲 + 独立事务落库（Phase 6）
```

为什么 `classify` 与 `buffer` **都不在**这里导出
--------------------------------------------
`classify` 同时是**子模块名**（`app.audit.classify`）和**其中的函数名**。
包 `__init__` 一旦重导出这个函数，`app.audit.classify` 这个属性就从"模块"
变成"函数" —— 于是下面这种按字符串定位的目标会失效：

```python
monkeypatch.setattr("app.audit.classify.SECURITY_ACTIONS", frozenset())
# AttributeError: 'function' object at app.audit.classify has no attribute ...
```

更麻烦的是它**只在特定的 import 顺序下**才暴露：`sys.modules` 里仍然是模块，
因此 `importlib.import_module("app.audit.classify")` 一切正常，
而 `getattr` 路径（pytest / mock / 任何按点号定位的工具）拿到的是函数。
（这条不是推测：本 Phase 的完整测试运行**真的**因此失败了两次。）

代价是多敲一次 `from app.audit.classify import classify`，换回"点号路径只有一个含义"。

`buffer` 不导出是另一个原因：它在顶层导入 `events` / `records`，
而 `app.repositories.logs` 又在顶层导入 `buffer` 的值对象。挂到包上会让
"导入 `app.audit`"变成一次牵动数据库层的动作，使本应零依赖的事件模型不再独立。
"""

from __future__ import annotations

from app.audit.classify import (
    OPERATION_ACTIONS,
    READ_ONLY_ACTIONS,
    SECURITY_ACTIONS,
    LogCategory,
)
from app.audit.events import (
    AuditAction,
    AuditEvent,
    AuditRecorder,
    AuditResult,
    NullAuditRecorder,
)
from app.audit.records import AccessRecord, ApplicationRecord

__all__ = [
    "OPERATION_ACTIONS",
    "READ_ONLY_ACTIONS",
    "SECURITY_ACTIONS",
    "AccessRecord",
    "ApplicationRecord",
    "AuditAction",
    "AuditEvent",
    "AuditRecorder",
    "AuditResult",
    "LogCategory",
    "NullAuditRecorder",
]
