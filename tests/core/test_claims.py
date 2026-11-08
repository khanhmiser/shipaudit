"""Kiểm tra core/claims.ClaimService trên Mongo giả: vòng đời claim, idempotent, chặn quá hạn."""
from datetime import datetime, timedelta

import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from contracts.interfaces import ClaimService as ClaimServiceProtocol
from core.claims import ClaimError, ClaimService
from core.indexes import ensure_indexes
from core.periods import VN_TZ, to_db

T0 = datetime(2026, 10, 22, 9, 0, tzinfo=VN_TZ)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def rec(code, diff, diff_type="FEE_MISMATCH", hours=24, carrier="carrier_b"):
    sid = "STM-B-2026W42"
    return {"reconciliation_id": f"{sid}:{code}", "statement_id": sid, "order_code": code, "carrier": carrier,
            "diff": diff, "diff_type": diff_type, "expected_amount": 100_000, "actual_amount": 100_000 - diff,
            "claim_deadline_at": to_db(T0 + timedelta(hours=hours))}


@pytest.fixture
def env():
    db = mongomock.MongoClient().db
    ensure_indexes(db)
    db.reconciliations.insert_many([
        rec("B-1", 5_000), rec("B-2", 12_000, "RETURN_FEE_DOUBLE", hours=10), rec("B-3", 0, "NONE"),
        rec("B-4", -3_000), rec("B-5", 7_000, hours=-1), rec("B-6", 9_000, hours=100),
        rec("A-1", 4_000, carrier="carrier_a"),
    ])
    clock = Clock(T0)
    return db, ClaimService(db, now=clock), clock


def rid(code):
    return f"STM-B-2026W42:{code}"


def test_matches_contract_protocol(env):
    assert isinstance(env[1], ClaimServiceProtocol)


def test_create_draft(env):
    db, svc, _ = env
    c = svc.create_draft(rid("B-1"), "manual")
    assert c["status"] == "DRAFT" and c["amount"] == 5_000 and c["carrier"] == "carrier_b"
    assert c["claim_id"].startswith("CLM-") and "alert_id" not in c
    assert c["history"][0]["status"] == "DRAFT"
    assert db.claims.count_documents({}) == 1


def test_same_alert_twice_gives_one_claim(env):
    db, svc, _ = env
    a = svc.create_draft(rid("B-1"), "datadog_webhook", alert_id="alert-123")
    b = svc.create_draft(rid("B-1"), "datadog_webhook", alert_id="alert-123")
    assert a["claim_id"] == b["claim_id"] and db.claims.count_documents({}) == 1


def test_one_open_claim_per_reconciliation(env):
    db, svc, _ = env
    manual = svc.create_draft(rid("B-1"), "manual")
    again = svc.create_draft(rid("B-1"), "manual")
    from_alert = svc.create_draft(rid("B-1"), "datadog_webhook", alert_id="alert-9")
    assert manual["claim_id"] == again["claim_id"] == from_alert["claim_id"]
    assert db.claims.count_documents({}) == 1


def test_unique_index_blocks_duplicate_alert(env):
    db, svc, _ = env
    c = svc.create_draft(rid("B-1"), "datadog_webhook", alert_id="alert-1")
    with pytest.raises(DuplicateKeyError):
        db.claims.insert_one({"claim_id": "X", "alert_id": "alert-1", "reconciliation_id": c["reconciliation_id"]})


@pytest.mark.parametrize("code", ["B-3", "B-4"], ids=["no_diff", "overpaid"])
def test_nothing_to_claim(env, code):
    with pytest.raises(ClaimError):
        env[1].create_draft(rid(code), "manual")


def test_invalid_inputs(env):
    _, svc, _ = env
    with pytest.raises(ClaimError):
        svc.create_draft(rid("NOPE"), "manual")
    with pytest.raises(ClaimError):
        svc.create_draft(rid("B-1"), "email")
    with pytest.raises(ClaimError):
        svc.create_draft(rid("B-5"), "manual")  # đã quá hạn


