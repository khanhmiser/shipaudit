"""Luồng nạp trên mongomock: một lần nạp ghi đủ statement_lines, reconciliations (stub khi B chưa cài),
ingest_events; nạp lại không nhân đôi; dòng hỏng → PARTIAL; sai tiêu đề → ERROR; công tắc lỗi làm lag tăng.
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock
import pytest
from pymongo.errors import OperationFailure

from app.ingest import pipeline
from app.ingest.pipeline import ERROR, OK, PARTIAL, Faults, ingest
from common.enums import Collections

SAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "samples"
T0 = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)


class Clock:
    """Đồng hồ giả: sleep() cộng thêm vào giờ hiện tại, để test lag_seconds không phải chờ thật."""

    def __init__(self, start: datetime):
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True).db


@pytest.fixture
def metrics():
    return []


@pytest.fixture
def run(db, tmp_path, metrics):
    def _run(carrier="carrier_a", raw=None, **kw):
        raw = raw if raw is not None else (SAMPLES / f"statement_{carrier}.csv").read_bytes()
        clock = kw.pop("clock", Clock(T0))
        return ingest(db, carrier, raw, f"statement_{carrier}.csv", upload_dir=tmp_path, now=clock.now,
                      sleep=clock.sleep, emit=lambda n, v, t=None: metrics.append((n, v, t)), **kw)
    return _run


def _not_implemented(statement_id, db):
    raise NotImplementedError


@pytest.mark.parametrize("carrier", ["carrier_a", "carrier_b", "carrier_c"])
def test_one_ingest_fills_three_collections(db, run, carrier, tmp_path):
    res = run(carrier, reconcile_fn=_not_implemented)
    assert res.status == OK and res.rows == 4 and res.skipped == 0
    assert db[Collections.STATEMENT_LINES].count_documents({"statement_id": res.statement_id}) == 4

    # B chưa cài reconcile_statement: dùng stub, ghi kèm cờ stub=true.
    assert res.stub and res.reconciled == 1
    rec = db[Collections.RECONCILIATIONS].find_one({"statement_id": res.statement_id})
    assert rec["stub"] is True and rec["carrier"] == carrier and rec["diff"] == 5_000

    ev = db[Collections.INGEST_EVENTS].find_one()
    assert ev["meta"] == {"carrier": carrier, "statement_id": res.statement_id}
    assert ev["status"] == OK and ev["rows"] == 4 and isinstance(ev["duration_ms"], int)
    assert ev["lag_seconds"] == 0

    assert Path(res.file).read_bytes() == (SAMPLES / f"statement_{carrier}.csv").read_bytes()
    assert Path(res.file).parent == tmp_path / carrier


def test_real_reconcile_is_called(db, run):
    calls = []

    def fake(statement_id, db_):
        calls.append(statement_id)
        return [{}, {}, {}]

    res = run(reconcile_fn=fake)
    assert calls == [res.statement_id] and res.reconciled == 3 and not res.stub
    assert db[Collections.RECONCILIATIONS].count_documents({}) == 0


def test_ingest_twice_does_not_duplicate(db, run):
    first = run(reconcile_fn=_not_implemented)
    second = run(reconcile_fn=_not_implemented)
    assert first.statement_id == second.statement_id  # cùng nội dung → cùng mã bảng kê
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 4
    assert db[Collections.RECONCILIATIONS].count_documents({}) == 1
    assert db[Collections.INGEST_EVENTS].count_documents({}) == 2  # mỗi lần nạp một sự kiện


def test_statement_id_from_period_and_explicit(db, run):
    assert run(period="2026-W42").statement_id == "STM-A-2026W42"
    line = db[Collections.STATEMENT_LINES].find_one({"statement_id": "STM-A-2026W42"})
    assert line["period"] == "2026-W42"
    assert run(statement_id="STM-A-MANUAL").statement_id == "STM-A-MANUAL"


def test_duplicate_order_in_file_keeps_last(db, run):
    raw = (b"order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid\n"
           b"A-1,100000,20000,0,0,1650,78350\nA-1,100000,20000,0,0,1650,70000\n")
    res = run(raw=raw)
    assert res.rows == 1
    assert db[Collections.STATEMENT_LINES].find_one({"order_code": "A-1"})["net_paid"] == 70000


def test_broken_rows_give_partial(db, run, metrics):
    raw = (SAMPLES / "statement_carrier_b.csv").read_bytes() + b"B-0005;abc;1;0;0;1\nB-0006;1;1;0;0\n"
    res = run("carrier_b", raw=raw)
    assert res.status == PARTIAL and res.rows == 4 and res.skipped == 2 and len(res.errors) == 2
    assert db[Collections.INGEST_EVENTS].find_one()["status"] == PARTIAL
    assert ("shipaudit.ops.ingest_errors", 2, {"carrier": "carrier_b", "status": PARTIAL}) in metrics


def test_wrong_header_gives_error_and_writes_nothing(db, run):
    res = run("carrier_c", raw=b"tracking,cod,fee,net\nC-1,1,1,0\n")
    assert res.status == ERROR and res.error_kind == "format" and "sai tiêu đề" in res.error
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 0
    assert db[Collections.RECONCILIATIONS].count_documents({}) == 0
    ev = db[Collections.INGEST_EVENTS].find_one()
    assert ev["status"] == ERROR and ev["rows"] == 0 and "sai tiêu đề" in ev["error"]
    assert Path(res.file).exists()  # vẫn giữ file để điều tra


def test_reconcile_failure_is_error_but_lines_kept(db, run):
    def boom(statement_id, db_):
        raise RuntimeError("mất kết nối")

    res = run(reconcile_fn=boom)
    assert res.status == ERROR and res.error_kind == "reconcile" and "mất kết nối" in res.error
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 4


def test_delay_fault_raises_lag(db, run, metrics):
    res = run(faults=Faults(delay_ms=2_500))
    assert res.status == OK and res.lag_seconds == 2.5
    assert db[Collections.INGEST_EVENTS].find_one()["lag_seconds"] == 2.5
    assert ("shipaudit.ops.ingest_lag_seconds", 2.5, {"carrier": "carrier_a", "status": OK}) in metrics


def test_fail_rate_fault(db, run):
    res = run(faults=Faults(fail_rate=1.0), rng=random.Random(1))
    assert res.status == ERROR and res.error_kind == "fault"
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 0
    assert run(faults=Faults(fail_rate=0.0)).status == OK


def test_unknown_carrier_raises_before_writing(db, run):
    with pytest.raises(ValueError):
        run("carrier_x", raw=b"x")
    assert Collections.INGEST_EVENTS not in db.list_collection_names()


# ── ingest_events: Time Series hoặc dự phòng ──
def test_ingest_events_falls_back_to_ttl_collection(db, monkeypatch):
    def no_timeseries(name, **kw):
        if "timeseries" in kw:
            raise OperationFailure("time-series collections are not supported")
        return mongomock.Database.create_collection(db, name, **kw)

    monkeypatch.setattr(db, "create_collection", no_timeseries)
    assert pipeline.ensure_ingest_events(db) == "collection"
    ttl = db[Collections.INGEST_EVENTS].index_information()["ts_ttl"]
    assert ttl["expireAfterSeconds"] == pipeline.INGEST_EVENTS_TTL_SECONDS
    assert pipeline.ensure_ingest_events(db) == "collection"  # gọi lại không lỗi


def test_ingest_events_timeseries_options(db, monkeypatch):
    seen = {}

    def capture(name, **kw):
        seen.update(kw)
        return mongomock.Database.create_collection(db, name)

    monkeypatch.setattr(db, "create_collection", capture)
    assert pipeline.ensure_ingest_events(db) == "timeseries"
    assert seen["timeseries"] == {"timeField": "ts", "metaField": "meta", "granularity": "seconds"}
    assert seen["expireAfterSeconds"] == pipeline.INGEST_EVENTS_TTL_SECONDS


def test_statement_lines_unique_index(db):
    pipeline.ensure_storage(db)
    idx = db[Collections.STATEMENT_LINES].index_information()[pipeline.STATEMENT_LINES_INDEX]
    assert idx["unique"] and idx["key"] == [("statement_id", 1), ("order_code", 1)]
