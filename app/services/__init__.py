"""Service 层。

职责：业务规则 + **服务端授权二次校验** + 审计接入。

事务边界：Service **不**提交事务，由调用方（未来的 API 依赖）统一提交，
以便组合多个 Service 并让测试可回滚（Spec `11 §3` 要求显式事务边界）。
"""

from __future__ import annotations