def test_full_lifecycle_recovered(env):
    _, svc, clock = env
    c = svc.create_draft(rid("B-1"), "manual")
    with pytest.raises(ClaimError):
        svc.submit(c["claim_id"], "ke-toan")  # chưa duyệt thì không gửi được
    with pytest.raises(ClaimError):
        svc.approve(c["claim_id"], "  ")
    clock.t = T0 + timedelta(hours=1)
    c = svc.approve(c["claim_id"], "Nguyen Van Duyet")
    assert c["status"] == "APPROVED" and c["approved_by"] == "Nguyen Van Duyet"
    with pytest.raises(ClaimError):
        svc.approve(c["claim_id"], "nguoi khac")
    c = svc.submit(c["claim_id"], "ke-toan")
    assert c["status"] == "SUBMITTED"
    with pytest.raises(ClaimError):
        svc.mark_recovered(c["claim_id"], 4_500.0, "ke-toan")
    c = svc.mark_recovered(c["claim_id"], 5_000, "ke-toan")
    assert c["status"] == "RECOVERED" and c["recovered_amount"] == 5_000
    assert [h["status"] for h in c["history"]] == ["DRAFT", "APPROVED", "SUBMITTED", "RECOVERED"]


def test_rejected(env):
    _, svc, _ = env
    c = svc.create_draft(rid("B-1"), "manual")
    svc.approve(c["claim_id"], "duyet")
    svc.submit(c["claim_id"], "ke-toan")
    c = svc.mark_rejected(c["claim_id"], "ke-toan", "hãng không chấp nhận")
    assert c["status"] == "REJECTED" and c["note"] == "hãng không chấp nhận"


def test_cannot_approve_after_deadline_and_expire(env):
    db, svc, clock = env
    short = svc.create_draft(rid("B-2"), "manual")      # hạn sau 10 giờ
    sent = svc.create_draft(rid("B-1"), "manual")       # hạn sau 24 giờ
    svc.approve(sent["claim_id"], "duyet")
    svc.submit(sent["claim_id"], "ke-toan")
    clock.t = T0 + timedelta(hours=11)
    with pytest.raises(ClaimError):
        svc.approve(short["claim_id"], "duyet")
    assert svc.expire_overdue() == 1
    assert svc.get(short["claim_id"])["status"] == "EXPIRED"
    assert svc.get(sent["claim_id"])["status"] == "SUBMITTED"   # đã gửi thì không hết hạn
    assert svc.expire_overdue() == 0


def test_create_drafts_for_carrier(env):
    db, svc, _ = env
    made = svc.create_drafts_for_carrier("carrier_b", "datadog_webhook", alert_id="alert-7", within_hours=48)
    assert sorted(c["order_code"] for c in made) == ["B-1", "B-2"]   # không lấy B-3..B-5, B-6 còn xa hạn, A-1
    again = svc.create_drafts_for_carrier("carrier_b", "datadog_webhook", alert_id="alert-7", within_hours=48)
    assert {c["claim_id"] for c in made} == {c["claim_id"] for c in again}
    assert db.claims.count_documents({}) == 2


def test_list(env):
    _, svc, clock = env
    svc.create_draft(rid("B-1"), "manual")
    clock.t = T0 + timedelta(minutes=5)
    c2 = svc.create_draft(rid("B-2"), "manual")
    svc.approve(c2["claim_id"], "duyet")
    assert [c["order_code"] for c in svc.list()] == ["B-2", "B-1"]
    assert [c["order_code"] for c in svc.list(status="APPROVED")] == ["B-2"]
    assert all("_id" not in c for c in svc.list())


def _recover(svc, code, alert_id=None):
    c = svc.create_draft(rid(code), "datadog_webhook", alert_id)
    svc.approve(c["claim_id"], "Kế toán Lan")
    svc.submit(c["claim_id"], "Kế toán Lan")
    return svc.mark_recovered(c["claim_id"], c["amount"], "Kế toán Lan")


