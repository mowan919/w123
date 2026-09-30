# VCTN 数据库完整设计 V3.1

本目录是 VCTN 当前数据库的完整设计基线，面向 PostgreSQL + SQLAlchemy/Alembic + BIGINT/Snowflake。

## 文档
- 00-数据库设计总览.md
- 01-系统管理域.md
- 02-统一业务用户域.md
- 03-用户成长中心.md
- 04-Tools工具域.md
- 05-Blog博客域.md
- 06-日志审计与字典域.md
- 07-表关系与索引规范.md
- 08-DDL基线.sql
- 09-数据库完整性检查.md

## 核心原则
1. sys_user 与 biz_user 分离。
2. 当前不做多租户，不增加 tenant_id。
3. 所有主键 BIGINT + Snowflake。
4. JSON API 中 BIGINT ID 序列化为字符串。
5. UTC 存储。
6. 业务用户由 Tools、Blog 统一复用。
7. 成长值与可消费积分分离。
8. 积分/成长值只能通过业务事件和规则产生。
9. 流水不可更新、不可删除。
10. 管理员人工调整必须产生流水和审计。
11. 工具使用统计与工具执行解耦。
12. 权限由后台 RBAC + 动态资源体系控制。
