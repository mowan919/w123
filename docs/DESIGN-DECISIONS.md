# 未冻结设计决策登记表（Design Decision Register）

> 本文件**不是 Spec**，也不修改任何冻结结论。
> 它是 Agent 侧的**登记台账**：记录哪些设计点尚未冻结、当前实现采取了什么
> 临时措施（INTERIM）、以及被推迟到哪个 Phase 处理。
>
> 一旦对应 Spec 冻结，应回填"冻结依据"，并同步移除代码中的 `INTERIM` 标注。
> 冻结业务规则的唯一权威来源始终是 `docs/spec/`。

---

## 1. 登记状态总览

| 编号 | 主题 | 当前状态 | 目标 Phase |
|---|---|---|---|
| DD-01 | MFA Provider | 未冻结（Spec 04 未定 Provider） | Phase 5 |
| DD-02 | Token 生命周期 | 未冻结 | Phase 4 |
| DD-03 | Redis Key 命名 | 未冻结 | Phase 4 |
| DD-04 | Permission Version | 未冻结 | Phase 8 |
| **DD-05** | **角色继承（Role Inheritance）存储与展开** | **DEFERRED TO PHASE 3** | Phase 3 |
| DD-06 | Field Permission 表结构 | 未冻结 | Phase 8 |
| **DD-07** | **CUSTOM Data Scope 的持久化模型** | **DEFERRED TO PHASE 3** | Phase 3 |
| **DD-08** | **日志分区策略** | **DEFERRED** | 日志相关 Phase（Phase 6） |
| DD-09 | Secret Manager | 未冻结 | Phase 9 |
| DD-10 | Rate Limit 阈值 | 未冻结 | Phase 9 |
| DD-11 | 幂等策略 | 未冻结 | Phase 4 |
| DD-12 | 错误码段位表 | 未冻结（现用集中式 INTERIM 码） | 待定 |
| DD-13 | 分页协议 | 未冻结（现用 `pageNum`/`pageSize` + `{list,total,...}` 临时协议） | 待定 |
| DD-14 | Snowflake 参数（epoch / 机器位分配） | 未冻结（现用默认参数） | 待定 |
| DD-16 | 版本策略 | 未冻结 | 待定 |
| DD-18 | PostgreSQL / Redis 镜像版本 | 未冻结（本地不装 Docker，仅交付部署产物） | 待定 |

---

## 2. 本次裁定（Phase 2 收尾）

### DD-05 Role Inheritance — DEFERRED TO PHASE 3

- **裁定**：Phase 2 **不实现**角色继承。
- **现状**：未创建 `role_inheritances` 表；`RoleRepository` 只做直接角色关联
  （`user_roles`），不做继承展开。
- **约束**：`00 §1#3` 已冻结"V1 支持角色继承"，因此继承**必须**在 Phase 3 落地；
  不得以"不支持继承"作为最终形态。
- **Phase 3 必须补齐**：存储模型、继承展开、环路检测、权限并集计算、审计。

### DD-07 CUSTOM Data Scope — DEFERRED TO PHASE 3

- **裁定**：Phase 2 **不实现** CUSTOM 的数据库最终模型。
- **现状**：`app/core/scope.py` 只提供 CUSTOM 的**算法支持**
  （`CurrentActor.custom_department_ids` 由外部传入），
  并在注释中明确"不实现任何存储"。
- **⚠️ 明确禁止的误读**：**不得把"外部传入 CUSTOM 范围"当作最终实现**。
  它只是算法占位，不是交付形态。
- **Phase 3 必须补齐**：CUSTOM 数据范围持久化、数据范围查询、授权校验、
  修改、删除、审计（六项全部必须，缺一不可）。

### DD-08 日志分区 — DEFERRED

- **裁定**：Phase 2 **不实现**日志分区。
- **约束**：**不得因此修改当前日志行为**（分区是存储层优化，
  不影响 Phase 1 已交付的日志格式与脱敏规则）。
- **处理时机**：进入日志相关 Phase（Phase 6）时再处理。

---

## 3. Phase 2 期间新增的 INTERIM 取值（已在代码内标注 `INTERIM`）

这些不是 DD 编号项，而是 Agent 在实现中为让功能可运行而选取的
**临时技术默认值**；Spec 未规定，故登记待确认。

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/auth/actor.py` | `SUPER_ADMIN_ROLE_CODE = "SUPER_ADMIN"` | Spec 未冻结 SUPER_ADMIN 的标识方式；集中单点常量，冻结后只改一处 |
| `app/models/*` | 各列 `String(n)` 长度 | Spec 未规定字段长度，取常规值并与 schema 保持一致 |
| `app/db/types.py` | `VARCHAR(16) + CHECK`（`native_enum=False`） | 枚举落库形态选择；Spec 未规定 |
| `app/core/error_codes.py` | `INTERIM` 错误码 | DD-12 未冻结 |
| `app/schemas/user.py` | 分页字段名 `pageNum` / `pageSize`、响应体 `{list,total,pageNum,pageSize}` | 人类裁定采用，但 DD-13 仍未冻结 |

---

## 4. 需要人类裁定的行为外推（Phase 2 已按"同一意图"实现）

| 项 | Spec 原文范围 | 本次实现 | 状态 |
|---|---|---|---|
| 创建用户时 `must_change_password` | `00 §2` 只规定"管理员**重置**密码后"必须改密 | 创建同样置 `True` | 已裁定（RISK-001） |
| 禁用 / 删除**最后一个** SUPER_ADMIN | `00 §1#7` 只规定"其他管理员不能踢 SUPER_ADMIN" | 禁止禁用 / 逻辑删除最后一个，且记 FAILURE 审计 | 已裁定（RISK-002） |
| 响应返回真实手机号 / 邮箱 | `00 §8` / `06 §4` 只约束日志与审计 | 响应返回真实值；脱敏仅在日志 / 审计链路 | 已裁定（RISK-003） |
| 解除强制改密的入口 | `00 §2` 只规定"必须改密"，未规定如何解除 | 新增 `UserService.change_own_password`（HTTP 端点属 Phase 4） | 已裁定（RISK-001 配套） |
