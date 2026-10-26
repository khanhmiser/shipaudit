"""[A] Công tắc lỗi nạp (A7), giữ trong bộ nhớ của tiến trình api.

Giá trị ban đầu lấy từ INGEST_DELAY_MS và INGEST_FAIL_RATE. Đổi lúc chạy qua /admin/ingest-fault.
Chỉ đúng khi api chạy một tiến trình (uvicorn mặc định), vì mỗi tiến trình giữ trạng thái riêng.
"""
from __future__ import annotations

import threading
from dataclasses import replace

from app.ingest.pipeline import Faults
from common import config

_lock = threading.Lock()
_state = Faults(delay_ms=config.INGEST_DELAY_MS, fail_rate=config.INGEST_FAIL_RATE)


def get() -> Faults:
    with _lock:
        return replace(_state)


def set(delay_ms: int | None = None, fail_rate: float | None = None) -> Faults:  # noqa: A001
    global _state
    with _lock:
        _state = Faults(
            delay_ms=_state.delay_ms if delay_ms is None else delay_ms,
            fail_rate=_state.fail_rate if fail_rate is None else fail_rate,
        )
        return replace(_state)


def reset() -> Faults:
    global _state
    with _lock:
        _state = Faults()
        return replace(_state)
