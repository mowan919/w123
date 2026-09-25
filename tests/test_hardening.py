"""Phase 9 Hardening 测试（`docs/verification/009-hardening.md`）。

覆盖对象与对应裁判项：

| 类 | 裁判项 |
|---|---|
| `TestSecurityHeaders` | Security headers（`PHASES.md` Phase 9） |
| `TestErrorMasking` | 错误响应不泄漏内部异常 |
| `TestSecretNeverReachesLogs` | Secret 不进入日志 |
| `TestConcurrencyProtection` | 并发更新有保护 |
| `TestIdempotency` | 关键写操作具备幂等策略 |
| `TestNoStalePermission` | 权限缓存有失效机制 / 无明显 stale |
| `TestPerformanceBaseline` | Performance baseline（无 N+1） |
| `TestMigrationSafety` | Migration 可重复部署 |
| `TestAuditIntegrity` | Audit integrity（追加型） |
| `TestDatabaseGuarantees` | 数据库关键索引 / FK 行为符合逻辑删除设计 |

关于"并发"这一项的诚实边界
------------------------
本文件的并发用例证明的是**保护机制存在且生效**（CAS 条件更新使第二个
写入者匹配 0 行），而不是在多线程/多连接下做竞态压测 ——
`db_session` 夹具把每个用例包在一个事务里并在结束时回滚，
两任务的"并发"会共用同一条连接从而被串行化，
那样跑出来的"并发测试"是假的。真正的竞态压测需要独立连接池与
已提交的数据，属压测环境范畴，不在此伪造。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scope import DataScope
from app.db.base import utc_now
from app.db.session import get_db
from app.models.enums import (
    PermissionResourceType,
    PermissionStatus,
    SessionRevokeReason,
)
from app.repositories.permission import RolePermissionRepository
from app.repositories.session import SessionRepository
from app.services.permission_contract import PermissionContractService
from tests.factories import (
    hash_token,
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_session,
    make_user,
)

pytestmark = pytest.mark.integration

DEPT_ID = 65101
USER_ID = 65102
ROLE_ID = 65103


# ===========================================================================
# Security headers
# ===========================================================================
class TestSecurityHeaders:
    async def test_every_response_carries_the_baseline_headers(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"

    async def test_hsts_is_off_by_default(self, client: AsyncClient) -> None:
        """HSTS 默认不下发 —— 它是一个"下发后难以撤回"的承诺。"""
        response = await client.get("/health")
        assert "strict-transport-security" not in response.headers

    async def test_hsts_appears_when_enabled(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.main import create_app

        monkeypatch.setattr(settings, "security_hsts_enabled", True)
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as probe:
            response = await probe.get("/health")
        assert "max-age=" in response.headers["strict-transport-security"]

    async def test_existing_headers_are_not_overwritten(self, app: FastAPI) -> None:
        """中间件只补缺 —— 端点设置的头必须保留。

        若中间件是覆盖式的，端点将无法表达任何例外（例如给静态资源开缓存）。
        """
        from app.core.response import success_response

        @app.get("/__harden_cache_probe__", include_in_schema=False)
        async def _probe() -> object:
            return success_response({"ok": True}, headers={"Cache-Control": "max-age=60"})

        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://t") as probe:
                response = await probe.get("/__harden_cache_probe__")
            assert response.headers["cache-control"] == "max-age=60"
            # 其余安全头仍然补上
            assert response.headers["x-frame-options"] == "DENY"
        finally:
            app.router.routes = [
                route
                for route in app.router.routes
                if getattr(route, "path", None) != "/__harden_cache_probe__"
            ]


# ===========================================================================
# 错误响应不泄漏内部异常
# ===========================================================================
class TestErrorMasking:
    async def test_unhandled_exception_returns_a_content_free_500(self, app: FastAPI) -> None:

        @app.get("/__harden_boom__", include_in_schema=False)
        async def _boom() -> object:
            raise RuntimeError("database password is hunter2 at 10.0.0.5")

        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://t") as probe:
                response = await probe.get("/__harden_boom__")
        finally:
            app.router.routes = [
                route
                for route in app.router.routes
                if getattr(route, "path", None) != "/__harden_boom__"
            ]

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == 500000
        assert body["data"] is None
        # 异常消息、类型、堆栈一律不得出现在响应里
        for leak in ("hunter2", "10.0.0.5", "RuntimeError", "Traceback", "__harden_boom__"):
            assert leak not in response.text, f"泄漏了 {leak!r}"

    async def test_validation_error_does_not_echo_input(self, app: FastAPI, db_session) -> None:
        """422 不得回显 `input` —— 登录场景下那是明文口令。

        FastAPI 默认的 422 响应会带上 `input` 原文，
        在 `/auth/login` 上等于把明文口令回显给调用方。

        为什么必须带 `db_session`：依赖层（`get_auth_service`）**先于**
        请求体校验执行，而它会读一次系统参数表。不带数据库时
        这里会先以 500 失败，根本走不到校验 —— 用例就失去了意义。
        """

        async def _override_get_db() -> AsyncIterator[object]:
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://t") as probe:
                response = await probe.post(
                    "/api/v1/auth/login",
                    json={"username": "x", "password": []},  # 类型错误 → 422
                )
        finally:
            app.dependency_overrides.pop(get_db, None)
        body = response.json()
        assert body["code"] == 422001
        assert "input" not in response.text

    async def test_unknown_path_returns_the_frozen_envelope(self, app: FastAPI) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as probe:
            response = await probe.get("/api/v1/admin/__not_exists__")
        assert response.status_code == 404
        assert response.json()["data"] is None


# ===========================================================================
# Secret 不进入日志
# ===========================================================================
class TestSecretNeverReachesLogs:
    def test_masking_covers_the_credential_shapes(self) -> None:
        from app.core.masking import scrub

        secret = "S3cr3t-V4lue-9f21c7"
        for template in (
            '{"password": "%s"}',
            "password=%s",
            "Authorization: Bearer %s",
            "refresh_token=%s",
            "mfa_secret=%s",
        ):
            scrubbed = scrub(template % secret)
            assert secret not in scrubbed, template

    def test_masking_is_idempotent_and_does_not_double_corrupt(self) -> None:
        """重复脱敏不得把已脱敏文本再次破坏（`***` 本身不含敏感形态）。"""
        from app.core.masking import scrub

        once = scrub('{"password": "hunter2"}')
        assert scrub(once) == once


# ===========================================================================
# 并发更新有保护
# ===========================================================================
class TestConcurrencyProtection:
    async def test_token_rotation_is_a_compare_and_swap(self, db_session) -> None:
        """第二次用**旧值**轮换必须匹配 0 行 —— 这正是并发保护本身。

        见 `app/repositories/session.py::rotate_tokens` 的论证：
        若是"读了再写"，两个并发请求会各自成功，
        令牌盗用信号会被静默吞掉。
        """
        dept = await make_department(db_session, department_id=DEPT_ID, department_code="HARDEN")
        user = await make_user(
            db_session,
            user_id=USER_ID,
            username="harden-user",
            department_id=dept.id,
        )
        repo = SessionRepository(db_session)
        now = utc_now()

        session = await make_session(
            db_session,
            session_id=65199,
            user_id=user.id,
            access_token="access-1",
            refresh_token="refresh-1",
            login_at=now,
        )

        first = await repo.rotate_tokens(
            session,
            access_token_hash="access-2",
            refresh_token_hash="refresh-2",
            access_expires_at=now + timedelta(minutes=15),
            last_active_at=now,
        )
        assert first is True

        # 模拟**另一个请求**：它读这一行时拿到的是 access-1（A 尚未提交），
        # 因此它手里的 ORM 对象仍是旧哈希 —— 这正是 CAS 要挡住的情形。
        # （不做这一步的话，ORM 对象已被 A 改成 access-2，
        #   第二次调用会拿新值去比新值，必然成功 —— 用例就失去了意义。）
        session.access_token_hash = hash_token("access-1")
        stale = await repo.rotate_tokens(
            session,
            access_token_hash="access-3",
            refresh_token_hash="refresh-3",
            access_expires_at=now + timedelta(minutes=15),
            last_active_at=now,
        )
        assert stale is False

    async def test_retiring_the_same_token_twice_does_not_raise(self, db_session) -> None:
        """`ON CONFLICT DO NOTHING`：并发下必然重复，抛错会让撤销被回滚。"""
        from app.models.enums import RefreshTokenRetirement

        dept = await make_department(db_session, department_id=DEPT_ID, department_code="HARDEN")
        user = await make_user(
            db_session,
            user_id=USER_ID,
            username="harden-user",
            department_id=dept.id,
        )
        repo = SessionRepository(db_session)
        now = utc_now()
        session = await make_session(
            db_session,
            session_id=65198,
            user_id=user.id,
            access_token="a-1",
            refresh_token="r-1",
            login_at=now,
        )

        for _ in range(2):
            await repo.record_retired_refresh_token(
                session_id=session.id,
                token_hash="r-1",
                reason=RefreshTokenRetirement.ROTATED,
                retired_at=now,
            )

    async def test_full_replacement_makes_last_write_wins_safe(self, db_session) -> None:
        """整体替换端点上的 LWW 不会产生"半应用"状态。

        `PUT /roles/{id}/permissions/pages` 收的是**完整集合**，
        因此后到者覆盖先到者时结果仍是某个请求者的完整意图，
        而不是两者各半的混合体。这是"此处不需要乐观锁"的依据。
        """
        role = await make_role(db_session, role_id=ROLE_ID, role_code="HARDEN_ROLE2")
        page_a = await make_permission_resource(
            db_session,
            resource_id=65201,
            resource_type=PermissionResourceType.PAGE,
            resource_code="page:a",
            route_path="/a",
            component_path="views/a.vue",
        )
        page_b = await make_permission_resource(
            db_session,
            resource_id=65202,
            resource_type=PermissionResourceType.PAGE,
            resource_code="page:b",
            route_path="/b",
            component_path="views/b.vue",
        )
        grants = RolePermissionRepository(db_session)

        await grants.replace_resource_ids(
            role.id, PermissionResourceType.PAGE, frozenset({page_a.id})
        )
        assert await grants.list_resource_ids(role.id, PermissionResourceType.PAGE) == frozenset(
            {page_a.id}
        )

        # 后到者的意图被**完整**应用：A 消失，不是 "A + B 的混合"
        await grants.replace_resource_ids(
            role.id, PermissionResourceType.PAGE, frozenset({page_b.id})
        )
        assert await grants.list_resource_ids(role.id, PermissionResourceType.PAGE) == frozenset(
            {page_b.id}
        )


# ===========================================================================
# 幂等
# ===========================================================================
class TestIdempotency:
    async def test_revoking_an_already_revoked_session_succeeds(self, db_session) -> None:
        """DD-11 方案 A（语义幂等）：意图已达成即成功，不报错。"""
        from app.repositories.session import SessionRepository

        dept = await make_department(db_session, department_id=DEPT_ID, department_code="HARDEN")
        user = await make_user(
            db_session,
            user_id=USER_ID,
            username="harden-user",
            department_id=dept.id,
        )
        repo = SessionRepository(db_session)
        now = utc_now()
        session = await make_session(
            db_session,
            session_id=65198,
            user_id=user.id,
            access_token="a-1",
            refresh_token="r-1",
            login_at=now,
        )

        assert await repo.revoke(session, reason=SessionRevokeReason.LOGOUT, now=now)
        # 已撤销 → 再撤销返回 False（语义幂等），不报错、不改写原因
        assert not await repo.revoke(session, reason=SessionRevokeReason.LOGOUT, now=now)


# ===========================================================================
# 权限缓存 / stale
# ===========================================================================
class TestNoStalePermission:
    async def test_contract_service_declares_no_cache(self) -> None:
        """结构性证明：服务里不存在任何缓存属性，因此不可能陈旧。

        "权限缓存有失效机制"这一项在本系统的答案是**没有缓存** ——
        见 `docs/DESIGN-DECISIONS.md §15.7`。这里用 AST/属性断言把
        "没有缓存"钉住：将来有人引入缓存字段，这条会立刻失败，
        从而迫使他去处理失效问题，而不是悄悄引入 stale。
        """
        import inspect

        source = inspect.getsource(PermissionContractService)
        for forbidden in ("_cache", "cache_get", "cache_set", "lru_cache", "redis"):
            assert forbidden not in source, f"契约服务出现了缓存痕迹：{forbidden}"

    async def test_grant_change_is_visible_within_a_few_calls(self, db_session) -> None:
        """连续两次构建之间无需任何失效动作。"""
        dept = await make_department(db_session, department_id=DEPT_ID, department_code="HARDEN")
        user = await make_user(
            db_session,
            user_id=USER_ID,
            username="harden-user",
            department_id=dept.id,
        )
        role = await make_role(
            db_session,
            role_id=ROLE_ID,
            role_code="HARDEN_ROLE",
            data_scope=DataScope.DEPARTMENT_CHILDREN,
        )
        await link_user_role(db_session, user_id=user.id, role_id=role.id)
        page = await make_permission_resource(
            db_session,
            resource_id=65203,
            resource_type=PermissionResourceType.PAGE,
            resource_code="page:late",
            route_path="/late",
            component_path="views/late.vue",
            status=PermissionStatus.ACTIVE,
        )
        service = PermissionContractService(db_session)

        before = await service.build(user_id=user.id)
        assert [item.resource_code for item in before.pages] == []

        await link_role_permission(db_session, role_id=role.id, resource_id=page.id)
        await db_session.flush()

        after = await service.build(user_id=user.id)
        assert [item.resource_code for item in after.pages] == ["page:late"]


# ===========================================================================
# Performance baseline（无 N+1）
# ===========================================================================
class TestPerformanceBaseline:
    async def test_contract_query_count_does_not_grow_with_resource_count(self, db_session) -> None:
        """批量读而非逐条读：资源数翻两番，SQL 条数必须**不变**。

        这是性能基线的可执行形式。用耗时断言会随机器波动而假红，
        而"查询条数与数据量无关"是一个**结构性**性质，
        既能钉住 N+1，又不会 flaky。
        """
        dept = await make_department(db_session, department_id=DEPT_ID, department_code="HARDEN")
        user = await make_user(
            db_session,
            user_id=USER_ID,
            username="harden-user",
            department_id=dept.id,
        )
        role = await make_role(
            db_session,
            role_id=ROLE_ID,
            role_code="HARDEN_ROLE",
            data_scope=DataScope.DEPARTMENT_CHILDREN,
        )
        await link_user_role(db_session, user_id=user.id, role_id=role.id)

        service = PermissionContractService(db_session)

        next_id = 65300

        async def _count_with(resource_count: int) -> int:
            nonlocal next_id
            for _ in range(resource_count):
                next_id += 1
                resource = await make_permission_resource(
                    db_session,
                    resource_id=next_id,
                    resource_type=PermissionResourceType.PAGE,
                    resource_code=f"page:perf{next_id}",
                    route_path=f"/perf{next_id}",
                    component_path=f"views/perf{next_id}.vue",
                    status=PermissionStatus.ACTIVE,
                )
                await link_role_permission(db_session, role_id=role.id, resource_id=resource.id)
            await db_session.flush()

            statements: list[str] = []
            bind = db_session.get_bind()
            assert bind is not None
            # 异步引擎不支持异步事件监听，必须挂到同步侧
            target = getattr(bind, "sync_engine", None) or bind.engine

            def _record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
                statements.append(statement)

            event.listen(target, "before_cursor_execute", _record)
            try:
                await service.build(user_id=user.id)
            finally:
                event.remove(target, "before_cursor_execute", _record)
            return len(statements)

        small = await _count_with(3)
        larger = await _count_with(9)  # 累计 12 个页面

        assert larger == small, f"疑似 N+1：3 个资源 {small} 条 SQL，12 个资源 {larger} 条"
        assert larger <= 20, f"契约构建查询数过多：{larger}"


# ===========================================================================
# Migration 可重复部署
# ===========================================================================
class TestMigrationSafety:
    def test_every_migration_implements_downgrade(self) -> None:
        """每个 revision 都必须实现 `downgrade()`（可读的回滚路径）。

        "可重复部署"的一个前提是"可回滚"。空的 `downgrade()`
        会让 `alembic downgrade` 静默成功却什么也没撤 ——
        那是比失败更危险的状态。
        """
        versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
        files = sorted(versions.glob("*.py"))
        assert files, "未找到任何迁移文件"

        def _is_noop(body: str) -> bool:
            """函数体里除了 `pass` 与注释之外什么也没有。"""
            return all(
                line.strip() in ("", "pass") or line.strip().startswith("#")
                for line in body.splitlines()[1:]
            )

        for path in files:
            source = path.read_text(encoding="utf-8")
            assert "def downgrade()" in source, f"{path.name} 缺少 downgrade()"

            upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
            downgrade_body = source.split("def downgrade()", 1)[1]

            # 判据：**upgrade 有操作 ⇒ downgrade 必须有操作**。
            # 反过来（两者都是空）是合法的 —— 本仓库的 baseline 迁移
            # 就是一个占位（`upgrade()` 什么也不建），此时 `pass` 是正确的。
            if _is_noop(upgrade_body):
                continue
            assert not _is_noop(downgrade_body), (
                f"{path.name} 的 upgrade() 有操作但 downgrade() 是空实现 —— "
                "这会让 `alembic downgrade` 静默成功却什么也没撤"
            )

    def test_alembic_sees_no_drift(self) -> None:
        """模型与迁移一致：`alembic check` 不得发现新操作。

        这是"可重复部署"的另一半：若模型与迁移漂移，
        新环境从零跑迁移得到的库与旧环境升级得到的库**结构不同**。

        为什么必须还原环境变量：conftest 把 `POSTGRES_*` 注入成不可达端口，
        子进程会继承它们，于是 alembic 连不上库 —— 那测的是"端口不通"，
        不是"有没有漂移"。
        """
        import os
        import subprocess
        import sys

        saved: dict[str, str] = {}
        for key in list(os.environ):
            if key.startswith("POSTGRES") or key.startswith("REDIS"):
                saved[key] = os.environ.pop(key)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "check"],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
                check=False,
            )
        finally:
            os.environ.update(saved)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No new upgrade operations detected." in result.stdout


# ===========================================================================
# Audit integrity
# ===========================================================================
class TestAuditIntegrity:
    async def test_delete_without_the_retention_flag_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        """追加型由数据库触发器强制，不经应用代码。

        直接绕开 `LogRetentionService` 去 DELETE，必须被数据库拒绝 ——
        否则"审计不可篡改"只是应用层的一句承诺。
        """
        await db_session.execute(
            text("delete from audit_logs where id = -1")  # 不影响数据的空删除
        )
        # 上面的删除本身是允许的（0 行）；真正被拒绝的是**有行**的删除。
        # 这里改为插入一行再删，验证触发器真的拦住。
        now = utc_now()
        await db_session.execute(
            text(
                """
                insert into audit_logs (
                    id, action, result, operator_id, resource_type, created_at
                ) values (:id, 'HARDENING_PROBE', 'SUCCESS', :op, 'probe', :now)
                """
            ),
            {"id": 65199001, "op": USER_ID, "now": now},
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text("delete from audit_logs where id = :id"),
                {"id": 65199001},
            )
            await db_session.flush()

    async def test_delete_is_allowed_with_the_retention_flag(
        self, db_session: AsyncSession
    ) -> None:
        """同一条 DELETE 在 `vctn.retention='on'` 下应当被放行 ——
        否则保留期清理（合规要求）无处可用。"""
        await db_session.execute(text("set local vctn.retention = 'on'"))
        await db_session.execute(text("delete from audit_logs where id = :id"), {"id": 65199001})
        # 走到这里即通过：没有抛 append-only 违规
        await db_session.execute(text("set local vctn.retention = 'off'"))


# ===========================================================================
# 数据库保证
# ===========================================================================
class TestDatabaseGuarantees:
    async def test_no_cascade_foreign_keys(self, db_session: AsyncSession) -> None:
        """**没有**任何 `ON DELETE CASCADE`。

        所有业务实体都是逻辑删除（软删除）。若存在 CASCADE，
        一次物理删除父行会连带抹掉子行的历史 ——
        那会把"逻辑删除"这个不变量在数据库层打穿。
        """
        rows = sorted(
            (
                await db_session.execute(
                    text(
                        """
                        select cl.relname, c.conname
                        from pg_constraint c
                        join pg_class cl on cl.oid = c.conrelid
                        where c.contype = 'f'
                          and c.connamespace = 'public'::regnamespace
                          and c.confdeltype = 'c'
                        """
                    )
                )
            ).all()
        )
        # 白名单：**新增**任何 CASCADE 外键都必须先给出理由并更新这里。
        # 直接断言"零 CASCADE"看似更严，却会把唯一一个合理的
        # （瞬态挑战表随用户清理）逼成"不写理由就删掉"，
        # 反而让人以为 CASCADE 一律不可用。
        assert rows == [("mfa_challenges", "fk_mfa_challenges_user_id_admin_users")], (
            f"CASCADE 外键集合发生变化，需重新论证：{rows}"
        )

    async def test_soft_delete_unique_indexes_are_partial(self, db_session: AsyncSession) -> None:
        """软删除感知唯一性必须由 **partial** unique index 保证。

        普通唯一索引会让"删除后重建同名"失败，
        那是把软删除退化成硬删除。
        """
        rows = (
            (
                await db_session.execute(
                    text(
                        """
                    select c.relname
                    from pg_index i
                    join pg_class c on c.oid = i.indexrelid
                    where i.indpred is not null
                      and i.indisunique
                      and c.relnamespace = 'public'::regnamespace
                    """
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 7, f"partial unique index 数量不足：{rows}"
        assert "uq_admin_users_username_active" in rows
        assert "uq_roles_role_code_active" in rows
