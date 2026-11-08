"""[A] Nghe change stream của `reconciliations`.

Có bản ghi mới với diff != 0 thì ghi log JSON (trace_id, carrier, order_code, diff)
và đếm metric shipaudit.ops.* qua app.telemetry.metrics.

- Sự kiện insert/replace: xét diff của bản ghi. Sự kiện update: chỉ xét khi diff hoặc diff_type vừa đổi
  (đối soát lại cùng kết quả thì không ghi lại).
- Đếm: shipaudit.ops.reconciliation_diff_events (tag carrier, diff_type). Lỗi kết nối:
  shipaudit.ops.change_stream_errors, rồi tự thử lại (chờ 1, 2, 4... tối đa 30 giây), nối tiếp từ resume token.
Chạy: python -m app.workers.change_stream (service `worker` trong docker-compose).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from pymongo.errors import OperationFailure, PyMongoError

from app.telemetry.metrics import increment
from app.telemetry.tracing import span
from common.enums import Collections

log = logging.getLogger("shipaudit.worker")

PIPELINE = [{"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}}]
WATCHED_FIELDS = ("diff", "diff_type")
# Resume token không dùng được nữa (oplog đã trôi qua, token sai): bắt đầu nghe lại từ hiện tại.
RESUME_TOKEN_ERRORS = {260, 280, 286}


def handle_change(change: dict, emit: Callable[..., None] = increment) -> dict | None:
    """Xử lý một sự kiện. Trả về nội dung đã ghi log, hoặc None nếu bỏ qua."""
    op = change.get("operationType")
    if op == "update":
        updated = (change.get("updateDescription") or {}).get("updatedFields") or {}
        if not any(f in updated for f in WATCHED_FIELDS):
            return None
    doc = change.get("fullDocument") or {}
    diff = doc.get("diff") or 0
    if not diff:
        return None
    carrier, diff_type = doc.get("carrier", "unknown"), doc.get("diff_type", "unknown")
    with span("reconciliation.diff", carrier=carrier, diff_type=diff_type) as trace_id:
        event = {
            "event": "reconciliation_diff",
            "trace_id": trace_id,
            "operation": op,
            "carrier": carrier,
            "statement_id": doc.get("statement_id"),
            "order_code": doc.get("order_code"),
            "diff": int(diff),
            "diff_type": diff_type,
        }
        log.info("chênh lệch mới", extra=event)
        emit("shipaudit.ops.reconciliation_diff_events", 1, {"carrier": carrier, "diff_type": diff_type})
    return event


def run(
    db: Any,
    stop: threading.Event | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_backoff: float = 30,
    emit: Callable[..., None] = increment,
) -> None:
    stop = stop or threading.Event()
    resume_token, backoff = None, 1.0
    while not stop.is_set():
        try:
            with db[Collections.RECONCILIATIONS].watch(
                PIPELINE, full_document="updateLookup", resume_after=resume_token, max_await_time_ms=1000,
            ) as stream:
                log.info("đang nghe change stream reconciliations", extra={"resumed": resume_token is not None})
                backoff = 1.0
                while not stop.is_set() and stream.alive:
                    change = stream.try_next()  # chờ tối đa 1 giây rồi trả None, để kiểm tra `stop`
                    if change is not None:
                        handle_change(change, emit)
                    resume_token = stream.resume_token or resume_token
        except PyMongoError as e:
            if isinstance(e, OperationFailure) and e.code in RESUME_TOKEN_ERRORS:
                resume_token = None
            emit("shipaudit.ops.change_stream_errors", 1, {"error": type(e).__name__})
            log.warning("change stream mất kết nối, thử lại", extra={
                "error": f"{type(e).__name__}: {e}", "retry_in_seconds": backoff})
            sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def main() -> None:
    from app.telemetry.logging import setup_logging
    from app.telemetry.tracing import setup_tracing
    from common.db import get_db

    setup_logging()
    setup_tracing()
    try:
        run(get_db())
    except KeyboardInterrupt:
        log.info("dừng worker")


if __name__ == "__main__":
    main()
