"""[A] Luồng nạp: lưu file > parse > ghi statement_lines > reconcile_statement > ghi ingest_events.

Gọi B qua contracts.interfaces.ReconcileFn: dùng core.reconcile.reconcile_statement (test có thể truyền
hàm khác qua reconcile_fn). Lỗi ở bước đối soát làm lượt nạp ERROR với error_kind="reconcile".
Ghi ingest_events (Time Series, timeField ts, metaField meta={carrier, statement_id}) với: rows, skipped,
duration_ms, status (OK / PARTIAL / ERROR), lag_seconds. Có TTL. Atlas không tạo được Time Series thì
dùng collection thường có TTL index và ghi log cảnh báo.

- statement_lines upsert theo (statement_id, order_code), có index unique: nạp lại cùng file không nhân đôi.
- statement_id: truyền vào, hoặc STM-<hãng>-<kỳ> khi có kỳ (vd STM-B-2026W40), hoặc STM-<hãng>-<12 ký tự
  sha256 của file> (cùng nội dung → cùng mã).
- lag_seconds = lúc ghi xong − lúc nhận file. Công tắc lỗi (delay_ms) làm số này tăng.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pymongo import ASCENDING, UpdateOne
from pymongo.errors import OperationFailure

from app.ingest.parsers import StatementFormatError, get_parser
from app.telemetry.metrics import increment, metric
from common.enums import Collections
from contracts.interfaces import ReconcileFn

log = logging.getLogger("shipaudit.ingest")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
INGEST_EVENTS_TTL_SECONDS = int(os.getenv("INGEST_EVENTS_TTL_DAYS", "14")) * 24 * 3600
STATEMENT_LINES_INDEX = "statement_order_unique"
OK, PARTIAL, ERROR = "OK", "PARTIAL", "ERROR"


class InjectedFault(RuntimeError):
    """Lỗi giả do công tắc lỗi nạp (fail_rate) gây ra."""


@dataclass
class Faults:
    """Công tắc lỗi nạp (A7): trễ thêm delay_ms, và hỏng cả lượt nạp với xác suất fail_rate."""
    delay_ms: int = 0
    fail_rate: float = 0.0


@dataclass
class IngestResult:
    statement_id: str
    carrier: str
    status: str
    rows: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    reconciled: int = 0
    duration_ms: int = 0
    lag_seconds: float = 0.0
    file: str | None = None
    error: str | None = None
    error_kind: str | None = None  # format | fault | reconcile

    def to_dict(self) -> dict:
        return asdict(self)


# ── Chuẩn bị collection ──
def ensure_storage(db: Any) -> None:
    """Index unique cho statement_lines và collection ingest_events (Time Series có TTL). Gọi lại nhiều lần được."""
    try:
        db[Collections.STATEMENT_LINES].create_index(
            [("statement_id", ASCENDING), ("order_code", ASCENDING)], unique=True, name=STATEMENT_LINES_INDEX)
    except OperationFailure as e:
        # Đã có index cùng khóa nhưng khác tên/tùy chọn. Upsert vẫn giữ mỗi (statement_id, order_code) một dòng.
        log.warning("không tạo được index unique cho statement_lines", extra={"error": str(e)})
    ensure_ingest_events(db)


def ensure_ingest_events(db: Any) -> str:
    """Trả về "timeseries" hoặc "collection" (dạng dự phòng)."""
    name = Collections.INGEST_EVENTS
    if name in db.list_collection_names():
        if _collection_type(db, name) == "timeseries":
            return "timeseries"
        _ttl_index(db)
        return "collection"
    try:
        db.create_collection(
            name, timeseries={"timeField": "ts", "metaField": "meta", "granularity": "seconds"},
            expireAfterSeconds=INGEST_EVENTS_TTL_SECONDS,
        )
        return "timeseries"
    except Exception as e:  # noqa: BLE001 - gói Atlas, bản Mongo hoặc mongomock không hỗ trợ
        log.warning("không tạo được Time Series ingest_events, dùng collection thường có TTL",
                    extra={"error": f"{type(e).__name__}: {e}"})
        if name not in db.list_collection_names():
            db.create_collection(name)
        _ttl_index(db)
        return "collection"


def _collection_type(db: Any, name: str) -> str | None:
    try:
        info = next(iter(db.list_collections(filter={"name": name})), None)
    except Exception:  # noqa: BLE001 - mongomock không có list_collections
        return None
    return (info or {}).get("type")


def _ttl_index(db: Any) -> None:
    db[Collections.INGEST_EVENTS].create_index("ts", expireAfterSeconds=INGEST_EVENTS_TTL_SECONDS, name="ts_ttl")


# ── Các bước ──
def statement_id_for(carrier: str, raw: bytes, period: str | None = None) -> str:
    letter = carrier.rsplit("_", 1)[-1].upper()
    if period:
        return f"STM-{letter}-{period.replace('-', '')}"
    return f"STM-{letter}-{hashlib.sha256(raw).hexdigest()[:12].upper()}"


def save_upload(raw: bytes, carrier: str, statement_id: str, filename: str | None, upload_dir: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "statement.csv").name) or "statement.csv"
    path = upload_dir / carrier / f"{statement_id}__{safe}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def write_lines(db: Any, lines: list[dict], period: str | None) -> int:
    """Upsert theo (statement_id, order_code). Trùng mã đơn trong cùng file thì dòng sau ghi đè dòng trước."""
    if not lines:
        return 0
    ops = []
    for line in lines:
        doc = {**line, "period": period} if period else line
        ops.append(UpdateOne({"statement_id": line["statement_id"], "order_code": line["order_code"]},
                             {"$set": doc}, upsert=True))
    db[Collections.STATEMENT_LINES].bulk_write(ops, ordered=False)
    unique = len({line["order_code"] for line in lines})
    if unique < len(lines):
        log.warning("bảng kê có mã đơn trùng, giữ dòng sau",
                    extra={"statement_id": lines[0]["statement_id"], "duplicates": len(lines) - unique})
    return unique


def reconcile(db: Any, statement_id: str, fn: ReconcileFn | None = None) -> int:
    """Gọi reconcile_statement của B. Trả về số bản ghi đối soát."""
    if fn is None:
        from core.reconcile import reconcile_statement as fn
    return len(fn(statement_id, db))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Luồng nạp ──
def ingest(
    db: Any,
    carrier: str,
    raw: bytes,
    filename: str | None = None,
    *,
    statement_id: str | None = None,
    period: str | None = None,
    received_at: datetime | None = None,
    faults: Faults | None = None,
    reconcile_fn: ReconcileFn | None = None,
    upload_dir: Path | None = None,
    now: Callable[[], datetime] = _utcnow,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    emit: Callable[..., None] = metric,
    count: Callable[..., None] = increment,
) -> IngestResult:
    parser = get_parser(carrier)  # ValueError nếu mã hãng lạ: lỗi của người gọi, không ghi ingest_events
    received_at = received_at or now()
    started = time.perf_counter()
    statement_id = statement_id or statement_id_for(carrier, raw, period)
    result = IngestResult(statement_id=statement_id, carrier=carrier, status=OK)
    ensure_storage(db)

    try:
        result.file = str(save_upload(raw, carrier, statement_id, filename, upload_dir or UPLOAD_DIR))
        faults = faults or Faults()
        if faults.delay_ms > 0:
            sleep(faults.delay_ms / 1000)
        if faults.fail_rate > 0 and (rng or random).random() < faults.fail_rate:
            raise InjectedFault(f"lỗi giả do công tắc lỗi nạp (fail_rate={faults.fail_rate})")

        parsed = parser.parse_report(raw, statement_id, ingested_at=received_at)
        result.errors, result.skipped = parsed.errors, len(parsed.errors)
        result.rows = write_lines(db, parsed.lines, period)
        result.reconciled = reconcile(db, statement_id, reconcile_fn)
        result.status = PARTIAL if parsed.errors else OK
    except StatementFormatError as e:
        result.status, result.error, result.error_kind = ERROR, str(e), "format"
    except InjectedFault as e:
        result.status, result.error, result.error_kind = ERROR, str(e), "fault"
    except Exception as e:  # noqa: BLE001 - lỗi ở bước đối soát hoặc ghi: vẫn ghi ingest_events rồi báo lỗi
        log.exception("nạp bảng kê lỗi", extra={"statement_id": statement_id, "carrier": carrier})
        result.status, result.error, result.error_kind = ERROR, f"{type(e).__name__}: {e}", "reconcile"

    finished = now()
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    result.lag_seconds = round((finished - received_at).total_seconds(), 3)
    db[Collections.INGEST_EVENTS].insert_one({
        "ts": finished,
        "meta": {"carrier": carrier, "statement_id": statement_id},
        "rows": result.rows,
        "skipped": result.skipped,
        "duration_ms": result.duration_ms,
        "lag_seconds": result.lag_seconds,
        "status": result.status,
        **({"error": result.error} if result.error else {}),
    })

    # Gauge chỉ gắn tag hãng: tách theo trạng thái thì chuỗi status:ERROR dừng ở giá trị cuối và Datadog nội suy
    # thêm vài phút, làm monitor độ trễ hồi phục chậm. Trạng thái nằm ở count ingest_runs.
    tags = {"carrier": carrier}
    emit("shipaudit.ops.ingest_lag_seconds", result.lag_seconds, tags)
    emit("shipaudit.ops.ingest_duration_ms", result.duration_ms, tags)
    emit("shipaudit.ops.statement_rows", result.rows, tags)
    emit("shipaudit.ops.ingest_errors", result.skipped + (1 if result.status == ERROR else 0), tags)
    count("shipaudit.ops.ingest_runs", 1, {**tags, "status": result.status})  # tỉ lệ lỗi = runs{status:error} / runs
    level = logging.ERROR if result.status == ERROR else logging.INFO
    log.log(level, "nạp bảng kê thất bại" if result.status == ERROR else "nạp bảng kê xong", extra={
        "statement_id": statement_id, "carrier": carrier, "status": result.status, "rows": result.rows,
        "skipped": result.skipped, "duration_ms": result.duration_ms, "lag_seconds": result.lag_seconds,
        "error_kind": result.error_kind, "error": result.error,
    })
    return result
