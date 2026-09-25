"""masking 在**日志链路**上的有效性（Spec `06 §4` / `10 §4` / `00 §8`）。

为什么单独测"自由文本"
--------------------
`scrub()` 靠**键名**判断敏感度。而日志正文是渲染后的字符串：

```python
logger.info("login failed phone=%s password=%s", phone, raw_password)
```

渲染之后既没有 `phone` 键也没有 `password` 键。而 `MaskingFilter` 跳过的恰恰是
`msg` / `args`（保留键）。于是在 Phase 6 之前，`06 §4` 的五条脱敏规则
在最常见的那条路径上**完全不生效** —— 却没有任何测试会失败，
因为既有测试只覆盖了 `scrub({...})` 这种结构化入口。

本模块把这条路径变成可执行的证据。
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import (
    JsonFormatter,
    MaskingFilter,
    PlainFormatter,
    _scrub_record_message,
)
from app.core.masking import scrub, scrub_field, scrub_text


class TestFreeTextMasking:
    """`scrub_text` 的五条 Frozen 规则。"""

    def test_phone_becomes_frozen_shape(self) -> None:
        assert scrub_text("登录失败 phone=13812341234") == "登录失败 phone=138****1234"

    def test_email_becomes_frozen_shape(self) -> None:
        assert scrub_text("通知 abc@example.com") == "通知 abc***@example.com"

    def test_phone_inside_sentence_not_at_boundary(self) -> None:
        assert scrub_text("call13812341234now") == "call138****1234now"

    def test_password_pair_never_logged(self) -> None:
        result = scrub_text("create failed password=hunter2 retry")
        assert "hunter2" not in result
        assert "password=<redacted>" in result

    def test_colon_separator_also_covered(self) -> None:
        result = scrub_text("mfa_secret: JBSWY3DPEHPK3PXP")
        assert "JBSWY3DPEHPK3PXP" not in result

    def test_jwt_never_logged(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        result = scrub_text(f"authorization failed token={jwt}")
        assert jwt not in result
        assert "<redacted>" in result

    def test_bearer_token_never_logged(self) -> None:
        result = scrub_text("Bearer abcdef1234567890 rejected")
        assert "abcdef1234567890" not in result

    def test_authorization_header_never_logged(self) -> None:
        result = scrub_text("headers Authorization: Bearer abc.def.ghi")
        assert "abc.def.ghi" not in result
        assert "authorization=<redacted>" in result

    def test_token_only_first_six_chars_is_not_enough_for_free_text(self) -> None:
        """自由文本里**整体**替换，比"只留前 6 字符"更严。

        `06 §4` 对 token 的规则是"保留前 6 个字符"，那是针对**具名 token 字段**的
        展示口径；`10 §4` 的措辞则是"不得记录 access token **plaintext**"。
        自由文本没有"这是个 token 字段"的上下文，因此取两侧更严的那一条。
        方向只允许更严，不允许更松。
        """
        result = scrub_text("token=abcdef1234567890")
        assert "abcdef" not in result

    def test_snowflake_id_is_not_mistaken_for_a_phone(self) -> None:
        """19 位 Snowflake ID 不得被当成手机号。

        这是"宁可多脱一点"的反面约束：如果连业务 ID 都被打码，
        日志就失去了排查价值，运维会转而关闭脱敏 —— 那才是真正的失败。
        """
        snowflake = "1234567890123456789"
        assert scrub_text(f"user_id={snowflake}") == f"user_id={snowflake}"

    def test_is_idempotent(self) -> None:
        once = scrub_text("phone=13812341234 mail=abc@example.com password=x")
        assert scrub_text(once) == once

    def test_empty_input(self) -> None:
        assert scrub_text("") == ""

    def test_plain_text_untouched(self) -> None:
        message = "request_completed method=GET path=/health status=200"
        assert scrub_text(message) == message


class TestScrubCoversUnnamedFields:
    """键名不敏感 ≠ 值不敏感。"""

    def test_unknown_key_with_phone_is_still_masked(self) -> None:
        result = scrub({"remark": "客户电话 13812341234"})
        assert "13812341234" not in str(result)

    def test_nested_list_strings_are_masked(self) -> None:
        result = scrub({"items": ["13812341234"]})
        assert result["items"][0] == "138****1234"

    def test_scrub_field_masks_unknown_key_text(self) -> None:
        assert scrub_field("detail", "abc@example.com") == "abc***@example.com"

    def test_never_log_key_still_wins(self) -> None:
        assert scrub({"password": "13812341234"})["password"] == "<redacted>"

    def test_structured_field_value_keeps_frozen_phone_shape(self) -> None:
        assert scrub({"phone": "13812341234"})["phone"] == "138****1234"


class TestMaskingFilterRewritesMessage:
    """过滤器必须让**所有** handler 拿到同一份安全文本。"""

    def _record(self, msg: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
        return logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=None,
        )

    def test_message_with_password_is_scrubbed(self) -> None:
        record = self._record("reset failed password=%s", ("hunter2",))
        assert MaskingFilter().filter(record) is True
        assert "hunter2" not in record.getMessage()

    def test_message_with_phone_and_email_is_scrubbed(self) -> None:
        record = self._record("notify 13812341234 / abc@example.com", ())
        MaskingFilter().filter(record)
        rendered = record.getMessage()
        assert "13812341234" not in rendered
        assert "abc@example.com" not in rendered

    def test_args_are_consumed_so_no_double_formatting(self) -> None:
        """改写了 `msg` 就必须清空 `args`，否则 `%` 会二次格式化。"""
        record = self._record("value=%s", ("abc",))
        MaskingFilter().filter(record)
        assert record.args is None
        assert record.getMessage() == "value=abc"

    def test_extra_fields_still_scrubbed(self) -> None:
        record = self._record("ok")
        record.password = "secret-value"
        MaskingFilter().filter(record)
        assert record.password == "<redacted>"

    def test_filter_is_idempotent_via_flag(self) -> None:
        record = self._record("phone=13812341234")
        MaskingFilter().filter(record)
        first = record.getMessage()
        assert MaskingFilter().filter(record) is True
        assert record.getMessage() == first

    def test_scrub_record_message_survives_broken_args(self) -> None:
        """`args` 与占位符不匹配时不得抛异常（过滤器不能改变日志可用性）。"""
        record = self._record("value=%s %s", ("only-one",))
        with pytest.raises(TypeError):
            record.getMessage()
        _scrub_record_message(record)  # 不应抛出


class TestFormattersMaskSensitiveText:
    """两个 formatter 都必须覆盖消息正文与异常堆栈。"""

    def _record(self, msg: str, exc: BaseException | None = None) -> logging.LogRecord:
        exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
        return logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )

    def test_json_formatter_masks_message(self) -> None:
        payload = json.loads(JsonFormatter().format(self._record("password=hunter2")))
        assert "hunter2" not in payload["message"]

    def test_json_formatter_masks_phone(self) -> None:
        payload = json.loads(JsonFormatter().format(self._record("13812341234")))
        assert payload["message"] == "138****1234"

    def test_json_formatter_masks_exception_text(self) -> None:
        try:
            raise RuntimeError("dsn=postgres://u:p@h/db phone=13812341234")
        except RuntimeError as exc:
            payload = json.loads(JsonFormatter().format(self._record("boom", exc)))
        assert "13812341234" not in payload["exception"]

    def test_plain_formatter_masks_exception_text(self) -> None:
        formatter = PlainFormatter("%(message)s")
        try:
            raise RuntimeError("password=hunter2")
        except RuntimeError as exc:
            rendered = formatter.format(self._record("boom", exc))
        assert "hunter2" not in rendered

    def test_json_formatter_keeps_trace_fields(self) -> None:
        from app.core.context import reset_ids, set_ids

        tokens = set_ids("t" * 32, "r" * 32)
        try:
            payload = json.loads(JsonFormatter().format(self._record("ok")))
        finally:
            reset_ids(tokens)
        assert payload["trace_id"] == "t" * 32
        assert payload["request_id"] == "r" * 32
