"""配置与日志基础设施测试。

Spec 13 §2：敏感配置不得硬编码，且不得出现在日志中。
Spec 00 §6：时间统一 UTC。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import JsonFormatter

pytestmark = pytest.mark.unit


class TestSettings:
    def test_database_url_safe_masks_password(self) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            postgres_user="vctn",
            postgres_password="sup3r-s3cret",  # type: ignore[arg-type]
            postgres_host="db.internal",
            postgres_port=5432,
            postgres_db="vctn",
        )

        assert "sup3r-s3cret" not in settings.database_url_safe
        assert "***" in settings.database_url_safe
        assert "db.internal" in settings.database_url_safe
        # 真实 DSN 仍然可用（供引擎使用），仅审计输出被脱敏
        assert "sup3r-s3cret" in settings.database_url

    def test_redis_url_safe_masks_password(self) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            redis_password="redis-s3cret",  # type: ignore[arg-type]
        )

        assert "redis-s3cret" not in settings.redis_url_safe
        assert "redis-s3cret" in settings.redis_url

    def test_password_with_special_chars_is_encoded(self) -> None:
        """DSN 中的特殊字符必须转义，否则连接串会被截断。"""
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            postgres_password="p@ss word/with:special",  # type: ignore[arg-type]
        )

        assert "p%40ss+word%2Fwith%3Aspecial" in settings.database_url

    def test_api_prefix_must_start_with_slash(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, api_v1_prefix="api/v1/admin")  # type: ignore[call-arg]

    def test_api_prefix_trailing_slash_is_normalized(self) -> None:
        settings = Settings(_env_file=None, api_v1_prefix="/api/v1/admin/")  # type: ignore[call-arg]
        assert settings.api_v1_prefix == "/api/v1/admin"

    def test_production_requires_secrets(self) -> None:
        """安全默认值：prod 环境缺少密钥时 fail-closed。"""
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                app_env="prod",
                postgres_password="",  # type: ignore[arg-type]
                redis_password="",  # type: ignore[arg-type]
                signing_secret="",  # type: ignore[arg-type]
                encryption_key="",  # type: ignore[arg-type]
            )

    def test_local_environment_allows_empty_secrets(self) -> None:
        settings = Settings(_env_file=None, app_env="local")  # type: ignore[call-arg]
        assert settings.app_env == "local"
        assert settings.is_production is False


class TestJsonFormatter:
    def test_log_record_carries_context_and_is_masked(self, capsys) -> None:
        import json
        import logging

        from app.core.context import trace_context

        logger = logging.getLogger("vctn.test.formatter")
        logger.handlers = []
        logger.propagate = False

        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with trace_context("trace-abc", "request-def"):
            logger.info("user login", extra={"password": "plaintext", "phone": "13812341234"})

        payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])

        assert payload["trace_id"] == "trace-abc"
        assert payload["request_id"] == "request-def"
        assert payload["message"] == "user login"
        assert payload["level"] == "INFO"
        assert payload["timestamp"].endswith("+00:00")  # Spec 00 §6：UTC
        # Spec 00 §8 / 06 §4：password 绝不记录，phone 部分脱敏
        assert payload["password"] == "<redacted>"
        assert payload["phone"] == "138****1234"
