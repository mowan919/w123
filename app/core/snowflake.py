"""Snowflake ID 生成器。

Frozen（Spec 00 §6 / 07 §2 / 15 D-014 / AGENTS.md §6）：
- 业务主键必须为 BIGINT + Snowflake；
- API JSON 中 BIGINT ID 统一序列化为**字符串**；
- **禁止**自增业务 ID；
- **禁止** UUID 作为业务主键。

UNRESOLVED DESIGN DECISION —— DD-14（技术参数未冻结）
-----------------------------------------------------
Spec 未定义：epoch 起始时间、位分配方案、worker/datacenter id 来源、
时钟回拨策略、序列号溢出策略、是否支持外部指定 ID（Seed 场景，见 07 §10）。

本实现采用**保守的行业标准默认值**（41 位时间戳 + 5 位数据中心 + 5 位机器 + 12 位序列），
全部参数可由环境变量覆盖，以便 DD-14 冻结后无需改动代码即可对齐。
时钟回拨采用 **fail-closed**（抛异常）而非静默等待，遵循 Spec 11 §5
"宁可失败也不产生不确定语义"的安全取向。

已登记为 Phase 1 的 UNRESOLVED DESIGN DECISION，不得视为最终需求。
"""

from __future__ import annotations

import threading
import time

from app.core.config import settings

# ---- 位分配（DD-14 保守默认值） ----
SEQUENCE_BITS = 12
WORKER_ID_BITS = 5
DATACENTER_ID_BITS = 5
TIMESTAMP_BITS = 41

MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1  # 4095
MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1  # 31
MAX_DATACENTER_ID = (1 << DATACENTER_ID_BITS) - 1  # 31
MAX_TIMESTAMP = (1 << TIMESTAMP_BITS) - 1

WORKER_ID_SHIFT = SEQUENCE_BITS
DATACENTER_ID_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS
TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS + DATACENTER_ID_BITS

#: BIGINT 有符号 64 位上限，Spec 07 §2 要求业务主键为 BIGINT。
MAX_BIGINT = (1 << 63) - 1


class SnowflakeError(RuntimeError):
    """Snowflake 生成异常基类。"""


class ClockBackwardError(SnowflakeError):
    """系统时钟发生回拨。fail-closed：拒绝生成 ID。"""


class InvalidWorkerConfigError(SnowflakeError):
    """worker_id / datacenter_id 越界。"""


class SnowflakeGenerator:
    """线程安全的 Snowflake ID 生成器。

    生成的 ID 保证在同一进程内单调递增且不重复；
    跨进程唯一性依赖 (datacenter_id, worker_id) 的唯一分配。
    """

    def __init__(
        self,
        *,
        worker_id: int = 1,
        datacenter_id: int = 1,
        epoch_ms: int = 1735689600000,
    ) -> None:
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise InvalidWorkerConfigError(
                f"worker_id 必须在 0..{MAX_WORKER_ID} 之间，当前为 {worker_id}"
            )
        if not 0 <= datacenter_id <= MAX_DATACENTER_ID:
            raise InvalidWorkerConfigError(
                f"datacenter_id 必须在 0..{MAX_DATACENTER_ID} 之间，当前为 {datacenter_id}"
            )

        self.worker_id = worker_id
        self.datacenter_id = datacenter_id
        self.epoch_ms = epoch_ms

        self._lock = threading.Lock()
        self._last_timestamp = -1
        self._sequence = 0

    # ------------------------------------------------------------------
    def _current_ms(self) -> int:
        return int(time.time() * 1000)

    def _now(self) -> int:
        return self._current_ms() - self.epoch_ms

    def next_id(self) -> int:
        """生成下一个 ID。"""
        with self._lock:
            timestamp = self._now()

            if timestamp < 0:
                raise ClockBackwardError("系统时间早于 Snowflake epoch，无法生成 ID")

            if timestamp < self._last_timestamp:
                # 时钟回拨：fail-closed，不使用可能重复的 ID
                raise ClockBackwardError(
                    f"检测到时钟回拨 {self._last_timestamp - timestamp} ms，拒绝生成 ID"
                )

            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    # 当前毫秒序列号耗尽，自旋等待下一毫秒
                    timestamp = self._wait_next_ms(self._last_timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = timestamp

            if timestamp > MAX_TIMESTAMP:
                raise SnowflakeError("时间戳超出 41 位可表示范围")

            snowflake_id = (
                (timestamp << TIMESTAMP_SHIFT)
                | (self.datacenter_id << DATACENTER_ID_SHIFT)
                | (self.worker_id << WORKER_ID_SHIFT)
                | self._sequence
            )

            if snowflake_id > MAX_BIGINT:
                raise SnowflakeError("生成的 ID 超出 BIGINT 范围")

            return snowflake_id

    def _wait_next_ms(self, last_timestamp: int) -> int:
        timestamp = self._now()
        while timestamp <= last_timestamp:
            time.sleep(0.0005)
            timestamp = self._now()
        return timestamp

    # ------------------------------------------------------------------
    def parse(self, snowflake_id: int) -> dict[str, int]:
        """反解 ID，用于排障与测试。"""
        return {
            "timestamp": (snowflake_id >> TIMESTAMP_SHIFT) + self.epoch_ms,
            "datacenter_id": (snowflake_id >> DATACENTER_ID_SHIFT) & MAX_DATACENTER_ID,
            "worker_id": (snowflake_id >> WORKER_ID_SHIFT) & MAX_WORKER_ID,
            "sequence": snowflake_id & MAX_SEQUENCE,
        }


_generator_lock = threading.Lock()
_default_generator: SnowflakeGenerator | None = None


def get_generator() -> SnowflakeGenerator:
    """返回进程级默认生成器（参数取自配置）。"""
    global _default_generator
    if _default_generator is None:
        with _generator_lock:
            if _default_generator is None:
                _default_generator = SnowflakeGenerator(
                    worker_id=settings.snowflake_worker_id,
                    datacenter_id=settings.snowflake_datacenter_id,
                    epoch_ms=settings.snowflake_epoch_ms,
                )
    return _default_generator


def next_id() -> int:
    """生成下一个业务 ID。"""
    return get_generator().next_id()


def reset_generator() -> None:
    """重置进程级生成器（测试用）。"""
    global _default_generator
    with _generator_lock:
        _default_generator = None
