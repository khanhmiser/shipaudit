"""[A] ddtrace cho FastAPI và PyMongo. Chạy no-op nếu không bật DD_TRACE_ENABLED hoặc chưa cài ddtrace.

Gọi setup_tracing() trước khi tạo FastAPI app. Trace gửi về Agent ở DD_AGENT_HOST (compose đặt sẵn).

PyMongo chỉ được bọc khi DD_TRACE_PYMONGO_ENABLED=true: ddtrace 4.16 bọc pymongo 4.19 bị lỗi ngay lúc import
(`Server.run_operation` không còn), làm sập app. Bật lại khi đã chọn được cặp phiên bản tương thích.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger("shipaudit.telemetry")
_enabled = False


def setup_tracing() -> bool:
    global _enabled
    if os.getenv("DD_TRACE_ENABLED", "false").lower() != "true":
        return False
    try:
        from ddtrace import patch

        patch(fastapi=True, logging=True, pymongo=os.getenv("DD_TRACE_PYMONGO_ENABLED", "false").lower() == "true")
        _enabled = True
    except Exception as e:  # noqa: BLE001
        log.warning("không bật được ddtrace", extra={"error": f"{type(e).__name__}: {e}"})
    return _enabled


@contextmanager
def span(name: str, **tags: str) -> Iterator[str]:
    """Mở một span (khi có ddtrace) và trả về trace_id để ghi vào log. Không có ddtrace thì trả mã ngẫu nhiên."""
    if not _enabled:
        yield uuid.uuid4().hex
        return
    from ddtrace.trace import tracer

    with tracer.trace(name, service=os.getenv("DD_SERVICE")) as s:
        for k, v in tags.items():
            s.set_tag(k, v)
        yield tracer.get_log_correlation_context().get("dd.trace_id") or str(s.trace_id)
