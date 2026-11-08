"""Test pipeline kết quả khiếu nại (claims_outcome) trên mongomock, không cần Atlas."""
import mongomock

from pipelines import claims_outcome


def make_db():
    db = mongomock.MongoClient()["claims_outcome"]
    db.claims.insert_many([
        {"claim_id": "1", "carrier": "carrier_b", "status": "SUBMITTED", "amount": 150_000},
        {"claim_id": "2", "carrier": "carrier_b", "status": "SUBMITTED", "amount": 150_000},
        {"claim_id": "3", "carrier": "carrier_b", "status": "RECOVERED", "amount": 150_000, "recovered_amount": 140_000},
        {"claim_id": "4", "carrier": "carrier_a", "status": "REJECTED", "amount": 40_000, "note": "hãng từ chối"},
    ])
    return db


def test_groups_by_carrier_and_status():
    got = {(r["carrier"], r["status"]): r for r in claims_outcome.run(make_db())}
    assert got[("carrier_b", "SUBMITTED")] == {"carrier": "carrier_b", "status": "SUBMITTED", "count": 2,
                                                "amount": 300_000, "recovered": 0}
    assert got[("carrier_b", "RECOVERED")]["recovered"] == 140_000       # hãng hoàn thiếu 10.000
    assert got[("carrier_a", "REJECTED")]["amount"] == 40_000 and got[("carrier_a", "REJECTED")]["recovered"] == 0


def test_filter_by_carrier():
    assert {r["carrier"] for r in claims_outcome.run(make_db(), "carrier_a")} == {"carrier_a"}
    assert claims_outcome.run(mongomock.MongoClient()["empty"]) == []
