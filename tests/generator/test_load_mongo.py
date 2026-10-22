"""Kiểm tra script nạp bằng MongoDB giả lập (mongomock không hỗ trợ Time Series nên tách riêng)."""
from __future__ import annotations

from pathlib import Path

import mongomock
import pytest
from pymongo.errors import OperationFailure

from generator import load_mongo, seed

NOW = seed.datetime.fromisoformat(seed.DEFAULT_NOW)


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("out")
    built = seed.generate(seed=42, now=NOW, weeks=3, incident=True)
    seed.write_out(built, Path(d), 42, NOW, 3, True)
    return Path(d)


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def test_load_inserts_all_rows_and_keeps_dates(out_dir, monkeypatch):
    monkeypatch.setattr(load_mongo, "ensure_time_series", lambda db, ttl: "plain")
    db = mongomock.MongoClient().db
    counts = load_mongo.load(db, out_dir)
    for coll, fname in load_mongo.TARGETS:
        assert counts[coll] == _line_count(out_dir / fname)
    assert db.orders.find_one({"delivered_at": {"$type": "date"}}) is not None
    assert db.statement_lines.find_one()["ingested_at"].year == 2026
    # Không đụng reconciliations / claims.
    assert "reconciliations" not in db.list_collection_names() and "claims" not in db.list_collection_names()


def test_refuses_non_empty_without_reset_then_resets(out_dir, monkeypatch):
    monkeypatch.setattr(load_mongo, "ensure_time_series", lambda db, ttl: "plain")
    db = mongomock.MongoClient().db
    load_mongo.load(db, out_dir)
    with pytest.raises(SystemExit):
        load_mongo.load(db, out_dir)
    db.reconciliations.insert_one({"keep": True})
    counts = load_mongo.load(db, out_dir, reset=True)
    assert counts["orders"] == _line_count(out_dir / "orders.jsonl")  # không nhân đôi
    assert db.reconciliations.count_documents({}) == 1  # không bị xóa


class _FakeDb:
    def __init__(self, fail: bool):
        self.fail = fail
        self.calls: list = []
        self.indexes: list = []

    def list_collection_names(self):
        return []

    def create_collection(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.fail and "timeseries" in kwargs:
            raise OperationFailure("not supported", code=115)

    def __getitem__(self, name):
        outer = self

        class _C:
            def create_index(self, field, **kw):
                outer.indexes.append((field, kw))

        return _C()


def test_time_series_options():
    db = _FakeDb(fail=False)
    assert load_mongo.ensure_time_series(db, 90) == "timeseries"
    name, kw = db.calls[0]
    assert name == "ingest_events"
    assert kw["timeseries"] == {"timeField": "ts", "metaField": "meta", "granularity": "minutes"}
    assert kw["expireAfterSeconds"] == 90 * 86400


def test_time_series_fallback_to_plain_with_ttl():
    db = _FakeDb(fail=True)
    assert load_mongo.ensure_time_series(db, 30) == "plain"
    assert db.indexes == [("ts", {"expireAfterSeconds": 30 * 86400})]
