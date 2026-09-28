"""统计概览 API 契约（报表页面的数据来源）。

为什么需要独立端点，而不是让前端拼现有清单端点
--------------------------------------------
报表页（前端默认首页）要回答"系统里现在有多少人 / 多少人在线"。
现有清单端点给不出这两个数字中的**第二个**：

- `GET /admin/users` 的 `total` 口径正确（注册用户数），但它要取一页列表
  才有 `total`，且只能回答用户域。一次报表要 5 个域就得发 5 个请求，
  并发下还会各自取到**不同时刻**的快照。
- "在线用户"根本不在 Users 域：它是 `sessions` 表的**去重**计数
  （一个人开三个浏览器 = 3 条会话、**1 个**在线用户），
  而 `GET /admin/sessions?online=true` 的 `total` 数的是**会话**不是人。
  把会话数当成在线用户数上报，是一个看起来对、少数场景下会翻倍的数字。

因此把"报表口径"显式建模为独立契约：一次请求给出全部指标，
且每个指标的**可见性**由该域自身的 API 权限决定
（见 `app/services/statistics.py`）。

关于 `accessible` 与 `null`
--------------------------
每个分组都带 `accessible`；不可见时计数一律为 `null`，**刻意不用 0**：

```text
"你没有权限看这个数字"  与  "系统里一个都没有"  是两件事
```

把两者都渲染成 0，会让无权限的报表看起来像"系统是空的" ——
那是一个比"缺少数据"严重得多的误导（运维据此判断"没人注册"）。

关于数据范围的适用面
------------------
| 分组 | 是否受数据范围约束 | 理由 |
|---|---|---|
| `users` | 是 | 用户记录带 `department_id`，范围可直接下推 |
| `sessions` | 是 | 经 `admin_users` join 后施加 `user_scope_condition` |
| `departments` | 是 | 部门本身就是范围的骨架 |
| `roles` | **否** | 角色是全局配置面，没有"属于哪个部门"的语义 |
| `audit` | **否** | 五张日志表没有 `department_id`（INTERIM-10-01） |

因此响应里的 `scope_policy` 只描述**前三个分组**的口径；
后两个是全局计数，这一点必须在契约里说清楚，
否则调用方会把"角色总数 6"误读成"我可见的角色有 6 个"。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.scope import DataScope

#: 分组通用配置：契约是封闭的，多余字段一律拒绝（`08` 的加固取向）。
_GROUP_CONFIG = ConfigDict(extra="forbid")


class UserStatistics(BaseModel):
    """用户域指标（**受数据范围约束**）。"""

    model_config = _GROUP_CONFIG

    accessible: bool = Field(description="操作者是否具备用户域的读权限；false 时下列计数均为 null")
    total: int | None = Field(default=None, description="注册用户数（未逻辑删除，数据范围内）")
    active: int | None = Field(default=None, description="其中状态为 ACTIVE 的用户数")
    disabled: int | None = Field(default=None, description="其中状态为 DISABLED 的用户数")


class SessionStatistics(BaseModel):
    """会话域指标（**受数据范围约束**）。

    `online_users` 与 `online_sessions` 必须同时给出：
    只给前者无法回答"是不是有人开了很多标签页"，只给后者则不能回答
    "现在到底有几个人在用"。两个数字来自同一份 `WHERE`，
    因此 `online_users <= online_sessions` 恒成立。
    """

    model_config = _GROUP_CONFIG

    accessible: bool = Field(description="操作者是否具备会话域的读权限；false 时下列计数均为 null")
    online_users: int | None = Field(default=None, description="在线用户数（按 user_id **去重**）")
    online_sessions: int | None = Field(default=None, description="在线会话数（同一用户可有多条）")
    total: int | None = Field(default=None, description="历史会话总数（含已撤销 / 已过期）")


class DepartmentStatistics(BaseModel):
    """部门域指标（**受数据范围约束**）。"""

    model_config = _GROUP_CONFIG

    accessible: bool = Field(description="操作者是否具备部门域的读权限；false 时计数为 null")
    total: int | None = Field(default=None, description="部门数（未逻辑删除，数据范围内）")


class RoleStatistics(BaseModel):
    """角色域指标（**全局，不受数据范围约束**）。"""

    model_config = _GROUP_CONFIG

    accessible: bool = Field(description="操作者是否具备角色域的读权限；false 时计数为 null")
    total: int | None = Field(default=None, description="角色数（未逻辑删除，全局）")


class AuditStatistics(BaseModel):
    """审计域指标（**全局，不受数据范围约束**，理由见模块文档）。"""

    model_config = _GROUP_CONFIG

    accessible: bool = Field(description="操作者是否具备审计读权限；false 时计数为 null")
    today: int | None = Field(default=None, description="今日（UTC 自然日 00:00 起）审计记录数")
    total: int | None = Field(default=None, description="审计记录总数（保留期内的全部）")


class StatisticsOverviewResponse(BaseModel):
    """`GET /statistics/overview` 的响应体（`08 §2` 信封中的 `data`）。"""

    model_config = _GROUP_CONFIG

    generated_at: datetime = Field(description="本次统计的生成时刻（UTC）；各分组取自同一时刻")
    scope_policy: DataScope = Field(
        description=(
            "`users` / `sessions` / `departments` 三个分组所依据的数据范围策略；"
            "`roles` 与 `audit` 是全局计数，不适用该范围"
        )
    )
    users: UserStatistics
    sessions: SessionStatistics
    departments: DepartmentStatistics
    roles: RoleStatistics
    audit: AuditStatistics


__all__ = [
    "AuditStatistics",
    "DepartmentStatistics",
    "RoleStatistics",
    "SessionStatistics",
    "StatisticsOverviewResponse",
    "UserStatistics",
]
