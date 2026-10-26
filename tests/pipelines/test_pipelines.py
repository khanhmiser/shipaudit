"""Test 4 Aggregation Pipeline trên dữ liệu seed cố định, so với cách tính độc lập bằng Python,
cùng explain() (có dùng index) và Time Series ingest_events.
"""
from collections import defaultdict
from datetime import timedelta

import pytest

from common.enums import Collections
from core.claims import ClaimService
from core.indexes import ensure_time_series
from core.periods import VN_TZ, as_aware
from generator.statements import statement_id_for
from pipelines import claims_expiring, diff_by_carrier, diff_trend, explain, missing_orders


@pytest.fixture(scope="module")
def recs(seeded):
    db, _ = seeded
    return list(db[Collections.RECONCILIATIONS].find({}, {"_id": 0}))


def _is_diff(r):
    return r["diff_type"] != "NONE"


# ── $facet ──
def test_diff_by_carrier_matches_python(seeded, recs):
    db, _ = seeded
    out = diff_by_carrier.run(db)
    want = defaultdict(lambda: {"records": 0, "diff_count": 0, "diff_amount": 0, "owed_amount": 0})
    for r in recs:
        w = want[r["carrier"]]
        w["records"] += 1
        if _is_diff(r):
            w["diff_count"] += 1
            w["diff_amount"] += r["diff"]
            w["owed_amount"] += max(r["diff"], 0)
    got = {row["carrier"]: {k: row[k] for k in ("records", "diff_count", "diff_amount", "owed_amount")}
           for row in out["by_carrier"]}
    assert got == dict(want)
    assert out["totals"]["diff_amount"] == sum(w["diff_amount"] for w in want.values())
    assert all(type(row["diff_amount"]) is int for row in out["by_carrier"])

    by_type = defaultdict(int)
    for r in recs:
        if _is_diff(r):
            by_type[(r["carrier"], r["diff_type"])] += 1
    assert {(t["carrier"], t["diff_type"]): t["diff_count"] for t in out["by_type"]} == dict(by_type)


def test_diff_by_carrier_filters(seeded, recs):
    db, ds = seeded
    last = ds["manifest"]["periods"][-1]
    out = diff_by_carrier.run(db, "carrier_b", [last])
    assert [row["carrier"] for row in out["by_carrier"]] == ["carrier_b"]
    assert out["by_carrier"][0]["records"] == sum(1 for r in recs if r["carrier"] == "carrier_b" and r["period"] == last)
    assert {p["period"] for p in out["by_period"]} == {last}


# ── $setWindowFields ──
def test_diff_trend_cumulative_and_7_days(seeded, recs):
    db, _ = seeded
    rows = diff_trend.run(db)
    daily = defaultdict(int)
    for r in recs:
        if _is_diff(r) and r.get("delivered_at"):
            daily[(r["carrier"], as_aware(r["delivered_at"]).astimezone(VN_TZ).date())] += r["diff"]
    for carrier in ("carrier_a", "carrier_b", "carrier_c"):
        mine = [row for row in rows if row["carrier"] == carrier]
        assert mine, carrier
        days = [as_aware(row["day"]).astimezone(VN_TZ).date() for row in mine]
        assert days == sorted(days)
        assert mine[-1]["cumulative_amount"] == sum(v for (c, _), v in daily.items() if c == carrier)
        for row, d in zip(mine, days):
            assert row["diff_amount"] == daily[(carrier, d)]
            assert row["amount_7d"] == sum(daily[(carrier, d - timedelta(days=k))] for k in range(7))
            assert type(row["amount_7d"]) is int


# ── $lookup ──
def test_missing_orders_match_reconcile_and_labels(seeded, recs):
    db, ds = seeded
    late_codes = {a["order_code"] for a in ds["labels"]["anomalies"] if a["injected"] == "LATE_PAYOUT"}
    total = 0
    for carrier in ("carrier_a", "carrier_b", "carrier_c"):
        for period in ds["manifest"]["periods"]:
            rows = missing_orders.run(db, carrier, period)
            sid = statement_id_for(carrier, period)
            want = {r["order_code"] for r in recs
                    if r["statement_id"] == sid and r["diff_type"] == "MISSING_IN_STATEMENT"}
            # Pipeline liệt kê mọi đơn vắng mặt (để điều tra), kể cả đơn về ở kỳ sau (late=true); bản ghi đối soát
            # chỉ tính là thiếu những đơn chưa về ở bảng kê nào.
            assert {row["order_code"] for row in rows if not row["late"]} == want, (carrier, period)
            for row in rows:
                assert row["late"] == (row["order_code"] in late_codes)
                if row["late"]:
                    assert row["other_statements"] == [statement_id_for(carrier, ds["manifest"]["periods"][
                        ds["manifest"]["periods"].index(period) + 1])]
            total += len(rows)
    assert total == ds["labels"]["summary"]["MISSING_IN_STATEMENT"] + ds["labels"]["summary"]["LATE_PAYOUT"]


