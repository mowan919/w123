# Verification 007 — Dictionary · 执行结果

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/007-dictionary.md`（裁判文件，**未修改**） |
| 执行 Phase | `PHASES.md` **Phase 7 — Dictionary / System Parameter**（= `docs/agent/PHASE-007-DICTIONARY.md`） |
| 执行时间 | 2026-09-25 02:45 UTC |
| 代码基线 | `49b7cee`（feat: complete phase 6 logging audit trace）+ 本阶段全部改动 |
| 前置判定 | 本 Phase **未**触发 `BLOCKED — NEED USER DECISION`：Spec 缺的是"表名与端点路径"，属**最小技术推导**（改动面明确、可逆），不是业务规则冲突。逐条登记在 `docs/DESIGN-DECISIONS.md §14` |
| 数据库变化 | **有**。新增 `sys_dict_type` / `sys_dict_item` / `sys_params` 三表 + 8 条索引；迁移 `phase7_dict`（Revises `phase6_dd08`），并在 `sys_params` 写入 Seed 行 `mfa.required_default`。`alembic check` → `No new upgrade operations detected.` |
| 执行方式 | `ruff check` + `ruff format --check` + `mypy` + `alembic check` + 完整 `pytest` |
| 门禁结果 | 见 §4 |
| 结论 | **PASS**（18/18 裁判项通过；另 §2 自证 6 项前提全部通过；0 项 BLOCKED；0 项 NOT RUN） |

> 说明：本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/007-dictionary.md` 的 18 个检查项内容**一字未改**。
>
> Phase 编号说明：本项目提交信息与迁移 `revision` 使用 `docs/agent/PHASE-00N` 编号，
> 与 `PHASES.md` 编号**相差一位**。本次执行 `PHASES.md` Phase 7 —
> Dictionary / System Parameter，对应 `docs/agent/PHASE-007-DICTIONARY.md`。

---

## 1. 逐项判定

### 1.1 Dictionary Type（5 项）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | `dict_code` | 对外稳定标识；软删除感知唯一；**不可修改** | `sys_dict_type.dict_code`（VARCHAR(64)，NOT NULL）；partial unique index `uq_sys_dict_type_dict_code_active`（`WHERE deleted_at IS NULL`）→ 逻辑删除后可用同一编码重建；`DictTypeUpdateRequest` **不含**该字段（`extra="forbid"` → 422），服务层 `update_type` 也无该形参 | **PASS** | `app/models/dict.py:80`、`:93`、`:116`（索引）；`app/schemas/dict.py:77`；`app/services/dict.py:335`；`tests/test_dict_service.py::TestDictTypeCrud::test_code_can_be_reused_after_delete`、`::test_duplicate_code_is_rejected`、`tests/test_dict_api.py::TestDictTypeHttp::test_dictionary_code_is_not_updatable` |
| 2 | `dict_name` | 必填、可修改、有长度上界 | `dict_name`（VARCHAR(128)，NOT NULL）；创建必填（DTO `min_length=1`），修改可省略（None = 不改）；超长在服务层转 400 而不是让数据库报错 | **PASS** | `app/models/dict.py:98`；`app/schemas/dict.py:72`、`:86`；`app/services/dict.py:212`（`_assert_text_lengths`）；`tests/test_dict_service.py::TestDictTypeCrud::test_create_persists_all_spec_fields`、`::test_update_writes_before_and_after_audit` |
| 3 | `description` | 可空、有长度上界 | `description`（VARCHAR(255)，NULL 允许）；DTO `max_length=255`；服务层同时拒绝"全空白"（`" "` 能通过 `min_length=1`） | **PASS** | `app/models/dict.py:103`；`app/schemas/dict.py:73`；`app/services/dict.py:212`；`tests/test_dict_api.py::TestDictTypeHttp::test_blank_code_returns_400` |
| 4 | `status` | 取值受约束（ACTIVE / DISABLED） | `DictStatus`（StrEnum）经 `enum_type()` → VARCHAR + CHECK 约束 **`ck_sys_dict_type_status`**（`native_enum=False`，避免 PostgreSQL 原生枚举的迁移代价）。约束已在实际数据库中以 `pg_constraint` 核对存在 | **PASS** | `app/models/enums.py`（`DictStatus`）、`:70` 附近（排除复用 `PermissionStatus` 的理由）；`app/models/dict.py:108`；§4 的数据库核对输出；`tests/test_dict_service.py::TestDictTypeCrud::test_update_writes_before_and_after_audit`（ACTIVE → DISABLED） |
| 5 | soft delete | **绝不物理删除**；删除后不可读、可重建 | 删除写 `deleted_at` + `status=DISABLED`（行仍在库中）；所有读路径（`get` / `get_by_code` / `list` / `count`）一律带 `deleted_at IS NULL`；测试以 `db_session.get` 直接确认行仍存在 | **PASS** | `app/models/dict.py:80`（`SoftDeleteMixin`）；`app/repositories/dict.py`（全部查询带 `deleted_at` 过滤）；`app/services/dict.py:368`；`tests/test_dict_service.py::TestDictTypeCrud::test_delete_is_soft_and_cascades_items`、`tests/test_dict_api.py::TestDictTypeHttp::test_crud_round_trip` |

