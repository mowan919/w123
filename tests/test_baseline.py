"""Phase 1 基础设施单元测试。

覆盖对象：
- 统一 API Response Envelope（Spec 08 §2 冻结格式）
- 全局异常处理（Spec 10 §9 不泄漏内部信息）
- Trace / Request ID（Spec 06 §3）
- 敏感信息脱敏（Spec 00 §8 / 06 §4）
- Snowflake ID（Spec 00 §6 / 07 §2 / 12 §1）
"""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel

from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER
from app.core.error_codes import ErrorCode
from app.core.masking import mask_email, mask_phone, mask_token, scrub
from app.core.snowflake import (
    MAX_BIGINT,
    ClockBackwardError,
    InvalidWorkerConfigError,
    SnowflakeGenerator,
)
from app.schemas.types import SnowflakeId

pytestmark = pytest.mark.unit

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ===========================================================================
# Spec 08 §2 —— Unified API Response Envelope
# ===========================================================================
class TestResponseEnvelope:
    async def test_liveness_envelope_shape(self, client, api_prefix: str) -> None:
        """成功响应：code=0 / message=success / data 为对象。"""
        response = await client.get(f"{api_prefix}/health")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert isinstance(body["data"], dict)
        assert body["data"]["status"] == "ok"

    async def test_error_envelope_has_null_data(self, client) -> None:
        """失败响应：data 必须为 null（冻结格式）。"""
        response = await client.get("/api/v1/admin/__not_exists__")

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == int(ErrorCode.NOT_FOUND)
        assert body["data"] is None

    async def test_permission_denied_frozen_sample(self, client, temp_routes) -> None:
        """Spec 08 §2 冻结样例：403001 / permission denied / data=null。"""
        from app.core.errors import PermissionDeniedError

        @temp_routes.get("/api/v1/admin/__test/forbidden")
        async def _forbidden() -> None:
            raise PermissionDeniedError

        response = await client.get("/api/v1/admin/__test/forbidden")

        assert response.status_code == 403
        body = response.json()
        assert body["code"] == 403001
        assert body["message"] == "permission denied"
        assert body["data"] is None