# ── Sắp hết hạn khiếu nại ──
def _expiring_python(recs, hours, NOW):
    return sorted(
        r["reconciliation_id"] for r in recs
        if r["diff"] > 0 and _is_diff(r) and NOW < as_aware(r["claim_deadline_at"]) <= NOW + timedelta(hours=hours)
    )


def test_claims_expiring(seeded, recs, now):
    NOW = now
    db, _ = seeded
    out = claims_expiring.run(db, NOW, within_hours=72)
    ids = sorted(i["reconciliation_id"] for i in out["items"])
    assert ids == _expiring_python(recs, 72, NOW) and ids
    assert {c["carrier"] for c in out["by_carrier"]} == {"carrier_b", "carrier_c"}  # A còn 165 giờ
    deadlines = [i["claim_deadline_at"] for i in out["items"]]
    assert deadlines == sorted(deadlines)
    c_hours = {i["hours_left"] for i in out["items"] if i["carrier"] == "carrier_c"}
    assert c_hours == {21.0}

    # Claim đã gửi hãng thì không còn là việc cần xử lý; claim nháp vẫn hiện kèm trạng thái.
    svc = ClaimService(db, now=lambda: NOW)
    first, second = out["items"][0], out["items"][1]
    sent = svc.create_draft(first["reconciliation_id"], "manual")
    svc.approve(sent["claim_id"], "duyet")
    svc.submit(sent["claim_id"], "ke-toan")
    draft = svc.create_draft(second["reconciliation_id"], "manual")
    out2 = claims_expiring.run(db, NOW, within_hours=72)
    by_id = {i["reconciliation_id"]: i for i in out2["items"]}
    assert first["reconciliation_id"] not in by_id
    assert by_id[second["reconciliation_id"]]["claim_status"] == "DRAFT"
    assert by_id[second["reconciliation_id"]]["claim_id"] == draft["claim_id"]
    assert sum(c["without_claim"] for c in out2["by_carrier"]) == len(out2["items"]) - 1


# ── explain() và index ──
def test_statement_lines_index_compatible_with_ingest(seeded):
    """Luồng nạp của A (app/ingest/pipeline.ensure_storage) tạo index này trên cùng database: không xung đột."""
    db, _ = seeded
    db[Collections.STATEMENT_LINES].create_index([("statement_id", 1), ("order_code", 1)], unique=True,
                                                 name="statement_order_unique")
    assert db[Collections.STATEMENT_LINES].index_information()["statement_order_unique"]["unique"] is True


def test_explain_uses_indexes(seeded, tmp_path, now):
    db, ds = seeded
    summary = explain.write(explain.capture(db, "carrier_b", ds["manifest"]["periods"][-1], now), tmp_path, "test")
    assert "statement_order_unique" in summary["reconcile_lines_by_statement"]["indexes"]
    assert "carrier_delivered_at" in summary["reconcile_orders_due_in_period"]["indexes"]
    assert "carrier_delivered_at" in summary["missing_orders"]["indexes"]
    assert "order_carrier" in summary["missing_orders"]["indexes"]       # $lookup sang statement_lines
    assert "claim_deadline_diff" in summary["claims_expiring"]["indexes"]
    assert "COLLSCAN" not in summary["reconcile_lines_by_statement"]["plan"]
    assert (tmp_path / "README.md").exists() and (tmp_path / "missing_orders.json").exists()


# ── Time Series ──
def test_ingest_events_time_series(seeded):
    db, _ = seeded
    assert ensure_time_series(db) is True
    assert ensure_time_series(db) is False
    info = db.command("listCollections", filter={"name": Collections.INGEST_EVENTS})["cursor"]["firstBatch"][0]
    assert info["type"] == "timeseries"
    assert info["options"]["timeseries"]["timeField"] == "ts"
    assert info["options"]["expireAfterSeconds"] > 0


# ── core/queries.py (tầng đọc cho Streamlit) ──
def test_queries(seeded, recs, now):
    from core import queries

    db, ds = seeded
    assert queries.periods(db) == ds["manifest"]["periods"]
    rows = queries.list_reconciliations(db, carrier="carrier_b")
    assert rows and all(r["carrier"] == "carrier_b" and r["diff_type"] != "NONE" for r in rows)
    assert [r["diff"] for r in rows] == sorted((r["diff"] for r in rows), reverse=True)
    one = rows[0]
    assert queries.get_reconciliation(db, one["reconciliation_id"])["diff"] == one["diff"]
    detail = queries.order_detail(db, one["order_code"])
    assert detail["order"]["order_code"] == one["order_code"] and detail["reconciliations"]
    assert queries.diff_summary(db)["totals"]["records"] == len(recs)
    assert queries.expiring(db, now, 72)["items"]
