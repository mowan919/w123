"""设备粗分类测试（Phase 4 / INTERIM 技术取值）。

本模块的输出**不参与任何安全判断**（见 `app.core.security.device` 的说明），
因此用例只钉住"分类是否按预期粗粒度成立"与"缺失是否如实表达为缺失"。
"""

from __future__ import annotations

import pytest

from app.core.security.device import DEVICE_MAX_LENGTH, describe_device

pytestmark = pytest.mark.unit

_CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
)
_IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.1 Safari/604.1"
)


class TestMissingUserAgent:
    def test_none_returns_none(self) -> None:
        """缺失就是缺失 —— 不编造 "unknown" 让下游误当成一个事实。"""
        assert describe_device(None) is None

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_blank_returns_none(self, value: str) -> None:
        assert describe_device(value) is None


class TestClassification:
    def test_chrome_on_windows_is_desktop(self) -> None:
        label = describe_device(_CHROME_WINDOWS)
        assert label is not None
        assert "Chrome" in label
        assert "Windows" in label
        assert "desktop" in label

    def test_iphone_safari_is_mobile(self) -> None:
        label = describe_device(_SAFARI_IPHONE)
        assert label is not None
        assert "Safari" in label
        assert "iOS" in label
        assert "mobile" in label

    def test_ipad_is_tablet(self) -> None:
        label = describe_device(_IPAD)
        assert label is not None
        assert "tablet" in label

    def test_curl_is_programmatic_not_desktop(self) -> None:
        """命令行 / 自动化客户端必须与浏览器区分开。

        否则后台会显示一堆"Chrome · Windows · desktop"，
        而实际全是脚本 —— 那会让"谁在用这个账号"这一判断失真。
        """
        label = describe_device("curl/8.4.0")
        assert label is not None
        assert "http-client" in label
        assert "programmatic" in label

    def test_edge_is_not_misclassified_as_chrome(self) -> None:
        """Edge 的 UA 同时包含 Chrome 与 Edg —— 判定顺序必须让 Edge 优先。"""
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
        )
        label = describe_device(ua)
        assert label is not None
        assert label.startswith("Edge")

    def test_unknown_parts_are_marked_unknown(self) -> None:
        label = describe_device("SomeRandomAgent/1.0")
        assert label == "unknown · unknown · unknown"

    def test_label_is_truncated_to_column_width(self) -> None:
        """标签长度必须受列宽约束。

        这是**防御性上限**：正常 UA 的分类结果约 20~40 字符，远低于 128，
        因此截断在实际数据上不可达。保留它是为了让"未来某次正则改动
        让标签突然变长"不会以"写库失败（value too long）"的形式暴露 ——
        那会把一个纯展示字段的问题升级成登录失败。
        """
        label = describe_device("Mozilla/5.0 (Windows NT 10.0) " + "A" * 500)
        assert label is not None
        assert len(label) <= DEVICE_MAX_LENGTH
        assert DEVICE_MAX_LENGTH == 128
