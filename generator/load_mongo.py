"""[B] Nạp dữ liệu trong generator/out/ vào MongoDB.

    python -m generator.load_mongo                      # dùng MONGO_URI / MONGO_DB trong .env
    python -m generator.load_mongo --db shipaudit_b_dev # chọn database
    python -m generator.load_mongo --reset              # xóa 4 collection dữ liệu rồi nạp lại

Chỉ đụng 4 collection: carrier_rules, orders, statement_lines, ingest_events.
KHÔNG đụng reconciliations và claims (đó là kết quả engine sinh ra).
Mặc định từ chối nếu collection đích đã có dữ liệu; cần --reset để xóa trước khi nạp.
ingest_events được tạo dạng Time Series (timeField=ts, metaField=meta) kèm TTL.
Không in mật khẩu trong URI ra màn hình.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bson import json_util

from common.enums import Collections

OUT_DIR = Path(__file__).resolve().parent / "out"

# (collection, tên file)
TARGETS = (
    (Collections.CARRIER_RULES, "carrier_rules.jsonl"),
    (Collections.ORDERS, "orders.jsonl"),
    (Collections.STATEMENT_LINES, "statement_lines.jsonl"),
    (Collections.INGEST_EVENTS, "ingest_events.jsonl"),
)
CHUNK = 1000


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json_util.loads(line) for line in f if line.strip()]


def ensure_time_series(db, ttl_days: int) -> str:
    """Tạo ingest_events dạng Time Series. Trả về 'timeseries', 'plain' (dự phòng) hoặc 'exists'."""
    from pymongo.errors import OperationFailure

    if Collections.INGEST_EVENTS in db.list_collection_names():
        return "exists"
    try:
        db.create_collection(
            Collections.INGEST_EVENTS,
            timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
            expireAfterSeconds=ttl_days * 86400,
        )
        return "timeseries"
    except OperationFailure as exc:
        # Cụm không hỗ trợ Time Series: dùng collection thường + TTL index để vẫn chạy được.
        print(f"Cảnh báo: không tạo được Time Series ({exc.code}); dùng collection thường kèm TTL.", file=sys.stderr)
        db.create_collection(Collections.INGEST_EVENTS)
        db[Collections.INGEST_EVENTS].create_index("ts", expireAfterSeconds=ttl_days * 86400)
        return "plain"


def load(db, directory: Path = OUT_DIR, reset: bool = False, ttl_days: int = 90) -> dict[str, int]:
    docs = {coll: read_jsonl(directory / fname) for coll, fname in TARGETS}

    existing = {coll: db[coll].estimated_document_count() for coll, _ in TARGETS if coll in db.list_collection_names()}
    busy = {c: n for c, n in existing.items() if n > 0}
    if busy and not reset:
        raise SystemExit(
            f"Collection đích đã có dữ liệu: {busy}. Chạy lại với --reset nếu muốn xóa và nạp lại."
        )
    if reset:
        for coll, _ in TARGETS:
            if coll == Collections.INGEST_EVENTS:
                db.drop_collection(coll)  # tạo lại đúng dạng Time Series
            else:
                db[coll].delete_many({})

    ensure_time_series(db, ttl_days)
    counts: dict[str, int] = {}
    for coll, _ in TARGETS:
        items = docs[coll]
        for i in range(0, len(items), CHUNK):
            db[coll].insert_many(items[i : i + CHUNK], ordered=False)
        counts[coll] = db[coll].count_documents({})
        if counts[coll] != len(items):
            raise SystemExit(f"{coll}: đã nạp {counts[coll]} khác {len(items)} dòng trong file.")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", help="Mặc định lấy MONGO_URI từ .env")
    parser.add_argument("--db", help="Mặc định lấy MONGO_DB từ .env")
    parser.add_argument("--dir", type=Path, default=OUT_DIR)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--ttl-days", type=int, default=90)
    args = parser.parse_args(argv)

    from pymongo import MongoClient
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

    from common import config

    uri = args.uri or config.MONGO_URI
    name = args.db or config.MONGO_DB
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
        client.admin.command("ping")
        counts = load(client[name], args.dir, args.reset, args.ttl_days)
    except ServerSelectionTimeoutError:
        print(
            "Không kết nối được MongoDB. Với Atlas: kiểm tra Network Access (thêm IP máy bạn), "
            "tên/mật khẩu user và chuỗi MONGO_URI.",
            file=sys.stderr,
        )
        return 1
    except PyMongoError as exc:
        print(f"Lỗi MongoDB: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Đã nạp vào database '{name}':")
    for coll, n in counts.items():
        print(f"  {coll}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
