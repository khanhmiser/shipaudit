"""Kiểm tra core/reconcile.reconcile_statement trên Mongo giả (mongomock), từng loại chênh lệch."""
from dataclasses import replace
from datetime import datetime, timedelta

import mongomock
import pytest

from common.enums import DiffType
from core.engine import compute_expected
from core.indexes import ensure_indexes
from core.periods import VN_TZ, as_aware, to_db
from core.reconcile import classify, reconcile_statement
from core.rules import rules_from_documents, upsert_rules
from generator.carriers.params import carrier_rule_documents
from generator.statements import normalize_row, render_row

RULES = rules_from_documents(carrier_rule_documents())
PERIOD = "2026-W42"  # 12/10 – 18/10/2026 giờ Việt Nam
RECEIVED = datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ)
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=VN_TZ)
IN_PERIOD = datetime(2026, 10, 12, 10, 0, tzinfo=VN_TZ)  # Carrier A T+2 → hạn 14/10 (W42)


def order(code, carrier="carrier_a", delivered=IN_PERIOD, **kw):
    base = {"order_code": code, "carrier": carrier, "status": "DELIVERED", "region": "noi_tinh",
            "weight_g": 400, "length_cm": 20, "width_cm": 15, "height_cm": 10, "cod_amount": 350_000,
            "delivered_at": to_db(delivered)}
    return {**base, **kw}


def line(o, statement_id, change=None, period=PERIOD):
    actual = compute_expected(o, None, RULES[o["carrier"]])
    if change:
        actual = replace(actual, **change(actual))
    ln = normalize_row(o["carrier"], render_row(o["carrier"], o, actual))
    ln.update(statement_id=statement_id, period=period, ingested_at=to_db(RECEIVED))
    return ln


@pytest.fixture
def db():
    d = mongomock.MongoClient().db
    ensure_indexes(d)
    upsert_rules(d, carrier_rule_documents())
    return d


@pytest.fixture
def stm_a(db):
    orders = {
        "A-1": order("A-1"),
        "A-2": order("A-2"),
        "A-3": order("A-3"),
        "A-4": order("A-4", status="RETURNED", region="noi_vung", weight_g=800, length_cm=0, width_cm=0,
                     height_cm=0, cod_amount=450_000, storage_days=4),
        "A-5": order("A-5"),
        "A-6": order("A-6", delivered=IN_PERIOD - timedelta(days=7)),   # kỳ W41, trả trong W42
        "A-7": order("A-7", delivered=IN_PERIOD + timedelta(days=5)),   # kỳ W43, chưa đến hạn
    }
    db.orders.insert_many([dict(o) for o in orders.values()])
    sid = "STM-A-TEST"
    lines = [
        line(orders["A-1"], sid),
        line(orders["A-2"], sid, lambda a: {"shipping_fee": a.shipping_fee + 3_000}),
        line(orders["A-3"], sid, lambda a: {"cod_collected": 300_000}),
        line(orders["A-4"], sid, lambda a: {"return_shipping_fee": a.return_shipping_fee * 2}),
        line(orders["A-6"], sid),
        {"statement_id": sid, "carrier": "carrier_a", "order_code": "X-999", "period": PERIOD,
         "cod_collected": 0, "net_paid": 10_000, "ingested_at": to_db(RECEIVED)},
    ]
    db.statement_lines.insert_many(lines)
    return sid


def by_code(records):
    return {r["order_code"]: r for r in records}


def test_each_diff_type(db, stm_a):
    recs = by_code(reconcile_statement(stm_a, db, now=NOW))
    assert set(recs) == {"A-1", "A-2", "A-3", "A-4", "A-5", "A-6", "X-999"}  # A-7 chưa đến hạn

    assert recs["A-1"]["diff_type"] == "NONE" and recs["A-1"]["diff"] == 0
    assert recs["A-1"]["expected_amount"] == recs["A-1"]["actual_amount"] == 322_850

    assert recs["A-2"]["diff_type"] == "FEE_MISMATCH" and recs["A-2"]["diff"] == 3_000
    assert recs["A-3"]["diff_type"] == "COD_MISMATCH" and recs["A-3"]["diff"] == 50_000

    assert recs["A-4"]["diff_type"] == "RETURN_FEE_DOUBLE" and recs["A-4"]["diff"] == 16_000
    assert recs["A-4"]["expected_amount"] == -55_500 and recs["A-4"]["actual_amount"] == -71_500

    assert recs["A-5"]["diff_type"] == "MISSING_IN_STATEMENT"
    assert recs["A-5"]["actual_amount"] == 0 and recs["A-5"]["diff"] == 322_850

    assert recs["A-6"]["diff_type"] == "LATE_PAYOUT" and recs["A-6"]["diff"] == 0 and recs["A-6"]["late"]

    assert recs["X-999"]["unmatched"] and recs["X-999"]["diff_type"] == "NONE"


def test_breakdown_and_deadline_recorded(db, stm_a):
    recs = by_code(reconcile_statement(stm_a, db, now=NOW))
    r = recs["A-2"]
    assert r["breakdown"]["shipping_fee"] == 22_000 and r["actual_breakdown"]["shipping_fee"] == 25_000
    assert as_aware(r["claim_deadline_at"]) == RECEIVED + timedelta(hours=168)
    assert r["claim_hours_left"] == 144.0
    assert r["rule_version"] == 1 and r["period"] == PERIOD


