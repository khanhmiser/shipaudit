"""Test POST /webhooks/datadog (A9): secret, bỏ qua Recovered, chọn đúng khoản sắp hết hạn, idempotent theo alert id."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api import webhooks

SECRET = "test-secret"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


class FakeClaims:
    """Giống ClaimService của B ở chỗ cần test: idempotent theo (alert_id, reconciliation_id)."""

    def __init__(self):
        self.store: dict[tuple, dict] = {}

    def create_draft(self, reconciliation_id, source, alert_id=None):
        if reconciliation_id.endswith(":BAD"):
            raise ValueError("không có khoản nhận thiếu để khiếu nại")
        key = (alert_id, reconciliation_id)
        if key not in self.store:
            self.store[key] = {"claim_id": f"CLM-{len(self.store) + 1}", "status": "DRAFT", "source": source}
        return self.store[key]


def rec(code, hours, diff=5_000, carrier="carrier_b", diff_type="FEE_MISMATCH"):
    deadline = (NOW + timedelta(hours=hours)).replace(tzinfo=None)
    return {"reconciliation_id": f"STM-B-1:{code}", "statement_id": "STM-B-1", "order_code": code,
            "carrier": carrier, "diff": diff, "diff_type": diff_type, "claim_deadline_at": deadline}


@pytest.fixture
def claims(monkeypatch, db):
    fake = FakeClaims()
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(webhooks, "claim_service", lambda d: fake)
    db.reconciliations.insert_many([
        rec("B-1", 5), rec("B-2", 30), rec("B-3", 70),                 # B-3 ngoài 48 giờ
        rec("B-4", -2),                                                # đã quá hạn
        rec("B-5", 10, diff=0, diff_type="NONE"),                      # không lệch
        rec("B-6", 10, diff=-3_000),                                   # nhận thừa
        rec("A-1", 5, carrier="carrier_a"),                            # hãng khác
    ])
    return fake


def post(client, body, secret=SECRET):
    headers = {"X-ShipAudit-Secret": secret} if secret is not None else {}
    return client.post("/webhooks/datadog", json=body, headers=headers)


def test_secret_required(client, claims):
    body = {"alert_id": "a1", "scope": "carrier:carrier_b"}
    assert post(client, body, secret=None).status_code == 401
    assert post(client, body, secret="sai").status_code == 401
    assert claims.store == {}


def test_creates_drafts_for_expiring_diffs_of_carrier(client, claims):
    r = post(client, {"alert_id": "cycle-1", "alert_transition": "Triggered", "monitor_id": 72690,
                      "scope": "carrier:carrier_b", "tags": "env:dev,carrier:carrier_b"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "created" and body["carrier"] == "carrier_b"
    assert [c["reconciliation_id"] for c in body["claims"]] == ["STM-B-1:B-1", "STM-B-1:B-2"]   # gần hạn trước
    assert {k[0] for k in claims.store} == {"cycle-1"}
    assert all(v["source"] == "datadog_webhook" for v in claims.store.values())


def test_same_alert_twice_gives_same_claims(client, claims):
    body = {"alert_id": "cycle-2", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}
    first, second = post(client, body).json(), post(client, body).json()
    assert [c["claim_id"] for c in first["claims"]] == [c["claim_id"] for c in second["claims"]]
    assert len(claims.store) == 2


def test_within_hours_and_tags_list(client, claims):
    body = post(client, {"alert_id": "c3", "tags": ["env:dev", "carrier:carrier_b"], "within_hours": 96}).json()
    assert [c["reconciliation_id"] for c in body["claims"]] == ["STM-B-1:B-1", "STM-B-1:B-2", "STM-B-1:B-3"]


def test_recovered_and_no_data_are_ignored(client, claims):
    for transition in ("Recovered", "Warn Recovered", "No Data"):
        body = post(client, {"alert_id": "c4", "alert_transition": transition, "scope": "carrier:carrier_b"}).json()
        assert body["action"] == "ignored" and body["count"] == 0
    assert claims.store == {}


def test_single_reconciliation_and_errors_reported(client, claims):
    ok = post(client, {"alert_id": "c5", "reconciliation_id": "STM-B-1:B-3"}).json()
    assert ok["count"] == 1 and ok["claims"][0]["reconciliation_id"] == "STM-B-1:B-3"
    bad = post(client, {"alert_id": "c6", "reconciliation_id": "STM-B-1:BAD"}).json()
    assert bad["count"] == 0 and "không có khoản" in bad["errors"][0]


def test_payload_without_target_is_rejected(client, claims):
    assert post(client, {"alert_id": "c7", "scope": "env:dev"}).status_code == 422
    assert post(client, {"scope": "carrier:carrier_b"}).status_code == 422          # thiếu alert_id


@pytest.mark.parametrize("scope,tags,expected", [
    ("carrier:carrier_c", None, "carrier_c"),
    ("env:dev,carrier:carrier_a", None, "carrier_a"),
    (None, "monitor,carrier:carrier_b,env:dev", "carrier_b"),
    ("{carrier:carrier_b}", None, "carrier_b"),
    ("env:dev", "team:biz", None),
])
def test_carrier_from_scope_or_tags(scope, tags, expected):
    from app.api.models import DatadogAlert

    assert webhooks.carrier_of(DatadogAlert(alert_id="x", scope=scope, tags=tags)) == expected


def test_with_real_claim_service_after_merge(client, db, monkeypatch):
    """Sau khi ghép với B: claim thật được ghi vào DB, gửi lại cùng alert không nhân đôi."""
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    db.reconciliations.insert_many([rec("B-1", 5), rec("B-2", 30), rec("B-3", 70)])
    body = {"alert_id": "real-1", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}
    first, second = post(client, body).json(), post(client, body).json()
    assert first["count"] == 2 and second["count"] == 2
    assert db.claims.count_documents({}) == 2
    claim = db.claims.find_one({"reconciliation_id": "STM-B-1:B-1"})
    assert claim["status"] == "DRAFT" and claim["source"] == "datadog_webhook" and claim["alert_id"] == "real-1"
    assert claim["amount"] == 5_000


def test_follows_shipaudit_now(client, db, monkeypatch):
    """Demo ở giờ mô phỏng (SHIPAUDIT_NOW): hạn khiếu nại tính theo giờ đó, không theo giờ thật."""
    simulated = NOW - timedelta(days=8)
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SHIPAUDIT_NOW", simulated.isoformat())
    # Hạn cách giờ mô phỏng 21 giờ và 92 giờ; cả hai đã quá hạn theo giờ thật.
    db.reconciliations.insert_many([rec("B-1", -8 * 24 + 21), rec("B-2", -8 * 24 + 92)])
    body = post(client, {"alert_id": "sim-1", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}).json()
    assert body["count"] == 1 and body["errors"] == []
    assert body["claims"][0]["reconciliation_id"] == "STM-B-1:B-1"
    assert db.claims.count_documents({}) == 1


def test_events_only_for_claims_created_by_this_call(client, db, monkeypatch):
    """Datadog có thể gọi lại cùng một cảnh báo: sự kiện chỉ phát cho claim mới tạo ở lần gọi đó."""
    published = []
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(webhooks.events, "publish", lambda action, claims, **kw: published.append((action, list(claims))))
    db.reconciliations.insert_many([rec("B-1", 5), rec("B-2", 30)])
    body = {"alert_id": "ev-1", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}
    post(client, body)
    post(client, body)
    assert [(a, len(c)) for a, c in published] == [("created", 2), ("created", 0)]
    assert {c["carrier"] for c in published[0][1]} == {"carrier_b"}


def test_recovered_amounts_are_skipped(client, db, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    db.reconciliations.insert_many([rec("B-1", 5), rec("B-2", 30)])
    db.claims.insert_one({"claim_id": "CLM-OLD", "reconciliation_id": "STM-B-1:B-1", "carrier": "carrier_b",
                          "status": "RECOVERED", "amount": 5_000, "recovered_amount": 5_000})
    body = post(client, {"alert_id": "after-refund", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}).json()
    assert [c["reconciliation_id"] for c in body["claims"]] == ["STM-B-1:B-2"] and body["errors"] == []


def test_rejected_amounts_are_skipped(client, db, monkeypatch):
    """Hãng đã từ chối: webhook không tạo claim mới, doanh nghiệp tự liên hệ hãng."""
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    db.reconciliations.insert_many([rec("B-1", 5), rec("B-2", 30)])
    db.claims.insert_one({"claim_id": "CLM-REJ", "reconciliation_id": "STM-B-1:B-1", "carrier": "carrier_b",
                          "status": "REJECTED", "amount": 5_000, "note": "thiếu chứng từ"})
    body = post(client, {"alert_id": "after-reject", "alert_transition": "Triggered", "scope": "carrier:carrier_b"}).json()
    assert [c["reconciliation_id"] for c in body["claims"]] == ["STM-B-1:B-2"] and body["errors"] == []
