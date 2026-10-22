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
    monkeypatch.setattr(webhooks, "claim_service", lambda d: (fake, False))
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
    assert body["action"] == "created" and body["carrier"] == "carrier_b" and body["stub"] is False
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


def test_falls_back_to_stub_until_b_claims_exist(db):
    svc, stub = webhooks.claim_service(db)
    try:
        from core.claims import ClaimService  # noqa: F401
        assert stub is False
    except ImportError:
        assert stub is True and svc.create_draft("x", "datadog_webhook", "a")["status"] == "DRAFT"


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