# ===========================================================================
# Spec 10 §9 —— 不得泄漏内部信息
# ===========================================================================
class TestErrorLeakage:
    async def test_unhandled_exception_returns_generic_envelope(self, client, temp_routes) -> None:
        """未捕获异常 → 500000，且响应体不含堆栈 / 内部消息。"""
        secret_marker = "INTERNAL-ONLY-DETAIL-9f3a"

        @temp_routes.get("/api/v1/admin/__test/boom")
        async def _boom() -> None:
            raise RuntimeError(secret_marker)

        response = await client.get("/api/v1/admin/__test/boom")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == int(ErrorCode.INTERNAL_ERROR)
        assert body["data"] is None
        assert secret_marker not in response.text
        assert "Traceback" not in response.text

    async def test_validation_error_does_not_echo_input(self, client, temp_routes) -> None:
        """校验失败不得回显用户输入（可能含明文密码）。

        FastAPI 默认 422 响应会带上 `input` 字段回显原始输入；
        当校验目标是 password 时，这会直接把明文口令写进响应体，
        违反 Spec 10 §4。因此 `_sanitize_validation_errors` 必须剥离 input。
        """
        from pydantic import Field

        plaintext_password = "PLAINTEXT-MARKER-abc123"

        class Payload(BaseModel):
            username: str
            # max_length 故意设为 8，使上面的长明文口令必然校验失败
            password: str = Field(max_length=8)

        @temp_routes.post("/api/v1/admin/__test/validate")
        async def _validate(payload: Payload) -> dict[str, str]:
            return {"username": payload.username}

        response = await client.post(
            "/api/v1/admin/__test/validate",
            json={"username": "alice", "password": plaintext_password},
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == int(ErrorCode.VALIDATION_ERROR)
        assert plaintext_password not in response.text
        for item in body["data"]:
            assert "input" not in item
            assert set(item) == {"loc", "msg", "type"}


# ===========================================================================
# Spec 06 §3 —— Trace / Request ID
# ===========================================================================
class TestTraceContext:
    async def test_ids_generated_when_absent(self, client, api_prefix: str) -> None:
        response = await client.get(f"{api_prefix}/health")

        trace_id = response.headers.get(TRACE_ID_HEADER)
        request_id = response.headers.get(REQUEST_ID_HEADER)

        assert trace_id is not None and _HEX32.match(trace_id)
        assert request_id is not None and _HEX32.match(request_id)
        assert trace_id != request_id

    async def test_incoming_ids_are_propagated(self, client, api_prefix: str) -> None:
        """Spec 06 §3：调用方传入的 X-Trace-ID / X-Request-ID 必须透传。"""
        response = await client.get(
            f"{api_prefix}/health",
            headers={
                TRACE_ID_HEADER: "trace-from-caller",
                REQUEST_ID_HEADER: "request-from-caller",
            },
        )

        assert response.headers[TRACE_ID_HEADER] == "trace-from-caller"
        assert response.headers[REQUEST_ID_HEADER] == "request-from-caller"

    async def test_oversized_incoming_id_is_replaced(self, client, api_prefix: str) -> None:
        """超长 ID 被丢弃并重新生成，避免日志膨胀与响应头异常。"""
        response = await client.get(
            f"{api_prefix}/health",
            headers={TRACE_ID_HEADER: "x" * 500},
        )

        trace_id = response.headers[TRACE_ID_HEADER]
        assert trace_id != "x" * 500
        assert _HEX32.match(trace_id)

    async def test_ids_are_unique_per_request(self, client, api_prefix: str) -> None:
        first = await client.get(f"{api_prefix}/health")
        second = await client.get(f"{api_prefix}/health")

        assert first.headers[TRACE_ID_HEADER] != second.headers[TRACE_ID_HEADER]


# ===========================================================================
# Spec 00 §8 / 06 §4 —— Masking
# ===========================================================================
class TestMasking:
    def test_phone(self) -> None:
        assert mask_phone("13812341234") == "138****1234"

    def test_email(self) -> None:
        assert mask_email("abc@example.com") == "abc***@example.com"

    def test_token_keeps_first_six_chars_only(self) -> None:
        assert mask_token("abcdef1234567890") == "abcdef"

    def test_empty_values_are_masked(self) -> None:
        assert mask_phone("") == "***"
        assert mask_email("not-an-email") == "***"
        assert mask_token("") == "***"

    @pytest.mark.parametrize(
        "key", ["password", "password_hash", "mfa_secret", "refresh_token", "signing_secret"]
    )
    def test_never_log_keys_are_redacted(self, key: str) -> None:
        result = scrub({key: "super-secret-value"})
        assert result[key] == "<redacted>"

    def test_scrub_is_recursive(self) -> None:
        result = scrub(
            {
                "user": {"phone": "13812341234", "email": "abc@example.com", "password": "x"},
                "items": [{"token": "abcdef123456"}],
            }
        )
        assert result["user"]["phone"] == "138****1234"
        assert result["user"]["email"] == "abc***@example.com"
        assert result["user"]["password"] == "<redacted>"
        assert result["items"][0]["token"] == "abcdef"

    def test_scrub_does_not_mutate_input(self) -> None:
        payload = {"password": "x", "phone": "13812341234"}
        scrub(payload)
        assert payload == {"password": "x", "phone": "13812341234"}

    def test_sensitive_containers_are_marked(self) -> None:
        result = scrub({"headers": {"Authorization": "Bearer abcdef"}})
        assert "Bearer" not in str(result)


# ===========================================================================
# Spec 00 §6 / 07 §2 / 12 §1 —— Snowflake ID
# ===========================================================================
class TestSnowflake:
    def test_ids_are_unique_and_monotonic(self) -> None:
        generator = SnowflakeGenerator(worker_id=3, datacenter_id=7)
        ids = [generator.next_id() for _ in range(2000)]

        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)

    def test_ids_fit_bigint(self) -> None:
        generator = SnowflakeGenerator(worker_id=1, datacenter_id=1)
        for _ in range(100):
            value = generator.next_id()
            assert 0 < value <= MAX_BIGINT

    def test_parse_roundtrip(self) -> None:
        generator = SnowflakeGenerator(worker_id=5, datacenter_id=9)
        value = generator.next_id()
        parts = generator.parse(value)

        assert parts["worker_id"] == 5
        assert parts["datacenter_id"] == 9
        assert parts["timestamp"] > generator.epoch_ms

    @pytest.mark.parametrize(("worker", "datacenter"), [(32, 0), (-1, 0), (0, 32)])
    def test_invalid_worker_configuration(self, worker: int, datacenter: int) -> None:
        with pytest.raises(InvalidWorkerConfigError):
            SnowflakeGenerator(worker_id=worker, datacenter_id=datacenter)

    def test_future_epoch_is_rejected(self) -> None:
        """epoch 晚于当前时间 → fail-closed，拒绝生成。"""
        generator = SnowflakeGenerator(epoch_ms=4102444800000)  # 2100-01-01
        with pytest.raises(ClockBackwardError):
            generator.next_id()

    def test_clock_rollback_is_rejected(self) -> None:
        """模拟时钟回拨：fail-closed，不产生可能重复的 ID。"""
        generator = SnowflakeGenerator()
        generator.next_id()
        generator._last_timestamp += 10_000

        with pytest.raises(ClockBackwardError):
            generator.next_id()


# ===========================================================================
# Spec 07 §2 / 00 §6 —— BIGINT 在 API JSON 中序列化为字符串
# ===========================================================================
class TestSnowflakeSerialization:
    def test_json_output_is_string(self) -> None:
        class Model(BaseModel):
            id: SnowflakeId

        model = Model(id=1_234_567_890_123)
        assert model.id == 1_234_567_890_123
        assert model.model_dump(mode="json") == {"id": "1234567890123"}
        assert model.model_dump() == {"id": 1_234_567_890_123}

    def test_accepts_string_input(self) -> None:
        class Model(BaseModel):
            id: SnowflakeId

        assert Model(id="987654321").id == 987654321

    def test_rejects_non_numeric_and_out_of_range(self) -> None:
        class Model(BaseModel):
            id: SnowflakeId

        with pytest.raises(ValueError):
            Model(id="not-a-number")
        with pytest.raises(ValueError):
            Model(id=MAX_BIGINT + 1)