### 1.2 Dictionary Item（9 项）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 6 | `dict_type_id` | 指向所属字典；删除类型时**不得留下孤儿项** | `sys_dict_item.dict_type_id` BIGINT NOT NULL + `ForeignKey("sys_dict_type.id", ondelete="RESTRICT")` + 索引；服务层删除类型时**级联逻辑删除**其全部项（响应与审计如实回报 `deleted_item_count` / `deleted_item_ids`），重建同编码字典不会"长出"旧项 | **PASS** | `app/models/dict.py:141`；`app/services/dict.py:368`；`app/repositories/dict.py::soft_delete_items`；`tests/test_dict_service.py::TestDictTypeCrud::test_delete_is_soft_and_cascades_items`、`tests/test_dict_api.py::TestDictItemHttp::test_deleting_the_type_cascades_items_over_http` |
| 7 | `item_label` | 必填、有长度上界 | `item_label`（VARCHAR(128)，NOT NULL）；DTO `min_length=1`；服务层长度与非空校验 | **PASS** | `app/models/dict.py:148`；`app/schemas/dict.py:148`；`app/services/dict.py:212`；`tests/test_dict_service.py::TestDictItemCrud::test_create_persists_all_spec_fields` |
| 8 | `item_value` | 必填；**同字典内软删除感知唯一** | `item_value`（VARCHAR(128)，NOT NULL）；partial unique index **`uq_sys_dict_item_type_value_active`**（`(dict_type_id, item_value) WHERE deleted_at IS NULL`）作最终保证；服务层预校验（`get_by_value` 排除自身）把冲突提前成友好的 409；`item_value` **可修改**（改值时重新校验唯一性） | **PASS** | `app/models/dict.py:153`、`:188`（索引）；`app/services/dict.py:238`（`_assert_value_available`）、`:489`（`update_item`）；`tests/test_dict_service.py::TestDictItemUniqueness`（含 `test_database_index_is_the_final_guard`：绕过服务层直接写库也必须被数据库拒绝） |
| 9 | `item_code` | 必填、有长度上界 | `item_code`（VARCHAR(64)，NOT NULL）；与 `item_value` **分开**：`item_value` 是"存进业务数据的值"，`item_code` 是稳定的短标识，不作隐式回落 | **PASS** | `app/models/dict.py:158`；`app/models/dict.py:125` 的类文档（说明为何不回落）；`tests/test_dict_service.py::TestDictItemCrud::test_create_persists_all_spec_fields` |
| 10 | `sort_order` | 参与排序且顺序**稳定** | `sort_order` INTEGER NOT NULL（默认 0）；读取时 `ORDER BY sort_order, id` —— 仅按 `sort_order` 排序在 PostgreSQL 下不保证稳定（同值时顺序随机），会让前端下拉框顺序跳动 | **PASS** | `app/models/dict.py:163`；`app/repositories/dict.py::list_items`；`tests/test_dict_service.py::TestDictItemCrud::test_items_are_ordered_by_sort_order_then_id`、`tests/test_dict_api.py::TestDictItemHttp::test_items_are_ordered_by_sort_order_then_id` |
| 11 | `status` | 取值受约束（ACTIVE / DISABLED） | 同 `DictStatus` → CHECK 约束 **`ck_sys_dict_item_status`**（已在数据库核对） | **PASS** | `app/models/dict.py:169`；§4 的数据库核对输出；`tests/test_dict_api.py::TestDictItemHttp::test_items_include_disabled_ones_by_default` |
| 12 | `is_default` | 有该字段，且同一字典"至多一个默认项" | `is_default` BOOLEAN NOT NULL（默认 false）；服务层取"后者胜"（**写前**清同字典其他项，顺序有专门注释），数据库 partial unique index `uq_sys_dict_item_type_default_active` 兜底 —— 服务层不是唯一写入路径 | **PASS** | `app/models/dict.py:175`、`:195`（索引）；`app/services/dict.py:246`（`_apply_default`）；`tests/test_dict_service.py::TestOneDefaultPerType`（含 `test_second_default_replaces_the_first`）、`tests/test_dict_api.py::TestDictItemHttp::test_only_one_default_item_survives` |
| 13 | `description` | 可空、有长度上界 | `description`（VARCHAR(255)，NULL 允许） | **PASS** | `app/models/dict.py:181`；`app/services/dict.py:212` |
| 14 | soft delete | 逻辑删除；删除后不可读，**同 `item_value` 可复用** | 删除写 `deleted_at` + `status=DISABLED` + `is_default=false`；读路径带 `deleted_at IS NULL`；删除后同 `item_value` 可再次创建（软删除感知唯一性） | **PASS** | `app/services/dict.py:564`；`app/repositories/dict.py::soft_delete_items`；`tests/test_dict_service.py::TestDictItemCrud::test_delete_is_soft_and_value_can_be_reused`、`tests/test_dict_api.py::TestDictItemHttp::test_item_crud_round_trip` |