def test_idempotent(db, stm_a):
    first = reconcile_statement(stm_a, db, now=NOW)
    created = {d["order_code"]: d["created_at"] for d in db.reconciliations.find()}
    second = reconcile_statement(stm_a, db, now=NOW + timedelta(hours=5))
    assert db.reconciliations.count_documents({}) == len(first) == len(second)
    assert {d["order_code"]: d["created_at"] for d in db.reconciliations.find()} == created
    assert db.reconciliations.find_one({"order_code": "A-2"})["claim_hours_left"] == 139.0


def test_duplicate_lines_counted_once(db, stm_a):
    # Index unique chặn dòng trùng ngay khi ghi; dữ liệu cũ (trước khi có index) vẫn được đếm một lần.
    with pytest.raises(Exception):
        db.statement_lines.insert_one(db.statement_lines.find_one({"order_code": "A-1"}, {"_id": 0}))
    db.statement_lines.drop_index("statement_order_unique")
    dup = db.statement_lines.find_one({"order_code": "A-1"}, {"_id": 0})
    db.statement_lines.insert_one(dup)
    recs = by_code(reconcile_statement(stm_a, db, now=NOW))
    assert recs["A-1"]["diff_type"] == "NONE" and recs["A-1"]["duplicate_lines"] == 2


def test_period_inferred_when_missing(db, stm_a):
    db.statement_lines.update_many({}, {"$unset": {"period": ""}})
    recs = by_code(reconcile_statement(stm_a, db, now=NOW))
    assert recs["A-5"]["diff_type"] == "MISSING_IN_STATEMENT"
    assert recs["A-6"]["diff_type"] == "LATE_PAYOUT"


def test_unknown_statement_returns_empty(db):
    assert reconcile_statement("NOPE", db) == []


def test_carrier_c_merged_fee_column(db):
    # Carrier C chỉ có total_fee: phí hoàn trừ hai lần nhận ra vì phần trừ dư đúng bằng phí hoàn.
    delivered = datetime(2026, 10, 13, 10, 0, tzinfo=VN_TZ)  # T+1 → hạn 14/10
    o1 = order("C-1", "carrier_c", delivered, status="RETURNED", cod_amount=0, declared_value=800_000,
               region="lien_vung", weight_g=300, length_cm=0, width_cm=0, height_cm=0, storage_days=7)
    o2 = order("C-2", "carrier_c", delivered, address_changes=1)
    db.orders.insert_many([dict(o1), dict(o2)])
    sid = "STM-C-TEST"
    db.statement_lines.insert_many([
        line(o1, sid, lambda a: {"return_shipping_fee": a.return_shipping_fee * 2}),
        line(o2, sid, lambda a: {"shipping_fee": a.shipping_fee + 5_000}),
    ])
    recs = by_code(reconcile_statement(sid, db, now=NOW))
    assert "return_shipping_fee" not in db.statement_lines.find_one({"order_code": "C-1"})
    assert recs["C-1"]["diff_type"] == "RETURN_FEE_DOUBLE" and recs["C-1"]["diff"] == 15_000
    assert recs["C-2"]["diff_type"] == "FEE_MISMATCH" and recs["C-2"]["diff"] == 5_000
    assert as_aware(recs["C-1"]["claim_deadline_at"]) == RECEIVED + timedelta(hours=24)
    assert recs["C-1"]["claim_hours_left"] == 0.0


def test_deadline_from_delivery_when_carrier_says_so(db, stm_a):
    doc = next(d for d in carrier_rule_documents() if d["carrier"] == "carrier_a")
    upsert_rules(db, [{**doc, "version": 2, "claim_deadline_anchor": "delivered_at", "claim_window_hours": 30 * 24}])
    recs = by_code(reconcile_statement(stm_a, db, now=NOW))
    assert as_aware(recs["A-2"]["claim_deadline_at"]) == IN_PERIOD + timedelta(days=30)
    assert as_aware(recs["A-6"]["claim_deadline_at"]) == IN_PERIOD - timedelta(days=7) + timedelta(days=30)
    assert as_aware(recs["X-999"]["claim_deadline_at"]) == RECEIVED + timedelta(days=30)   # dòng lạ: mốc nhận bảng kê
    assert recs["A-2"]["claim_hours_left"] == (IN_PERIOD + timedelta(days=30) - NOW).total_seconds() / 3600


def test_unique_index_blocks_duplicates(db, stm_a):
    reconcile_statement(stm_a, db, now=NOW)
    with pytest.raises(Exception):
        db.reconciliations.insert_one({"statement_id": stm_a, "order_code": "A-1"})


def test_classify_without_line_is_missing():
    o = order("A-1")
    assert classify(compute_expected(o, None, RULES["carrier_a"]), None) is DiffType.MISSING_IN_STATEMENT


def test_statement_lines_index_matches_ingest_and_migrates_legacy():
    d = mongomock.MongoClient().db
    d.statement_lines.create_index([("statement_id", 1), ("order_code", 1)], name="statement_order")  # bản cũ
    ensure_indexes(d)
    ensure_indexes(d)                                                    # gọi lại được
    info = d.statement_lines.index_information()
    assert "statement_order" not in info and info["statement_order_unique"].get("unique") is True
    # Tạo lại index theo cách của luồng nạp (A) chạy trên Mongo thật: tests/pipelines/test_pipelines.py.
