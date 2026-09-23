"""健康检查测试。

Spec 13 §4 Health：application health / database health / redis health。

说明：Phase 1 环境不保证存在可用的 PostgreSQL / Redis，
因此"依赖可用"分支通过 monkeypatch 显式模拟，"依赖不可用"分支使用真实探测
（conftest 将端口指向不可达地址，连接被立即拒绝，测试不会长时间阻塞）。
"""

from __future__ import annotations

import pytest

from app.api.v1.endpoints import health as health_module
from app.core.error_codes import ErrorCode

pytestmark = pytest.mark.unit


async def _available() -> None:
    """模拟依赖可用。"""


async def _unavailable() -> None:
    raise ConnectionError("simulated dependency outage")


class TestLiveness:
    async def test_health_ok(self, client, api_prefix: str) -> None:
        response = await client.get(f"{api_prefix}/health")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ok"
        assert body["data"]["env"] == "test"

    async def test_root_alias_ok(self, client) -> None:
        """根路径 liveness 别名（供容器探针使用），不进入 OpenAPI。"""
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json()["code"] == 0

        schema = (await client.get("/openapi.json")).json()
        assert "/health" not in schema["paths"]
        assert "/api/v1/admin/health" in schema["paths"]


class TestReadiness:
    async def test_ready_when_all_dependencies_up(self, client, api_prefix, monkeypatch) -> None:
        monkeypatch.setattr(health_module, "check_database", _available)
        monkeypatch.setattr(health_module, "check_redis", _available)

        response = await client.get(f"{api_prefix}/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ready"
        assert body["data"]["checks"]["database"]["status"] == "up"
        assert body["data"]["checks"]["redis"]["status"] == "up"

    async def test_not_ready_when_dependencies_down(self, client, api_prefix, monkeypatch) -> None:
        monkeypatch.setattr(health_module, "check_database", _unavailable)
        monkeypatch.setattr(health_module, "check_redis", _unavailable)

        response = await client.get(f"{api_prefix}/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["code"] == int(ErrorCode.SERVICE_UNAVAILABLE)
        # Spec 08 §2：失败响应 data 必须为 null
        assert body["data"] is None
        assert "database" in body["message"]
        assert "redis" in body["message"]

    async def test_not_ready_reports_only_failing_component(
        self, client, api_prefix, monkeypatch
    ) -> None:
        monkeypatch.setattr(health_module, "check_database", _available)
        monkeypatch.setattr(health_module, "check_redis", _unavailable)

        body = (await client.get(f"{api_prefix}/health/ready")).json()

        assert "redis" in body["message"]
        assert "database" not in body["message"]

    async def test_readiness_against_real_unreachable_dependencies(
        self, client, api_prefix
    ) -> None:
        """真实探测路径：conftest 指向不可达端口，必须优雅降级为 503。"""
        response = await client.get(f"{api_prefix}/health/ready")

        assert response.status_code == 503
        assert response.json()["data"] is None


class TestComponentHealth:
    async def test_database_up(self, client, api_prefix, monkeypatch) -> None:
        monkeypatch.setattr(health_module, "check_database", _available)

        body = (await client.get(f"{api_prefix}/health/db")).json()

        assert body["code"] == 0
        assert body["data"] == {"component": "database", "status": "up"}

    async def test_database_down_does_not_leak_details(
        self, client, api_prefix, monkeypatch
    ) -> None:
        async def _exploding() -> None:
            raise ConnectionError("postgresql://vctn:secretpw@10.0.0.9:5432/vctn refused")

        monkeypatch.setattr(health_module, "check_database", _exploding)

        response = await client.get(f"{api_prefix}/health/db")

        assert response.status_code == 503
        assert response.json()["data"] is None
        assert "secretpw" not in response.text
        assert "10.0.0.9" not in response.text

    async def test_redis_down(self, client, api_prefix, monkeypatch) -> None:
        monkeypatch.setattr(health_module, "check_redis", _unavailable)

        response = await client.get(f"{api_prefix}/health/redis")

        assert response.status_code == 503
        assert response.json()["code"] == int(ErrorCode.SERVICE_UNAVAILABLE)