### 1.3 Rules（4 项）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 15 | same dict type `item_value` soft-delete-aware unique | **跨字典相同取值必须允许**；同字典内删除后可复用 | 唯一性建立在 `(dict_type_id, item_value)` 且 `WHERE deleted_at IS NULL`（partial index）。三条独立用例：① 两个字典各自有 `item_value='A'` 必须都能创建；② 同字典内重复必须拒绝；③ 同字典删掉后再建同样的 `item_value` 必须成功 | **PASS** | `app/models/dict.py:188`（`uq_sys_dict_item_type_value_active`）；`tests/test_dict_service.py::TestDictItemUniqueness::test_same_value_in_another_type_is_allowed`、`::test_same_value_in_same_type_is_rejected`、`::test_database_index_is_the_final_guard`、`TestDictItemCrud::test_delete_is_soft_and_value_can_be_reused` |
| 16 | CRUD API | `05 §4` 列的 9 条管理端点**一条不缺、一条不多** | `GET/POST /api/v1/admin/dicts`；`GET/PUT/DELETE /api/v1/admin/dicts/{id}`；`GET/POST /api/v1/admin/dicts/{id}/items`；`PUT/DELETE /api/v1/admin/dicts/{id}/items/{itemId}`。路由面以 `app.openapi()["paths"]` **正向钉住**（含"不得出现未冻结的第 10 条"） | **PASS** | `app/api/v1/endpoints/dicts.py:115`、`:132`、`:151`、`:162`、`:182`、`:210`、`:222`、`:246`、`:277`；`tests/test_dict_api.py::TestRouteSurface::test_dictionary_and_param_paths_exist_exactly_as_specified` |
| 17 | public dictionary query API | `GET /api/v1/dicts/{dictCode}` 存在，**不在** admin 域，只下发 ACTIVE 项 | 独立 `public_router` 挂载于 `settings.public_v1_prefix`（`/api/v1`）。响应**不含**内部 ID（逐字节扫描响应原文断言）；`DISABLED` 字典与已删除字典返回**同一个** 404（不把停用状态变成可探测信号）；端点必须已认证（JUDGMENT-7-03），但不要求 `DICT_MANAGE` —— 后一条也有反向用例（"不该拒的没被拒"） | **PASS** | `app/api/v1/endpoints/dicts.py:298`；`app/main.py:115`；`app/core/config.py:60`；`tests/test_dict_api.py::TestPublicQueryHttp`（5 例）、`::TestAccessControl::test_public_query_accepts_any_authenticated_user`、`::test_public_query_requires_authentication`、`tests/test_dict_service.py::TestPublicQuery` |
| 18 | dictionary 与 system parameter 分离 | 两张表 / 两套服务 / 两套端点；权限位也分离 | `sys_dict_type` / `sys_dict_item` / `sys_params` 三表互不相同；`DictService` 不含任何 "param" 方法，`SystemParameterService` 不含任何字典方法；AST 扫描两个模块的 import，**禁止**互相引入；权限位 `DICT_MANAGE` 与 `PARAM_MANAGE` 各自独立（双向用例：字典管理员管不了参数、参数管理员管不了字典） | **PASS** | `app/models/dict.py` / `app/models/param.py`（表名）；`app/services/authorization.py:278`、`:287`；`tests/test_system_param.py::TestSeparation`（6 例）、`tests/test_dict_api.py::TestAccessControl::test_dict_manage_does_not_imply_param_manage`、`tests/test_param_api.py::TestAccessControl::test_endpoints_reject_users_without_param_manage` |

