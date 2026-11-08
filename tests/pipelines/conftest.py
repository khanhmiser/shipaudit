"""Dữ liệu seed cho test pipeline, chạy trên MongoDB thật (Atlas theo MONGO_URI trong .env).

mongomock không có $setWindowFields và explain(), nên các test này cần Mongo thật. Database riêng
`<MONGO_DB>_test`, seed cố định, xóa các collection sau khi chạy
(người dùng Atlas chỉ có quyền đọc ghi, không được dropDatabase). Không kết nối được (hoặc đặt SHIPAUDIT_SKIP_ATLAS=1)
thì bỏ qua.
"""
import os
from datetime import datetime

import pytest
from pymongo import MongoClient

from common import config
from core.indexes import ensure_indexes
from core.periods import VN_TZ
from generator.seed import build_dataset, load_to_db, reconcile_all

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=VN_TZ)  # sau khi nhận bảng kê kỳ W42 (9:00 19/10)
SEED, N = 7, 1_500


@pytest.fixture(scope="session")
def seeded():
    if os.getenv("SHIPAUDIT_SKIP_ATLAS") == "1":
        pytest.skip("SHIPAUDIT_SKIP_ATLAS=1")
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=8_000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"không kết nối được MongoDB: {type(e).__name__}")
    name = f"{config.MONGO_DB}_test"
    assert name.endswith("_test")
    db = client[name]
    _drop_all(db)
    ds = build_dataset("synthetic", seed=SEED, n=N)
    load_to_db(ds, db, reset=True)
    ensure_indexes(db)
    reconcile_all(ds, db, now=NOW)
    yield db, ds
    _drop_all(db)
    client.close()


@pytest.fixture(scope="session")
def now():
    return NOW


def _drop_all(db):
    for coll in db.list_collection_names():
        db.drop_collection(coll)