def test_recovered_amount_is_never_claimed_again(env):
    """Hãng đã hoàn tiền: cảnh báo mới (alert khác) không được tạo claim nháp lần nữa cho khoản đó."""
    db, svc, _ = env
    done = _recover(svc, "B-1", alert_id="cycle-1")
    with pytest.raises(ClaimError, match="đã hoàn tiền"):
        svc.create_draft(rid("B-1"), "datadog_webhook", "cycle-2")
    with pytest.raises(ClaimError, match="đã hoàn tiền"):
        svc.create_draft(rid("B-1"), "manual")
    assert svc.create_draft(rid("B-1"), "datadog_webhook", "cycle-1")["claim_id"] == done["claim_id"]  # cùng alert: trả lại
    again = svc.create_drafts_for_carrier("carrier_b", "datadog_webhook", alert_id="cycle-2", within_hours=48)
    assert [c["reconciliation_id"] for c in again] == [rid("B-2")]                 # B-1 đã thu hồi thì bỏ qua
    assert db.claims.count_documents({"reconciliation_id": rid("B-1")}) == 1


def _submitted(svc, code):
    c = svc.create_draft(rid(code), "manual")
    svc.approve(c["claim_id"], "Kế toán Lan")
    return svc.submit(c["claim_id"], "Kế toán Lan")


def test_reject_requires_reason_and_is_not_claimed_again(env):
    db, svc, _ = env
    c = _submitted(svc, "B-1")
    with pytest.raises(ClaimError, match="lý do"):
        svc.mark_rejected(c["claim_id"], "Kế toán Lan", "  ")
    rejected = svc.mark_rejected(c["claim_id"], "Kế toán Lan", "thiếu ảnh biên nhận")
    assert rejected["status"] == "REJECTED" and rejected["note"] == "thiếu ảnh biên nhận"
    with pytest.raises(ClaimError, match="đã từ chối"):
        svc.create_draft(rid("B-1"), "manual")                                     # không tạo claim mới
    again = svc.create_drafts_for_carrier("carrier_b", "datadog_webhook", alert_id="cycle-9", within_hours=48)
    assert rid("B-1") not in [x["reconciliation_id"] for x in again]               # webhook cũng bỏ qua
    assert db.claims.count_documents({"reconciliation_id": rid("B-1")}) == 1


def test_followup_log_then_carrier_agrees_after_contact(env, monkeypatch):
    db, svc, clock = env
    c = _submitted(svc, "B-1")
    with pytest.raises(ClaimError, match="nội dung"):
        svc.add_followup(c["claim_id"], "Kế toán Lan", "")
    svc.add_followup(c["claim_id"], "Kế toán Lan", "Đã gửi email cho hãng")              # đang chờ phản hồi
    svc.mark_rejected(c["claim_id"], "Kế toán Lan", "thiếu ảnh biên nhận")
    next_at = T0 + timedelta(days=3)
    f = svc.add_followup(c["claim_id"], "Kế toán Lan", "Gọi hãng, gửi lại ảnh; hãng hẹn trả lời", next_at)
    assert [x["note"] for x in f["followups"]] == ["Đã gửi email cho hãng", "Gọi hãng, gửi lại ảnh; hãng hẹn trả lời"]
    assert f["next_contact_at"] == to_db(next_at) and f["followups"][-1]["by"] == "Kế toán Lan"
    done = svc.mark_recovered(c["claim_id"], 4_000, "Kế toán Lan")                       # hãng đồng ý hoàn một phần
    assert done["status"] == "RECOVERED" and done["recovered_amount"] == 4_000
    assert [h["status"] for h in done["history"]][-2:] == ["REJECTED", "RECOVERED"]
    with pytest.raises(ClaimError, match="chỉ theo dõi"):
        svc.add_followup(c["claim_id"], "Kế toán Lan", "sau khi đã thu hồi")
    draft = svc.create_draft(rid("B-2"), "manual")
    with pytest.raises(ClaimError, match="chỉ theo dõi"):
        svc.add_followup(draft["claim_id"], "Kế toán Lan", "nháp chưa gửi hãng")
