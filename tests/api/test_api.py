"""API bằng TestClient trên mongomock: /health, POST /statements, GET /reconciliations, /admin/ingest-fault."""
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from common.enums import Collections


# ── /health ──
def test_health_ok(client):
    assert client.get("/health").json() == {"status": "ok", "mongo": "ok"}


def test_health_503_when_mongo_down(client):
    from app.deps import get_db
    from app.main import app

    class Admin:
        def command(self, name):
            raise ServerSelectionTimeoutError("no servers")

    class Client:
        admin = Admin()

    class DownDb:
        client = Client()

    app.dependency_overrides[get_db] = lambda: DownDb()
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "mongo": "ServerSelectionTimeoutError"}


# ── POST /statements ──
@pytest.mark.parametrize("carrier", ["carrier_a", "carrier_b", "carrier_c"])
def test_upload_sample(upload, db, carrier):
    r = upload(carrier)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "OK" and body["rows"] == 4 and body["skipped"] == 0 and body["carrier"] == carrier
    assert db[Collections.STATEMENT_LINES].count_documents({"statement_id": body["statement_id"]}) == 4
    assert db[Collections.INGEST_EVENTS].count_documents({}) == 1
    assert db[Collections.RECONCILIATIONS].count_documents({}) >= 1


def test_upload_twice_no_duplicate(upload, db):
    a, b = upload().json(), upload().json()
    assert a["statement_id"] == b["statement_id"]
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 4


def test_upload_with_period_and_statement_id(upload):
    assert upload(period="2026-W42").json()["statement_id"] == "STM-A-2026W42"
    assert upload(statement_id="STM-A-X1").json()["statement_id"] == "STM-A-X1"
    assert upload(period="tuan 42").status_code == 422
    assert upload(statement_id="../etc").status_code == 422


def test_upload_partial(upload):
    raw = b"tracking,cod,total_fee,note,net\nC-1,100,10,,90\nC-2,1x0,10,,90\n"
    r = upload("carrier_c", raw=raw)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "PARTIAL" and body["skipped"] == 1 and body["errors"][0].startswith("dòng 3")


def test_upload_wrong_header_422(upload, db):
    r = upload("carrier_b", raw=b"ma;thu_ho\nB-1;1\n")
    assert r.status_code == 422 and r.json()["status"] == "ERROR" and r.json()["error_kind"] == "format"
    assert db[Collections.STATEMENT_LINES].count_documents({}) == 0


def test_upload_bad_input(client, upload):
    assert upload("carrier_x", raw=b"x,y\n1,2\n").status_code == 422  # mã hãng lạ
    assert upload(raw=b"   ").status_code == 422  # file rỗng
    assert client.post("/statements", data={"carrier": "carrier_a"}).status_code == 422  # thiếu file


# ── GET /reconciliations ──
@pytest.fixture
def recs(db):
    docs = [
        {"statement_id": "S1", "order_code": "A-1", "carrier": "carrier_a", "expected_amount": 100,
         "actual_amount": 90, "diff": 10, "diff_type": "FEE_MISMATCH", "period": "2026-W42"},
        {"statement_id": "S1", "order_code": "A-2", "carrier": "carrier_a", "expected_amount": 100,
         "actual_amount": 100, "diff": 0, "diff_type": "NONE"},
        {"statement_id": "S2", "order_code": "B-1", "carrier": "carrier_b", "expected_amount": 500,
         "actual_amount": 0, "diff": 500, "diff_type": "MISSING_IN_STATEMENT"},
    ]
    db[Collections.RECONCILIATIONS].insert_many([dict(d) for d in docs])
    return docs


def _codes(client, query=""):
    return [i["order_code"] for i in client.get(f"/reconciliations{query}").json()["items"]]


def test_list_reconciliations_sorted_and_filtered(client, recs):
    body = client.get("/reconciliations").json()
    assert body["count"] == 3 and body["limit"] == 100
    assert [i["order_code"] for i in body["items"]] == ["B-1", "A-1", "A-2"]  # chênh lệch lớn trước
    assert "_id" not in body["items"][0]
    assert body["items"][1]["period"] == "2026-W42"  # trường B ghi thêm vẫn trả về

    assert _codes(client, "?carrier=carrier_a") == ["A-1", "A-2"]
    assert _codes(client, "?diff_type=FEE_MISMATCH") == ["A-1"]
    assert _codes(client, "?statement_id=S2") == ["B-1"]
    assert _codes(client, "?limit=1") == ["B-1"]


def test_list_reconciliations_validation(client):
    assert client.get("/reconciliations?diff_type=WRONG").status_code == 422
    assert client.get("/reconciliations?limit=0").status_code == 422
    assert client.get("/reconciliations?limit=1001").status_code == 422
    assert client.get("/reconciliations?carrier=carrier_z").status_code == 422


# ── /admin/ingest-fault ──
def test_fault_get_set_reset(client):
    assert client.get("/admin/ingest-fault").json() == {"delay_ms": 0, "fail_rate": 0.0}
    assert client.post("/admin/ingest-fault", json={"delay_ms": 300}).json() == {"delay_ms": 300, "fail_rate": 0.0}
    assert client.post("/admin/ingest-fault", json={"fail_rate": 0.5}).json() == {"delay_ms": 300, "fail_rate": 0.5}
    assert client.post("/admin/ingest-fault/reset").json() == {"delay_ms": 0, "fail_rate": 0.0}
    assert client.post("/admin/ingest-fault", json={"fail_rate": 2}).status_code == 422
    assert client.post("/admin/ingest-fault", json={"delay_ms": -1}).status_code == 422


def test_fault_delay_raises_lag(client, upload, db, capsys):
    base = upload().json()["lag_seconds"]
    client.post("/admin/ingest-fault", json={"delay_ms": 300})
    slow = upload(statement_id="STM-A-SLOW").json()
    assert slow["status"] == "OK" and slow["lag_seconds"] >= 0.3 > base
    assert db[Collections.INGEST_EVENTS].find_one({"meta.statement_id": "STM-A-SLOW"})["lag_seconds"] >= 0.3
    assert "shipaudit.ops.ingest_lag_seconds" in capsys.readouterr().out  # chưa có Agent: in ra console


def test_fault_fail_rate_503(client, upload, db):
    client.post("/admin/ingest-fault", json={"fail_rate": 1})
    r = upload()
    assert r.status_code == 503 and r.json()["error_kind"] == "fault"
    assert db[Collections.INGEST_EVENTS].find_one()["status"] == "ERROR"
    client.post("/admin/ingest-fault/reset")
    assert upload().status_code == 201


def test_admin_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    assert client.get("/admin/ingest-fault").status_code == 401
    assert client.get("/admin/ingest-fault", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert client.get("/admin/ingest-fault", headers={"X-Admin-Token": "s3cret"}).status_code == 200
