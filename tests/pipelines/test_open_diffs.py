"""Test pipeline open_diffs và job metric trên dữ liệu seed thật (Atlas), so với cách tính độc lập bằng Python."""
from collections import defaultdict
from datetime import timedelta

from common.enums import Collections
from core import metrics_job
from core.claims import ClaimService
from core.periods import as_aware, to_db
from pipelines import open_diffs
from pipelines.claims_expiring import CLOSED_CLAIM_STATUSES


def _bucket(hours):
    if hours <= 0:
        return "expired"
    if hours < 24:
        return "lt24h"
    if hours < 48:
        return "lt48h"
    if hours < 96:
        return "lt96h"
    return "later"


def _python_buckets(db, now):
    closed = {c["reconciliation_id"] for c in db[Collections.CLAIMS].find({"status": {"$in": CLOSED_CLAIM_STATUSES}})}
    want = defaultdict(lambda: [0, 0])
    nearest = {}
    for r in db[Collections.RECONCILIATIONS].find({"diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"}}):
        if r["reconciliation_id"] in closed:
            continue
        hours = (as_aware(r["claim_deadline_at"]) - now).total_seconds() / 3600
        w = want[(r["carrier"], r["diff_type"], _bucket(hours))]
        w[0] += 1
        w[1] += r["diff"]
        if hours > 0:
            nearest[r["carrier"]] = min(nearest.get(r["carrier"], hours), hours)
    return want, nearest


def test_open_diffs_matches_python(seeded, now):
    db, _ = seeded
    out = open_diffs.run(db, now)
    want, nearest = _python_buckets(db, now)
    got = {(b["carrier"], b["diff_type"], b["deadline"]): [b["count"], b["amount"]] for b in out["buckets"]}
    assert got == dict(want)
    assert {n["carrier"]: n["min_hours_left"] for n in out["nearest"]} == {c: round(h, 2) for c, h in nearest.items()}
    # Ngay sau khi nhận bảng kê kỳ mới phải có khoản còn trong hạn, và có cả khoản đã quá hạn từ kỳ cũ.
    assert {k[2] for k in got} & {"lt24h", "lt48h", "lt96h", "later"}
    assert any(k[2] == "expired" for k in got)


def test_collect_totals_match_pipeline(seeded, now):
    db, _ = seeded
    points = metrics_job.collect(db, now)
    want, _ = _python_buckets(db, now)
    amount = sum(p.value for p in points if p.name == metrics_job.DIFF_AMOUNT)
    count = sum(p.value for p in points if p.name == metrics_job.DIFF_COUNT)
    assert amount == sum(v[1] for v in want.values())
    assert count == sum(v[0] for v in want.values())
    assert {p.tags["carrier"] for p in points} == {"carrier_a", "carrier_b", "carrier_c"}


def test_submitted_claim_leaves_open_metrics_and_time_moves_buckets(seeded, now):
    db, _ = seeded
    with_claim = set(db[Collections.CLAIMS].distinct("reconciliation_id"))
    rec = next(r for r in db[Collections.RECONCILIATIONS].find(
        {"diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"}, "claim_deadline_at": {"$gt": to_db(now)}},
        sort=[("claim_deadline_at", 1)]) if r["reconciliation_id"] not in with_claim)
    before = metrics_job.summary(metrics_job.collect(db, now))[rec["carrier"]]

    svc = ClaimService(db, now=lambda: now)
    draft = svc.create_draft(rec["reconciliation_id"], "manual")
    try:
        assert metrics_job.summary(metrics_job.collect(db, now))[rec["carrier"]] == before  # nháp vẫn là việc cần làm
        svc.approve(draft["claim_id"], "duyet")
        svc.submit(draft["claim_id"], "ke-toan")
        after = metrics_job.summary(metrics_job.collect(db, now))[rec["carrier"]]
        assert after["open_amount"] == before["open_amount"] - rec["diff"]
        assert after["open_count"] == before["open_count"] - 1
    finally:
        db[Collections.CLAIMS].delete_one({"claim_id": draft["claim_id"]})  # dữ liệu seed dùng chung với test khác

    # Sau khi mọi hạn đã qua, không còn khoản nào trong hạn và claim_hours_left về mức chặn trên.
    late = now + timedelta(days=30)
    s = metrics_job.summary(metrics_job.collect(db, late))
    assert all(v["open_amount"] == 0 and v["claim_hours_left"] == metrics_job.HOURS_CAP for v in s.values())