---

## 2. 裁判之外、本阶段必须自证的前提

`PHASES.md` 的 Phase 7 除了 Dictionary 还要求交付 **System Parameter** 与
**Admin APIs**，而裁判 007 只有一条"分离"间接覆盖它。以下 6 项是本阶段
在裁判文本之外**必须自证**的内容 —— 缺了它们，"分离"与"Dictionary 完成"
都无法被证明。

| # | 前提 | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| A | System Parameter 具备 `05 §5` 的四要素 | 类型 / 默认值 / 状态 / 描述**逐项存在** | `sys_params`：`param_type`（STRING/INT/BOOL，CHECK 约束）、`default_value`（NOT NULL）、`status`（ACTIVE/DISABLED）、`description`（可空）；`param_value` 可空 = "未显式设置" | **PASS** | `app/models/param.py:97`、`:107`、`:112`、`:117`、`:128`；`tests/test_system_param.py::TestParamCrud::test_create_persists_all_spec_fields` |
| B | System Parameter 有**审计** | 每次写入产生 `06 §2` 的审计事件（before/after） | `PARAM_CREATE/UPDATE/DELETE` 三个动作，`AuditGuard` 统一产出；**拒绝也留痕**（`denial_audited`，5 条用例断言 5 个 FAILURE） | **PASS** | `app/audit/events.py:139`；`app/services/system_param.py:319`、`:381`、`:456`；`tests/test_system_param.py::TestAuthorization::test_denied_without_param_manage_and_failure_is_audited` |
| C | 参数**有类型**这条要求必须在读取侧产生实际约束 | 类型不符必须失败，而不是静默转换 | `get_bool` / `get_int` / `get_str` 与声明类型不一致 → `ConfigurationError`；`BOOL` 只接受 `true`/`false`（刻意不接受 `1`/`yes`/`on`）；`INT` 用 `fullmatch(r"-?\d+")`（刻意不用会接受全角数字的 `isdigit`）；写入侧同样校验（非法字面量不进库） | **PASS** | `app/services/system_param.py:179`（`_parse_literal`）、`:502`（`_read_typed`）、`:255`（`_validate_value`）；`tests/test_system_param.py::TestTypedRead::test_type_mismatch_fails_closed`、`::test_default_value_must_match_declared_type` |
| D | MFA system 级默认值迁入参数表（`§12.1` 兑现） | 迁移前后行为一致；不降低安全要求 | `mfa.required_default`（Seed 行 `700001` / BOOL / ACTIVE / `param_value=NULL` / `default_value='false'`）。**端到端**：参数改 `false` → 登录 200；改 `true` + 无 Provider → 登录 **500 且不创建会话**；行停用 → 同样 fail-closed；行缺失 → 回退环境变量（= 迁移前口径）。代码常量 / Seed 字面量 / Seed 主键三者一致由测试钉住 | **PASS** | `app/services/system_param.py:109`、`:535`；`app/api/deps.py`（两个工厂 `await resolve_mfa_required_default(session)`）；迁移 `20260925_0946_phase7_dict_params.py`（Seed）；`tests/test_param_mfa_binding.py`（15 例） |
| E | 迁移与模型一致 | `alembic check` 不得有差异 | `No new upgrade operations detected.`（三表 8 索引与模型逐条核对一致） | **PASS** | §4 |
| F | BIGINT 业务 ID 在 JSON 中为**字符串** | `07 §2` / `00 §6` 冻结 | `SnowflakeId` 类型：输入 str/int，Python 值为 int，JSON 输出为字符串。字典类型 / 字典项 / 参数三类响应均有用例断言 `isinstance(id, str)` | **PASS** | `app/schemas/types.py`；`tests/test_dict_api.py::TestDictTypeHttp::test_business_id_is_a_json_string`、`tests/test_param_api.py::TestParamHttp::test_business_id_is_a_json_string` |

---

## 3. BLOCKED CHECKS

