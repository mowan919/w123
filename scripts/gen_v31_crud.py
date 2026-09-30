"""V3.1 四新增域结构层 CRUD 代码生成器（VCTN §33，一次性工具）。

读取 `app.models.{biz_user,growth,tool,blog}` 的 ORM 模型，
为每个实体生成：
  - `app/schemas/v31_<domain>.py`：每个实体的
    `XResponse` / `XListQuery` / `XCreateRequest` / `XUpdateRequest` / `XPageResponse`
  - `app/api/v1/endpoints/v31_<domain>.py`：每个实体的标准 CRUD 路由
    （list / get / create / update / delete），复用 `app.crud.base.BaseCrudService`。

生成的是**静态、强类型**文件（满足 `mypy --strict`），不是运行时动态模型。
业务规则（§09-D 未冻结项）一律不生成。

用法：
    python scripts/gen_v31_crud.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import INET, JSONB

from app.models import biz_user as m_biz_user
from app.models import blog as m_blog
from app.models import growth as m_growth
from app.models import tool as m_tool

ROOT = Path(__file__).resolve().parent.parent

#: 域配置：(模型模块, 权限码前缀, 审计动作前缀, 中文标签)
DOMAINS: dict[str, tuple[object, str, str, str]] = {
    "biz_user": (m_biz_user, "BIZ_USER", "BIZ_USER", "统一业务用户"),
    "growth": (m_growth, "GROWTH", "GROWTH", "用户成长中心"),
    "tool": (m_tool, "TOOL", "TOOL", "Tools 工具"),
    "blog": (m_blog, "BLOG", "BLOG", "Blog 博客"),
}

#: 永远不作为请求字段出现的列 + 服务端托管字段（见 `app.crud.base`）。
_NEVER_REQUEST = {"id", "created_at", "updated_at", "deleted_at"}
_SERVER_MANAGED = {
    "created_by",
    "created_by_username",
    "updated_by",
    "approved_by",
    "reviewed_by",
    "operator_id",
    "operator_username",
}
#: 敏感列：既不进响应也不进请求。
_SENSITIVE = {
    "password_hash",
    "password",
    "salt",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "totp_secret",
    "mfa_secret",
    "credential",
}
#: 会被当作"枚举型过滤列"处理的列名：这些列若在模型上是 `SAEnum`，
#: 列表查询契约里就带上它（前端按等值过滤）。抽成常量是为了让
#: `gen_schema_file` 的预扫描、实际生成与前端元数据共用同一份取值，不会漂移。
_FILTERABLE = frozenset(
    {"status", "type", "code", "category", "visibility", "state", "level", "kind"}
)


def camel_to_snake(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s


def camel_to_kebab(name: str) -> str:
    return camel_to_snake(name).replace("_", "-")


def _col_type_expr(col, nullable: bool = False) -> tuple[str, str | None]:
    """返回 (类型表达式, 待导入的枚举类全名 or None)。"""
    t = col.type
    if col.foreign_keys:
        return "SnowflakeId", None
    if isinstance(t, SAEnum):
        enum_cls = t.enum_class
        return enum_cls.__name__, f"{enum_cls.__module__}.{enum_cls.__name__}"
    if isinstance(t, Boolean):
        return "bool", None
    if isinstance(t, DateTime):
        base = "datetime"
    elif isinstance(t, Date):
        base = "date"
    elif isinstance(t, Numeric):
        base = "float"
    elif isinstance(t, (BigInteger, Integer)):
        base = "int"
    elif isinstance(t, JSONB):
        base = "dict[str, Any]"
    elif isinstance(t, (INET, String)):
        base = "str"
    else:
        base = "Any"
    return (f"{base} | None" if nullable else base), None


def _field_default(col):
    """返回 (Field() 调用串, 是否为必填)。"""
    default_parts: list[str] = []
    d = col.default
    is_scalar = getattr(d, "is_scalar", False)
    is_callable = getattr(d, "is_callable", False)
    has_default = bool(is_scalar or is_callable or col.server_default is not None)
    if is_scalar:
        arg = d.arg  # type: ignore[attr-defined]
        if isinstance(arg, bool):
            default_parts.append(f"default={arg!r}")
        elif isinstance(arg, int):
            default_parts.append(f"default={arg}")
        elif isinstance(arg, str):
            default_parts.append(f"default={arg!r}")
        elif isinstance(arg, SAEnum):  # pragma: no cover - 枚举默认
            default_parts.append(f"default={arg.value!r}")
    if isinstance(col.type, String) and getattr(col.type, "length", None):
        default_parts.append(f"max_length={col.type.length}")
    required = (not col.nullable) and (not has_default)
    if default_parts:
        return "Field(" + ", ".join(default_parts) + ")", required
    return "Field()", required


def _iter_models(module) -> list[type]:
    models = []
    for name in dir(module):
        obj = getattr(module, name)
        if not isinstance(obj, type):
            continue
        if not hasattr(obj, "__tablename__"):
            continue
        if obj.__module__ != module.__name__:
            continue
        models.append(obj)
    return models


def gen_schema_file(domain: str, models: list[type]) -> str:
    enum_imports: set[str] = set()
    # 预扫描：先收集所有枚举导入，确保写在文件头（注解在 `from __future__` 之后才可用）。
    for model in models:
        for col in model.__table__.columns:
            if col.name in _SENSITIVE:
                continue
            _, enum_imp = _col_type_expr(col)
            if enum_imp:
                enum_imports.add(enum_imp)
            # 枚举型过滤列的注解同样会产生导入（与 Response 的类型注解一致）。
            if (
                col.name not in _NEVER_REQUEST | _SERVER_MANAGED | _SENSITIVE
                and col.name in _FILTERABLE
            ):
                _, enum_imp = _col_type_expr(col)
                if enum_imp:
                    enum_imports.add(enum_imp)

    lines: list[str] = []
    lines.append('"""V3.1 结构层 CRUD 契约（VCTN §33，自动生成）。')
    lines.append("")
    lines.append("本文件由 `scripts/gen_v31_crud.py` 生成；业务规则（§09-D 未冻结项）不在此处。")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import builtins")
    lines.append("from datetime import date, datetime")
    lines.append("from typing import Any")
    lines.append("")
    lines.append("from pydantic import BaseModel, ConfigDict, Field")
    lines.append("")
    lines.append("from app.schemas.types import SnowflakeId")
    lines.append("")
    for imp in sorted(enum_imports):
        module_path, cls_name = imp.rsplit(".", 1)
        lines.append(f"from {module_path} import {cls_name}")
    lines.append("")

    for model in models:
        cls = model.__name__
        resp = f"{cls}Response"
        lq = f"{cls}ListQuery"
        cr = f"{cls}CreateRequest"
        ur = f"{cls}UpdateRequest"
        pr = f"{cls}PageResponse"

        # ---- Response ----
        rlines = [
            f"class {resp}(BaseModel):",
            "    model_config = ConfigDict(from_attributes=True)",
        ]
        for col in model.__table__.columns:
            if col.name in _SENSITIVE:
                continue
            type_expr, enum_imp = _col_type_expr(col, nullable=col.nullable)
            if enum_imp:
                enum_imports.add(enum_imp)
            rlines.append(f"    {col.name}: {type_expr}")
        lines.extend(rlines)
        lines.append("")

        # ---- ListQuery ----
        qlines = [f"class {lq}(BaseModel):", '    model_config = ConfigDict(extra="forbid")']
        qlines.append("    pageNum: int = Field(default=1, ge=1)")
        qlines.append("    pageSize: int = Field(default=20, ge=1, le=100)")
        filter_names: list[str] = []
        for col in model.__table__.columns:
            if col.name in _NEVER_REQUEST | _SERVER_MANAGED | _SENSITIVE:
                continue
            name = col.name
            if name in _FILTERABLE:
                type_expr, enum_imp = _col_type_expr(col)
                if enum_imp:
                    enum_imports.add(enum_imp)
                qlines.append(f"    {name}: {type_expr} | None = Field(default=None)")
                filter_names.append(name)
            elif col.foreign_keys:
                qlines.append(f"    {name}: SnowflakeId | None = Field(default=None)")
                filter_names.append(name)
        qlines.append("")
        qlines.append("    def filters(self) -> dict[str, Any]:")
        qlines.append("        data = self.model_dump()")
        qlines.append('        data.pop("pageNum", None)')
        qlines.append('        data.pop("pageSize", None)')
        qlines.append("        return {k: v for k, v in data.items() if v is not None}")
        lines.extend(qlines)
        lines.append("")

        # ---- CreateRequest ----
        clines = [f"class {cr}(BaseModel):", '    model_config = ConfigDict(extra="forbid")']
        for col in model.__table__.columns:
            if col.name in _NEVER_REQUEST | _SERVER_MANAGED | _SENSITIVE:
                continue
            type_expr, enum_imp = _col_type_expr(col)
            if enum_imp:
                enum_imports.add(enum_imp)
            field_call, required = _field_default(col)
            if required:
                clines.append(f"    {col.name}: {type_expr} = {field_call}")
            else:
                clines.append(f"    {col.name}: {type_expr} | None = Field(default=None)")
        lines.extend(clines)
        lines.append("")

        # ---- UpdateRequest ----
        ulines = [f"class {ur}(BaseModel):", '    model_config = ConfigDict(extra="forbid")']
        for col in model.__table__.columns:
            if col.name in _NEVER_REQUEST | _SERVER_MANAGED | _SENSITIVE:
                continue
            type_expr, enum_imp = _col_type_expr(col)
            if enum_imp:
                enum_imports.add(enum_imp)
            ulines.append(f"    {col.name}: {type_expr} | None = Field(default=None)")
        lines.extend(ulines)
        lines.append("")

        # ---- PageResponse ----
        lines.append(f"class {pr}(BaseModel):")
        lines.append(f"    list: builtins.list[{resp}] = Field(default_factory=builtins.list)")
        lines.append("    total: int")
        lines.append("    pageNum: int")
        lines.append("    pageSize: int")
        lines.append("")

    names: list[str] = []
    for model in models:
        cls = model.__name__
        for suffix in ("Response", "ListQuery", "CreateRequest", "UpdateRequest", "PageResponse"):
            names.append(f"{cls}{suffix}")
    lines.append("")
    lines.append("__all__ = [")
    for nm in sorted(names):
        lines.append(f'    "{nm}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_endpoint_file(domain: str, models: list[type], perm_prefix: str, audit_prefix: str) -> str:
    perm = f"ApiPermissionCode.{perm_prefix}_MANAGE"
    a_create = f"AuditAction.{audit_prefix}_CREATE"
    a_update = f"AuditAction.{audit_prefix}_UPDATE"
    a_delete = f"AuditAction.{audit_prefix}_DELETE"
    a_read = f"AuditAction.{audit_prefix}_READ"

    def _svc_block(cls: str, res_type: str) -> list[str]:
        return [
            "    svc = BaseCrudService(",
            "        session,",
            "        audit=BufferingAuditRecorder(),",
            f"        model_cls={cls},",
            f"        permission_code={perm},",
            f"        resource_type={res_type},",
            f"        audit_create={a_create},",
            f"        audit_update={a_update},",
            f"        audit_delete={a_delete},",
            f"        audit_read={a_read},",
            "    )",
        ]

    def _dep(action: str, res_type: str) -> list[str]:
        return [
            "    dependencies=[",
            "        Depends(",
            "            require_api_permission(",
            f"                {perm},",
            f"                action={action},",
            f"                resource_type={res_type},",
            "            )",
            "        ),",
            "    ],",
        ]

    out: list[str] = []
    out.append('"""V3.1 结构层 CRUD 端点（VCTN §33，自动生成）。')
    out.append("")
    out.append("每个实体一组 `APIRouter`（仅 list/get/create/update/delete），")
    out.append("复用 `app.crud.base.BaseCrudService`；权限门 + 审计由底座与路由级依赖共同承担。")
    out.append('"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append("from typing import Annotated")
    out.append("")
    out.append("from fastapi import APIRouter, Depends, Query")
    out.append("from fastapi.responses import JSONResponse")
    out.append("")
    out.append("from app.api.deps import CurrentActorDep, DbSessionDep, require_api_permission")
    out.append("from app.audit import AuditAction")
    out.append("from app.audit.buffer import BufferingAuditRecorder")
    out.append("from app.core.response import success_response")
    out.append("from app.crud.base import BaseCrudService")
    out.append("from app.services.authorization import ApiPermissionCode")
    out.append(f"from app.models.{domain} import (")
    for model in models:
        out.append(f"    {model.__name__},")
    out.append(")")
    out.append(f"from app.schemas.v31_{domain} import (")
    for model in models:
        cls = model.__name__
        out.append(f"    {cls}CreateRequest,")
        out.append(f"    {cls}ListQuery,")
        out.append(f"    {cls}PageResponse,")
        out.append(f"    {cls}Response,")
        out.append(f"    {cls}UpdateRequest,")
    out.append(")")
    out.append("")
    out.append("")
    out.append("ROUTER = APIRouter()")
    out.append("")

    for model in models:
        cls = model.__name__
        var = camel_to_snake(cls)
        res_type = f'"{model.__tablename__}"'
        kebab = camel_to_kebab(model.__tablename__)
        out.append(f'_router_{var} = APIRouter(prefix="/{kebab}", tags=["{domain}"])')
        out.append("")

        # list
        #
        # ⚠️ 读端点**也要**声明式绑定权限：`test_route_authorization_guard.py`
        # 按**路径**判定"是否已声明"，而 `GET /x` 与 `POST /x` 共享同一条路径 ——
        # 只要读端点不声明，整条路径就会被判成"未声明授权"而门禁变红。
        # 语义上也成立：结构层实体清单（例如全部业务用户）本身是敏感信息。
        out.append(f"@_router_{var}.get(")
        out.append('    "",')
        out.append(f'    summary="{cls} 列表",')
        out.extend(_dep(a_read, res_type))
        out.append(")")
        out.append(f"async def list_{var}(")
        out.append(f"    query: Annotated[{cls}ListQuery, Query()],")
        out.append("    actor: CurrentActorDep,")
        out.append("    session: DbSessionDep,")
        out.append(") -> JSONResponse:")
        out.extend(_svc_block(cls, res_type))
        out.append("    page = await svc.list(")
        out.append("        actor=actor,")
        out.append("        filters=query.filters(),")
        out.append("        page_num=query.pageNum,")
        out.append("        page_size=query.pageSize,")
        out.append("    )")
        out.append("    return success_response(")
        out.append(f"        {cls}PageResponse(")
        out.append(f"            list=[{cls}Response.model_validate(i) for i in page.items],")
        out.append("            total=page.total,")
        out.append("            pageNum=page.page_num,")
        out.append("            pageSize=page.page_size,")
        out.append("        )")
        out.append("    )")
        out.append("")

        # get
        out.append(f"@_router_{var}.get(")
        out.append('    "/{entity_id}",')
        out.append(f'    summary="{cls} 详情",')
        out.extend(_dep(a_read, res_type))
        out.append(")")
        out.append(f"async def get_{var}(")
        out.append("    entity_id: int,")
        out.append("    actor: CurrentActorDep,")
        out.append("    session: DbSessionDep,")
        out.append(") -> JSONResponse:")
        out.extend(_svc_block(cls, res_type))
        out.append("    inst = await svc.get(actor=actor, entity_id=entity_id)")
        out.append(f"    return success_response({cls}Response.model_validate(inst))")
        out.append("")

        # create
        out.append(f"@_router_{var}.post(")
        out.append('    "",')
        out.append(f'    summary="{cls} 创建",')
        out.extend(_dep(a_create, res_type))
        out.append(")")
        out.append(f"async def create_{var}(")
        out.append(f"    payload: {cls}CreateRequest,")
        out.append("    actor: CurrentActorDep,")
        out.append("    session: DbSessionDep,")
        out.append(") -> JSONResponse:")
        out.extend(_svc_block(cls, res_type))
        out.append("    inst = await svc.create(actor=actor, fields=payload.model_dump())")
        out.append("    await session.commit()")
        out.append(f"    return success_response({cls}Response.model_validate(inst))")
        out.append("")

        # update
        out.append(f"@_router_{var}.put(")
        out.append('    "/{entity_id}",')
        out.append(f'    summary="{cls} 更新",')
        out.extend(_dep(a_update, res_type))
        out.append(")")
        out.append(f"async def update_{var}(")
        out.append("    entity_id: int,")
        out.append(f"    payload: {cls}UpdateRequest,")
        out.append("    actor: CurrentActorDep,")
        out.append("    session: DbSessionDep,")
        out.append(") -> JSONResponse:")
        out.extend(_svc_block(cls, res_type))
        out.append("    inst = await svc.update(")
        out.append("        actor=actor,")
        out.append("        entity_id=entity_id,")
        out.append("        fields=payload.model_dump(exclude_unset=True),")
        out.append("    )")
        out.append("    await session.commit()")
        out.append(f"    return success_response({cls}Response.model_validate(inst))")
        out.append("")

        # delete
        out.append(f"@_router_{var}.delete(")
        out.append('    "/{entity_id}",')
        out.append(f'    summary="{cls} 删除",')
        out.extend(_dep(a_delete, res_type))
        out.append(")")
        out.append(f"async def delete_{var}(")
        out.append("    entity_id: int,")
        out.append("    actor: CurrentActorDep,")
        out.append("    session: DbSessionDep,")
        out.append(") -> JSONResponse:")
        out.extend(_svc_block(cls, res_type))
        out.append("    inst = await svc.delete(actor=actor, entity_id=entity_id)")
        out.append("    await session.commit()")
        out.append(f"    return success_response({cls}Response.model_validate(inst))")
        out.append("")
        out.append(f"ROUTER.include_router(_router_{var})")
        out.append("")

    out.append("")
    out.append("__all__ = [")
    out.append('    "ROUTER",')
    out.append("]")
    out.append("")
    return "\n".join(out)


def _humanize(name: str) -> str:
    """蛇形 / 驼峰列名 → 标题样式（英文，结构层诚实标签，不臆造中文）。"""
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ")
    return " ".join(part.capitalize() for part in s.split())


def _has_default(col) -> bool:
    """该列是否"不传也有值"（标量默认 / callable 默认 / 服务端默认）。"""
    d = col.default
    scalar_or_callable = getattr(d, "is_scalar", False) or getattr(d, "is_callable", False)
    return bool(scalar_or_callable or col.server_default is not None)


def _meta_type(col) -> tuple[str, str | None]:
    """前端元数据用的类型串（与 `v31-meta.ts` 的联合类型一致）。"""
    t = col.type
    if col.foreign_keys:
        return "fk", None
    if isinstance(t, SAEnum):
        return "enum", t.enum_class.__name__
    if isinstance(t, Boolean):
        return "boolean", None
    if isinstance(t, DateTime):
        return "datetime", None
    if isinstance(t, Date):
        return "date", None
    if isinstance(t, Numeric):
        return "number", None
    if isinstance(t, (BigInteger, Integer)):
        return "number", None
    if isinstance(t, JSONB):
        return "json", None
    if isinstance(t, INET):
        return "string", None
    return "string", None


def _iter_all_domains() -> list[tuple[str, str, str, str, list[type]]]:
    result: list[tuple[str, str, str, str, list[type]]] = []
    for domain, (module, perm_prefix, audit_prefix, label) in DOMAINS.items():
        models = _iter_models(module)
        models.sort(key=lambda m: m.__name__)
        result.append((domain, perm_prefix, audit_prefix, label, models))
    return result


def gen_frontend_meta_file() -> str:
    """生成 `frontend/src/api/endpoints/v31-meta.ts`（通用 CRUD 元数据）。"""
    lines: list[str] = []
    lines.append("/**")
    lines.append(" * V3.1 四新增域结构层实体的列元数据（VCTN §33，自动生成）。")
    lines.append(" *")
    lines.append(" * 供 `views/crud/CrudResourcePanel.vue` 渲染通用 CRUD 表格与表单。")
    lines.append(" *")
    lines.append(" * ⚠️ 本文件由 `scripts/gen_v31_crud.py` 覆盖生成，不要手改：")
    lines.append(" * 手工修改会在下次重新生成时静默丢失。要改列，改模型或改生成器。")
    lines.append(" */")
    lines.append("")
    lines.append("export type V31ColumnType =")
    lines.append("  | 'string' | 'number' | 'boolean' | 'enum'")
    lines.append("  | 'date' | 'datetime' | 'json' | 'fk'")
    lines.append("")
    lines.append("export interface V31ColumnMeta {")
    lines.append("  key: string")
    lines.append("  label: string")
    lines.append("  type: V31ColumnType")
    lines.append("  required: boolean")
    lines.append("  filterable: boolean")
    lines.append("  formable: boolean")
    lines.append("  maxLength?: number")
    lines.append("  enumType?: string")
    lines.append("}")
    lines.append("")
    lines.append("export interface V31ResourceMeta {")
    lines.append("  resourceType: string")
    lines.append("  kebab: string")
    lines.append("  title: string")
    lines.append("  columns: V31ColumnMeta[]")
    lines.append("}")
    lines.append("")
    lines.append("export const V31_META: Record<string, V31ResourceMeta> = {")
    for _domain, _perm, _audit, _label, models in _iter_all_domains():
        for model in models:
            tablename = model.__tablename__
            kebab = camel_to_kebab(tablename)
            lines.append(f"  {tablename!r}: {{")
            lines.append(f"    resourceType: {tablename!r},")
            lines.append(f"    kebab: {kebab!r},")
            lines.append(f"    title: {model.__name__!r},")
            lines.append("    columns: [")
            for col in model.__table__.columns:
                if col.name in _SENSITIVE:
                    continue
                mtype, enum_type = _meta_type(col)
                formable = col.name not in _NEVER_REQUEST | _SERVER_MANAGED | _SENSITIVE
                required = formable and (not col.nullable) and (not _has_default(col))
                filterable = col.name in _FILTERABLE or bool(col.foreign_keys)
                max_len = getattr(col.type, "length", None)
                lines.append("      {")
                lines.append(f"        key: {col.name!r},")
                lines.append(f"        label: {_humanize(col.name)!r},")
                lines.append(f"        type: {mtype!r},")
                lines.append(f"        required: {str(required).lower()},")
                lines.append(f"        filterable: {str(filterable).lower()},")
                lines.append(f"        formable: {str(formable).lower()},")
                if max_len:
                    lines.append(f"        maxLength: {max_len},")
                if enum_type:
                    lines.append(f"        enumType: {enum_type!r},")
                lines.append("      },")
            lines.append("    ],")
            lines.append("  },")
    lines.append("}")
    lines.append("")
    lines.append("/**")
    lines.append(" * `kebab`（路由段）→ 元数据。")
    lines.append(" *")
    lines.append(" * `GenericCrudView.vue` 被 44 个页面共用，靠路由路径反查自己是哪个资源 ——")
    lines.append(" * 路由是 `/v31/<kebab>`，因此需要这张反查表，而不是让视图去遍历 `V31_META`。")
    lines.append(" *")
    lines.append(" * 值类型是 `V31ResourceMeta | undefined` 而不是 `V31ResourceMeta`：")
    lines.append(" * 工程开了 `noUncheckedIndexedAccess`，索引访问本来就可能是 undefined，")
    lines.append(" * 写成非空类型只会逼调用方在**视图**里加断言，把'查不到'这件事藏起来。")
    lines.append(" */")
    lines.append("export const V31_META_BY_KEBAB: Record<string, V31ResourceMeta | undefined> = {")
    for _domain, _perm, _audit, _label, models in _iter_all_domains():
        for model in models:
            tablename = model.__tablename__
            kebab = camel_to_kebab(tablename)
            lines.append(f"  {kebab!r}: V31_META[{tablename!r}],")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def gen_frontend_pages_file() -> str:
    """生成 `frontend/src/api/endpoints/v31-pages.ts`（供 `tests/helpers/fixtures.ts` 引用）。"""
    lines: list[str] = []
    lines.append("/**")
    lines.append(" * V3.1 四新增域页面夹具片段（VCTN §33，自动生成）。")
    lines.append(" *")
    lines.append(
        " * 导出 `V31_PAGE_SPECS` 供 `tests/helpers/fixtures.ts` 摊平进 `FULL_PAGE_SPECS`。"
    )
    lines.append(" * 与后端 `scripts/_v31_seed.py` 出自同一次生成，因此两边不会漂移。")
    lines.append(" *")
    lines.append(" * ⚠️ 本文件由 `scripts/gen_v31_crud.py` 覆盖生成，不要手改。")
    lines.append(" */")
    lines.append("")
    lines.append("import type { PermissionPageItem } from '@/types'")
    lines.append("")
    lines.append("export const V31_PAGE_SPECS: PermissionPageItem[] = [")
    order = 1000
    for _domain, _perm, _audit, _label, models in _iter_all_domains():
        for model in models:
            tablename = model.__tablename__
            kebab = camel_to_kebab(tablename)
            code = f"v31:{kebab}:page"
            lines.append("  {")
            lines.append(f"    id: 'v31-{tablename}',")
            lines.append(f"    code: {code!r},")
            lines.append(f"    name: {model.__name__!r},")
            lines.append(f"    route_path: '/v31/{kebab}',")
            lines.append("    component_path: '/crud/generic',")
            lines.append(f"    sort_order: {order},")
            lines.append("  },")
            order += 1
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_seed_fragment_file() -> str:
    """生成 `scripts/_v31_seed.py`：V3.1 的 PAGES / MENUS / MENU_PAGES / BUTTONS。

    与 `seed_data.py` 同口径（详见其模块文档）。`APIS` 不在此生成 —— V3.1 的
    权限是**域级单一位**（`BIZ_USER_MANAGE` …），若按实体逐条登记会与 `APIS`
    编码唯一性约束冲突；而 SUPER_ADMIN 在 `has_api_permission` 中集中 bypass，
    不需要出现在 `ROLE_APIS` 台账里。
    """
    pages: list[tuple[str, str, str, str, int]] = []
    menus: list[tuple[str, str, str | None, str | None, int]] = []
    menu_pages: list[tuple[str, str]] = []
    buttons: list[tuple[str, str, str]] = []
    page_order = 1000
    menu_order = 1010
    for _domain, _perm, _audit, label, models in _iter_all_domains():
        # 分组菜单编码必须与实体菜单编码**不可能撞车**：`tool` 域下的 `Tool`
        # 实体的 kebab 恰好也是 `tool`，若分组用 `v31:{domain}` 就会产生
        # 重复 MENUS 编码 + 自引用父子环（`v31:tool` 的父是 `v31:tool`）。
        domain_menu_code = f"v31:domain:{_domain}"
        menus.append((domain_menu_code, label, "v31:root", None, menu_order))
        menu_order += 10
        for index, model in enumerate(models, start=1):
            tablename = model.__tablename__
            kebab = camel_to_kebab(tablename)
            page_code = f"v31:{kebab}:page"
            pages.append((page_code, model.__name__, f"/v31/{kebab}", "crud/generic", page_order))
            page_order += 1
            menu_code = f"v31:{kebab}"
            # 兄弟菜单用递增 order：全部写同一个值会让侧边栏顺序变成
            # "看实现心情"（等于没有排序）。
            menus.append((menu_code, model.__name__, domain_menu_code, None, index * 10))
            menu_pages.append((menu_code, page_code))
            buttons.append((f"v31:{kebab}:create", f"新增{model.__name__}", page_code))
            buttons.append((f"v31:{kebab}:update", f"编辑{model.__name__}", page_code))
            buttons.append((f"v31:{kebab}:delete", f"删除{model.__name__}", page_code))

    out: list[str] = []
    out.append('"""V3.1 四新增域权限资源片段（VCTN §33，自动生成）。')
    out.append("")
    out.append("由 `scripts/gen_v31_crud.py` 生成；`seed_data.py` 在本文件之后 extend 主清单。")
    out.append('"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append("# (code, name, route_path, component_path, sort_order)")
    out.append("V31_PAGES: list[tuple[str, str, str, str, int]] = [")
    for p in pages:
        out.append(f"    {p!r},")
    out.append("]")
    out.append("")
    out.append("# (code, name, parent_code, icon, order)")
    out.append("V31_MENUS: list[tuple[str, str, str | None, str | None, int]] = [")
    out.append("    ('v31:root', 'V3.1 管理', None, 'setting', 900),")
    for m in menus:
        out.append(f"    {m!r},")
    out.append("]")
    out.append("")
    out.append("# (menu_code, page_code)")
    out.append("V31_MENU_PAGES: list[tuple[str, str]] = [")
    for mp in menu_pages:
        out.append(f"    {mp!r},")
    out.append("]")
    out.append("")
    out.append("# (code, name, page_code)")
    out.append("V31_BUTTONS: list[tuple[str, str, str]] = [")
    for b in buttons:
        out.append(f"    {b!r},")
    out.append("]")
    out.append("")
    out.append("__all__ = ['V31_PAGES', 'V31_MENUS', 'V31_MENU_PAGES', 'V31_BUTTONS']")
    out.append("")
    return "\n".join(out)


def _run_ruff(*args: str) -> None:
    """在生成产物上跑 ruff（`check --fix` 会自动修 import 排序 / `__all__` 等）。

    为什么生成器必须自己格式化
    --------------------------
    项目门禁是 `ruff check .` + `ruff format --check .`（`scripts/dev.ps1`），
    它**覆盖 `scripts/` 与 `app/`**。如果生成器只拼字符串而不跑 formatter，
    那么每次重新生成都会把"已格式化"的产物改回未格式化状态 ——
    表现是"改了模型 → 重跑生成器 → 门禁突然红一片"，而红的原因与改动无关。
    把格式化收进 `main()`，保证"生成器跑完 = 门禁干净"。

    ruff 不可用时只告警不失败：生成器的首要产出是文件本身，格式化是收尾步骤
    （此时 `dev.ps1 verify` 仍会拦住未格式化的产物）。
    """
    for command in (("check", "--fix", *args), ("format", *args)):
        result = subprocess.run(  # noqa: S603 - 参数全部来自本文件的常量，无外部输入
            [sys.executable, "-m", "ruff", *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and result.stderr:
            print(f"[warn] ruff {' '.join(command)}: {result.stderr.strip()}")


def main() -> None:
    generated: list[str] = []
    for domain, (module, perm_prefix, audit_prefix, _label) in DOMAINS.items():
        models = _iter_models(module)
        models.sort(key=lambda m: m.__name__)
        schema_path = ROOT / "app" / "schemas" / f"v31_{domain}.py"
        endpoint_path = ROOT / "app" / "api" / "v1" / "endpoints" / f"v31_{domain}.py"
        schema_path.write_text(gen_schema_file(domain, models), encoding="utf-8")
        endpoint_path.write_text(
            gen_endpoint_file(domain, models, perm_prefix, audit_prefix), encoding="utf-8"
        )
        generated.extend([str(schema_path), str(endpoint_path)])
        print(f"[{domain}] {len(models)} models -> {schema_path.name}, {endpoint_path.name}")

    meta_path = ROOT / "frontend" / "src" / "api" / "endpoints" / "v31-meta.ts"
    pages_path = ROOT / "frontend" / "src" / "api" / "endpoints" / "v31-pages.ts"
    seed_path = ROOT / "scripts" / "_v31_seed.py"
    meta_path.write_text(gen_frontend_meta_file(), encoding="utf-8")
    pages_path.write_text(gen_frontend_pages_file(), encoding="utf-8")
    seed_path.write_text(gen_seed_fragment_file(), encoding="utf-8")
    generated.append(str(seed_path))
    print(f"[frontend] meta -> {meta_path.name}, pages -> {pages_path.name}")
    print(f"[seed] fragment -> {seed_path.name}")

    _run_ruff(*generated)
    print("[ruff] 生成产物已格式化（check --fix + format）")


if __name__ == "__main__":
    main()
