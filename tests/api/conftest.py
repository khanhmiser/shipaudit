"""Fixture cho test API: TestClient với MongoDB giả (mongomock), thư mục upload tạm, công tắc lỗi tắt.

Kèm vá nhỏ cho mongomock khi chạy với pymongo mới (giống tests/ingest/conftest.py): pymongo ≥ 4.11 truyền
thêm `sort=` vào BulkOperationBuilder.add_update, mongomock 4.3 chưa nhận tham số này.
"""
from pathlib import Path

import mongomock
import mongomock.collection
import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "samples"

_orig_add_update = mongomock.collection.BulkOperationBuilder.add_update


def _add_update(self, *args, sort=None, **kwargs):
    return _orig_add_update(self, *args, **kwargs)


if not getattr(mongomock.collection.BulkOperationBuilder.add_update, "_shipaudit_patched", False):
    _add_update._shipaudit_patched = True
    mongomock.collection.BulkOperationBuilder.add_update = _add_update


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True).db


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    from app.deps import get_db
    from app.ingest import faults, pipeline
    from app.main import app

    monkeypatch.setattr(pipeline, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    faults.reset()
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
    faults.reset()


@pytest.fixture
def upload(client):
    def _upload(carrier="carrier_a", raw=None, **form):
        raw = raw if raw is not None else (SAMPLES / f"statement_{carrier}.csv").read_bytes()
        return client.post("/statements", data={"carrier": carrier, **form},
                           files={"file": (f"statement_{carrier}.csv", raw, "text/csv")})
    return _upload