**无。** 18 项裁判项 + 6 项自证前提全部 PASS，0 项 NOT RUN，0 项 BLOCKED。

本 Phase **未**触发 `BLOCKED — NEED USER DECISION`。判据：Spec 缺的两项
（系统参数表名、系统参数端点路径）属**技术形态推导**而非业务规则冲突 ——
改动面分别是"一次 migration + 一处 `__tablename__`"与
"一处 `include_router` 前缀 + 路由装饰器"，且不与任何 Frozen 条款冲突。
逐条登记在 `docs/DESIGN-DECISIONS.md §14.1`（INTERIM-7-01 ~ 7-10）。

### 3.1 本 Phase 的登记项（全部为 INTERIM / 判断项，非阻塞）

| 编号 | 内容 | 是否阻塞 |
|---|---|---|
| INTERIM-7-01 | 系统参数表名 `sys_params` | 否（可逆，改动面明确） |
| INTERIM-7-02 | `DISABLED` 参数读取侧 fail-closed | 否（安全方向：更严） |
| INTERIM-7-03 | 至多一个默认项（服务层"后者胜" + partial unique index） | 否（若裁定允许多默认项，改动面是一条索引） |
| INTERIM-7-04 | 系统参数端点 `/api/v1/admin/params` + `settings.public_v1_prefix` | 否（路径可改，不动服务层与模型） |
| INTERIM-7-05 | 公开字典查询不写审计 | 否（管理侧读仍逐次审计） |
| INTERIM-7-06 | `PARAM_*` 写操作归入安全日志 | 否（更严方向） |
| INTERIM-7-07 | 允许删除默认项 | 否 |
| INTERIM-7-08 | 参数审计**不记录值**（只记 `value_is_set` / 长度 / 生效来源） | 否（安全方向：更严；代价是答不出"改前是什么值"） |
| INTERIM-7-09 | `param_key` 不允许空白字符 | 否 |
| INTERIM-7-10 | `param_key` / `param_type` 不可修改 | 否（与 `dict_code` / `role_code` 同口径） |
| JUDGMENT-7-03 | 公开字典查询必须**已认证**、不要求 `DICT_MANAGE` | 否（改动面只有一处依赖） |
| FINDING-7-01 | 登录路径此前用默认 MFA 解析器（角色级策略失效）→ **已修复** | 否（修复方向：收紧） |

---

## 4. 门禁与迁移证据

```text
--- ruff check ---            All checks passed!
--- ruff format --check ---   200 files already formatted
--- mypy ---                  Success: no issues found in 99 source files
--- alembic check ---         No new upgrade operations detected.
--- pytest ---                1088 passed in 1031.83s (0:17:11)   ← 零告警
EXIT=0
```

**增量**：Phase 6 结束时为 `955 passed`，本次 `1088 passed` →
新增 **133** 例，全部来自本 Phase 的五个测试文件（无既有用例被删除或改写为弱断言）。

**迁移**：`alembic/versions/20260925_0946_phase7_dict_params.py`

```text
phase6_dd08 -> phase7_dict (head)
```

新增三表与六索引（**已与实际数据库核对**，`pg_indexes` / `pg_constraint`）：

| 表 | 约束 / 索引（数据库中的实际对象名） | 说明 |
|---|---|---|
| `sys_dict_type` | `pk_sys_dict_type`、`ck_sys_dict_type_status`、`uq_sys_dict_type_dict_code_active`（partial）、`ix_sys_dict_type_deleted_at` | `05 §2` 冻结表名与字段；`status` 的取值约束由数据库强制 |
| `sys_dict_item` | `pk_sys_dict_item`、`ck_sys_dict_item_status`、`fk_sys_dict_item_dict_type_id_sys_dict_type`（ON DELETE RESTRICT）、`uq_sys_dict_item_type_value_active`（partial）、`uq_sys_dict_item_type_default_active`（partial）、`ix_sys_dict_item_dict_type_id`、`ix_sys_dict_item_deleted_at` | `05 §3` 冻结字段 + `05 §3` 的软删除感知唯一 + INTERIM-7-03 |
| `sys_params` | `pk_sys_params`、`ck_sys_params_param_type`、`ck_sys_params_status`、`uq_sys_params_param_key_active`（partial）、`ix_sys_params_deleted_at` | INTERIM-7-01 表名；`05 §5` 的四要素 |

三条 partial unique index 的实际定义（数据库原文）：

