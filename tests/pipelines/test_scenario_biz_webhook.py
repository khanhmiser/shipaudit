"""Test chế độ `--webhook real` của kịch bản nghiệp vụ: chờ claim do webhook thật tạo (mongomock, không cần Atlas)."""
from datetime import datetime

import mongomock
import pytest

from scenarios.biz import run as scenario

NOW = datetime(2026, 10, 22, 13, 0, tzinfo=scenario.VN_TZ)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(scenario, "hold", lambda *a, **k: {})  # không phát metric
    return mongomock.MongoClient()["scn_webhook"]


def webhook_claim(carrier="carrier_b", source="datadog_webhook", claim_id="CLM-1"):
    return {"claim_id": claim_id, "carrier": carrier, "source": source, "alert_id": "cycle-1"}


def test_returns_claims_created_while_waiting(db):
    polls = []

    def sleep(_):  # webhook "gọi về" trong lúc chờ
        db.claims.insert_one(webhook_claim())

    got = scenario.wait_for_webhook(db, None, NOW, minutes=5, interval=1, on_poll=lambda: polls.append(1), sleep=sleep)
    assert [c["claim_id"] for c in got] == ["CLM-1"] and got[0]["alert_id"] == "cycle-1"
    assert len(polls) == 1


def test_gives_up_when_nothing_arrives(db):
    assert scenario.wait_for_webhook(db, None, NOW, minutes=0, interval=1, sleep=lambda s: None) == []


def test_ignores_other_carriers_and_manual_claims(db):
    db.claims.insert_many([webhook_claim("carrier_a", claim_id="A"), webhook_claim(source="manual", claim_id="M")])
    assert scenario.webhook_claims(db) == []


def _submitted(db, n=3, amount=150_000):
    db.claims.insert_many([{"claim_id": f"C{i}", "carrier": "carrier_b", "status": "SUBMITTED", "amount": amount,
                            "history": []} for i in range(n)])
    return [f"C{i}" for i in range(n)]


def test_recover_claims_records_full_refund(db):
    ids = _submitted(db)
    db.claims.insert_one({"claim_id": "D", "carrier": "carrier_b", "status": "DRAFT", "amount": 1, "history": []})
    assert scenario.recover_claims(db, NOW, ids + ["D"], "ke-toan") == (3, 450_000)       # bản nháp không bị đụng
    got = {c["claim_id"]: c for c in db.claims.find()}
    assert all(got[i]["status"] == "RECOVERED" and got[i]["recovered_amount"] == 150_000 for i in ids)
    assert got["D"]["status"] == "DRAFT"
    assert scenario.recover_claims(db, NOW, ids, "ke-toan") == (0, 0)                      # gọi lại không nhân đôi


def test_wait_for_recovery_ends_when_user_records_refunds(db):
    ids = _submitted(db, 2)

    def sleep(_):  # người dùng ghi nhận trên giao diện
        db.claims.update_many({}, {"$set": {"status": "RECOVERED"}})

    assert scenario.wait_for_recovery(db, ids, 300, 1, sleep=sleep) == 0
    assert scenario.wait_for_recovery(db, ["X"], 0, 1, sleep=lambda s: None) == 0          # không có claim nào chờ