```text
uq_sys_dict_type_dict_code_active   UNIQUE (dict_code)                     WHERE (deleted_at IS NULL)
uq_sys_dict_item_type_value_active  UNIQUE (dict_type_id, item_value)      WHERE (deleted_at IS NULL)
uq_sys_dict_item_type_default_active UNIQUE (dict_type_id)                 WHERE (is_default AND (deleted_at IS NULL))
uq_sys_params_param_key_active      UNIQUE (param_key)                     WHERE (deleted_at IS NULL)
```

```text
SELECT version_num FROM alembic_version;   -- phase7_dict
```


**Seed**（`sys_params`，一次写入）：

```text
id=700001  param_key='mfa.required_default'  param_type='BOOL'
param_value=NULL   default_value='false'   status='ACTIVE'
```

> Seed 的 `param_value` 刻意留空：当前值一旦预设，"默认值"就没有落点。
> 该行的形状（类型 / 状态 / 空当前值 / 默认 false）由
> `tests/test_param_mfa_binding.py::TestMigrationConsistency::test_seeded_row_shape_is_the_migration_contract`
> 直接读库断言。

**本阶段新增测试**：`tests/test_dict_service.py`（32）、`tests/test_dict_api.py`（32）、
`tests/test_system_param.py`（37）、`tests/test_param_api.py`（17）、
`tests/test_param_mfa_binding.py`（15），共 **133** 例。
分层：`*_service.py` 验证业务判定，`*_api.py` 验证接线（路由面 / 状态码 / 信封 /
ID 序列化 / 访问控制）。分开的理由写在 `tests/test_dict_api.py` 的模块 docstring：
混在一起时失败原因会变模糊（"409 是因为唯一性判定错了，还是因为路由没接上？"）。

---

## 5. 执行过程中发现并修复的缺陷

完整记录见 `docs/DESIGN-DECISIONS.md §14.2` / `§14.3`。三条都不是"顺手改"，
而是**测试真正跑起来之后**才暴露的：

| # | 缺陷 | 严重度 | 触发 | 修复 |
|---|---|---|---|---|
| 1 | `create_item(is_default=True)` 在"同字典已有默认项"时**撞数据库约束**（500 级） | High | `TestOneDefaultPerType::test_second_default_replaces_the_first` | 把"清同字典默认项"提前到 `add()`（会 flush）**之前** |
| 2 | `soft_delete_items` / `clear_default` 用 Core `update()`，**不维护身份映射** → 同事务内 `session.get()` 返回 `deleted_at is None` 的幽灵对象 | High（响应体/审计可能取自幽灵状态） | `TestDictTypeCrud::test_delete_is_soft_and_cascades_items` | 改为 ORM 变更 + 显式 `flush()`；并删除因此不再使用的 `count_items` / `list_item_ids` |
| 3 | **FINDING-7-01**：`get_auth_service` 构造的 `MfaService` 用**默认**解析器 → 角色级 MFA 策略在登录路径上完全不生效，Phase 5 的"策略要求但无 Provider"fail-closed 分支永远不会触发 | High（安全分支失效） | 本 Phase 首次真正走依赖装配路径时发现 | 统一改用 `build_policy_resolver(MfaRepository, RoleRepository, system_default=...)`，并由依赖层解析 system 层默认值 |

另修复一处**测试卫生**问题：`TestDictItemUniqueness::test_database_index_is_the_final_guard`
故意触发的 `IntegrityError` 会中止外层事务，导致夹具回滚时产生
`SAWarning: transaction already deassociated from connection`。
改为用显式**保存点**（`begin_nested()`）包住那次故意失败 ——
PostgreSQL 报错后会把当前事务标记为 aborted，不用保存点就会污染整套测试的输出。
修复后整套测试**零告警**。

---

## 6. 复现方式

```bash
# 门禁（等价于 .\scripts\dev.ps1 -Action verify 加 alembic check）
./.venv/Scripts/ruff.exe check .
./.venv/Scripts/ruff.exe format --check .
./.venv/Scripts/mypy.exe
./.venv/Scripts/alembic.exe check
./.venv/Scripts/python.exe -m pytest -q

# 本 Phase 的测试（约 4 分钟）
./.venv/Scripts/python.exe -m pytest tests/test_dict_service.py tests/test_dict_api.py \
    tests/test_system_param.py tests/test_param_api.py tests/test_param_mfa_binding.py -q
```
