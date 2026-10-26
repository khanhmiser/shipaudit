"""[B] Chuyển bộ dữ liệu `generator/out/chat_v1/` về định dạng của engine, nạp Mongo, đối soát, so với labels.json.

    python -m generator.chat_v1 --db shipaudit_b_chat_v1 --reset      # chuyển + nạp + đối soát + kiểm tra
    python -m generator.chat_v1 --check-only                          # chỉ kiểm tra định dạng và đáp án, không ghi Mongo

Bộ chat_v1 khác định dạng của generator chính ở các điểm sau (xem DATA_DICTIONARY.md của bộ):
- carrier_rules: bảng cước dạng base_g/base_fee/step_g/step_fee → mốc khối lượng `brackets` + `extra_step_g/extra_fee`;
  phụ phí dạng tỷ lệ thập phân (`insurance_pct`...) → basis point; phí hoàn cố định cho nội tỉnh → `return.flat_by_region`;
  `claim_anchor` → `claim_deadline_anchor`; `status_policy` đổi tên cờ (`cod_collected` → `collect_cod`...).
- Tên vùng `noi_mien`/`lien_mien` → `noi_vung`/`lien_vung` (tên dùng trong toàn repo).
- orders: `address_changed`/`inspected` (bool) → `address_changes` (số lần) / `inspection`.
- statement_lines: hãng không có cột bảo hiểm hoặc phí hoàn riêng (phí gộp vào tổng cước) thì bỏ khóa tương ứng,
  để classify nhận ra "phí gộp" và không coi mọi đơn hoàn là RETURN_FEE_DOUBLE.
- Kỳ bảng kê là tuần giao hàng, hãng trả tiền sau cuối kỳ `cod_payout_days` ngày (`payout_basis = period_end`).
Dữ liệu 100% tổng hợp (xem generator/out/chat_v1/DATA_NOTES.md); đáp án để kiểm tra là labels.json của bộ.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from bson import json_util

from common.enums import Collections
from core.periods import to_db
from core.rules import rules_from_documents, upsert_rules

SRC_DIR = Path(__file__).resolve().parent / "out" / "chat_v1"
REGION_MAP = {"noi_tinh": "noi_tinh", "noi_mien": "noi_vung", "lien_mien": "lien_vung"}
# Khoản trên dòng bảng kê chỉ coi là "có cột riêng" khi bảng kê gốc của hãng có cột mang tên chứa từ gợi ý.
SEPARATE_COLUMN_HINTS = {
    "insurance_fee": ("insurance", "bao_hiem"),
    "return_shipping_fee": ("return", "hoan"),
}


def _read_jsonl(path: Path) -> list[dict]:
    return [json_util.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _bp(pct) -> int:
    """Tỷ lệ thập phân (0.005) → basis point (50), không qua float."""
    return int(Decimal(str(pct)) * 10_000)


def convert_rule(doc: dict) -> dict:
    s = doc.get("surcharges") or {}
    rate_table = [
        {
            "region": REGION_MAP[r["region"]],
            "brackets": [{"max_weight_g": r["base_g"], "fee": r["base_fee"]}],
            "extra_step_g": r["step_g"],
            "extra_fee": r["step_fee"],
        }
        for r in doc["rate_table"]
    ]
    flat = s.get("return_flat_noi_tinh", 0)
    policy = {
        status: {
            "collect_cod": f["cod_collected"],
            "charge_return": f["return_fee"],
            # Đơn thất lạc không tính khoản nào; mọi trạng thái còn lại đều có cước giao hàng.
            "charge_shipping": f["cod_collected"] or f["return_fee"],
        }
        for status, f in doc["status_policy"].items()
    }
    return {
        "carrier": doc["carrier"],
        "version": doc["version"],
        "display_name": "Carrier " + doc["carrier"].removeprefix("carrier_").upper(),
        "dim_weight_divisor": doc["dim_weight_divisor"],
        "rate_table": rate_table,
        "surcharges": {
            # Làm tròn đo từ labels.json: bảo hiểm bội số 100đ (379/379 dòng), phí hoàn bội số 500đ (411/411 dòng), đều half-even.
            "insurance": {
                "rate_bp": _bp(s.get("insurance_pct", 0)), "min_declared_value": s.get("insurance_min_declared", 0),
                "round_unit": 100, "round_mode": "half_even",
            },
            "return": {
                "rate_bp": _bp(s.get("return_pct", 0)),
                "fixed": 0,
                "round_unit": 500, "round_mode": "half_even",
                **({"flat_by_region": {"noi_tinh": flat}} if flat else {}),
            },
            "storage": {"per_day": s.get("storage_per_day", 0), "free_days": s.get("storage_free_days", 0)},
            "address_change": {"fixed": s.get("address_change", 0)},
            "inspection": {"fixed": s.get("inspection", 0)},
        },
        "transfer_fee": doc.get("transfer_fee", 0),
        "transfer_fee_cod_only": True,
        "cod_payout_days": doc["cod_payout_days"],
        "claim_window_hours": doc["claim_window_hours"],
        "claim_deadline_anchor": doc.get("claim_anchor", "statement_received_at"),
        "payout_basis": doc.get("payout_basis", "delivered_plus_days"),
        "status_policy": policy,
        "updated_at": to_db(doc["updated_at"]) if doc.get("updated_at") else None,
    }


def convert_order(o: dict) -> dict:
    out = {k: v for k, v in o.items() if k not in ("address_changed", "inspected")}
    out["region"] = REGION_MAP[o["region"]]
    out["address_changes"] = 1 if o.get("address_changed") else 0
    out["inspection"] = bool(o.get("inspected"))
    if o.get("delivered_at"):  # đơn thất lạc chưa từng giao nên không có ngày giao
        out["delivered_at"] = to_db(o["delivered_at"])
    return out


def separate_columns(lines: list[dict]) -> dict[str, set[str]]:
    """Với mỗi hãng, các khoản có cột riêng trong bảng kê gốc (đọc từ khóa của `raw`)."""
    keys: dict[str, set[str]] = {}
    for ln in lines:
        keys.setdefault(ln["carrier"], set()).update(str(k).lower() for k in (ln.get("raw") or {}))
    return {
        carrier: {
            field for field, hints in SEPARATE_COLUMN_HINTS.items() if any(h in k for k in cols for h in hints)
        }
        for carrier, cols in keys.items()
    }


def convert_lines(lines: list[dict]) -> list[dict]:
    present = separate_columns(lines)
    out = []
    for ln in lines:
        row = {k: v for k, v in ln.items() if k not in ("insurance_fee", "return_shipping_fee")}
        for field in SEPARATE_COLUMN_HINTS:
            if field in present[ln["carrier"]]:
                row[field] = ln.get(field, 0)
        for key in ("ingested_at", "paid_at"):
            if row.get(key):
                row[key] = to_db(row[key])
        out.append(row)
    return out


def load_source(src: Path = SRC_DIR) -> dict:
    """Đọc bộ chat_v1 và chuyển sang định dạng engine."""
    src = Path(src)
    rules = [convert_rule(d) for d in _read_jsonl(src / "carrier_rules.jsonl")]
    for r in rules:
        if r["updated_at"] is None:
            r.pop("updated_at")
    orders = [convert_order(o) for o in _read_jsonl(src / "orders.jsonl")]
    lines = convert_lines(_read_jsonl(src / "statement_lines.jsonl"))
    events = _read_jsonl(src / "ingest_events.jsonl")
    labels = json.loads((src / "labels.json").read_text(encoding="utf-8"))
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    statements = sorted({ln["statement_id"] for ln in lines})
    return {
        "carrier_rules": rules, "orders": orders, "statement_lines": lines, "ingest_events": events,
        "labels": labels, "manifest": {**manifest, "statements": statements},
    }


def load_to_db(ds: dict, db, *, reset: bool = False) -> dict[str, int]:
    from core.indexes import ensure_indexes

    if reset:
        for name in (Collections.ORDERS, Collections.STATEMENT_LINES, Collections.RECONCILIATIONS, Collections.CLAIMS):
            db[name].delete_many({})
    ensure_indexes(db)
    upsert_rules(db, ds["carrier_rules"])
    db[Collections.ORDERS].delete_many({"order_code": {"$in": [o["order_code"] for o in ds["orders"]]}})
    db[Collections.ORDERS].insert_many(ds["orders"], ordered=False)
    db[Collections.STATEMENT_LINES].delete_many({"statement_id": {"$in": ds["manifest"]["statements"]}})
    db[Collections.STATEMENT_LINES].insert_many(ds["statement_lines"], ordered=False)
    return {k: len(ds[k]) for k in ("carrier_rules", "orders", "statement_lines")}


def load_events(ds: dict, db, *, reset: bool = False) -> int:
    """ingest_events của bộ: Time Series nếu Mongo hỗ trợ, không thì collection thường có TTL."""
    from pymongo.errors import OperationFailure

    name = Collections.INGEST_EVENTS
    if reset:
        db.drop_collection(name)
    if name not in db.list_collection_names():
        try:
            db.create_collection(
                name, timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
                expireAfterSeconds=90 * 86400,
            )
        except (OperationFailure, NotImplementedError):
            db.create_collection(name)
    docs = [{**e, "ts": to_db(e["ts"])} for e in ds["ingest_events"]]
    for i in range(0, len(docs), 1000):
        db[name].insert_many(docs[i:i + 1000], ordered=False)
    return len(docs)


def reconcile_all(ds: dict, db, now=None) -> dict[str, int]:
    from core.reconcile import reconcile_statement

    counts: Counter = Counter()
    for sid in ds["manifest"]["statements"]:
        for rec in reconcile_statement(sid, db, now=now):
            counts[rec["diff_type"]] += 1
    return dict(sorted(counts.items()))


def verify(ds: dict, db) -> dict:
    """So kết quả engine với labels.json từng (statement_id, order_code): số phải nhận, thực nhận, chênh lệch, loại."""
    got = {
        (r["statement_id"], r["order_code"]): r
        for r in db[Collections.RECONCILIATIONS].find({}, {"_id": 0})
    }
    wrong: list[dict] = []
    missing = 0
    for lab in ds["labels"]["lines"]:
        rec = got.get((lab["statement_id"], lab["order_code"]))
        if rec is None:
            missing += 1
            wrong.append({"key": (lab["statement_id"], lab["order_code"]), "why": "không có bản ghi đối soát"})
            continue
        for field in ("expected_amount", "actual_amount", "diff", "diff_type"):
            if rec[field] != lab[field]:
                wrong.append({
                    "key": (lab["statement_id"], lab["order_code"]), "field": field,
                    "engine": rec[field], "label": lab[field], "subtype": lab.get("subtype"),
                    "status": lab["status"],
                })
    expected_keys = {(x["statement_id"], x["order_code"]) for x in ds["labels"]["lines"]}
    extra = sorted(k for k in got if k not in expected_keys)
    return {
        "labels": len(ds["labels"]["lines"]), "reconciliations": len(got),
        "missing_records": missing, "extra_records": extra, "mismatches": wrong,
        "ok": not wrong and not extra,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default=str(SRC_DIR))
    parser.add_argument("--db", default=None, help="tên database (mặc định MONGO_DB trong .env)")
    parser.add_argument("--reset", action="store_true", help="xóa orders, statement_lines, reconciliations, claims, ingest_events trước khi nạp")
    parser.add_argument("--check-only", action="store_true", help="kiểm tra bằng Mongo giả trong bộ nhớ, không ghi Atlas")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ds = load_source(Path(args.src))
    rules = rules_from_documents(ds["carrier_rules"])
    print(f"[chat_v1] quy tắc hợp lệ: {sorted(rules)}; đơn {len(ds['orders'])}, dòng bảng kê {len(ds['statement_lines'])}")

    if args.check_only:
        import mongomock
        import mongomock.collection

        # pymongo ≥ 4.11 truyền thêm sort= mà mongomock 4.3 chưa nhận (giống tests/core/conftest.py).
        orig = mongomock.collection.BulkOperationBuilder.add_update
        mongomock.collection.BulkOperationBuilder.add_update = lambda self, *a, sort=None, **k: orig(self, *a, **k)
        db = mongomock.MongoClient()["chat_v1_check"]
    else:
        from common.db import get_client, get_db

        db = get_client()[args.db] if args.db else get_db()
        busy = {c: db[c].estimated_document_count() for c in (Collections.ORDERS, Collections.STATEMENT_LINES)}
        if any(busy.values()) and not args.reset:
            print(f"[chat_v1] database {db.name} đã có dữ liệu {busy}; thêm --reset để xóa và nạp lại", file=sys.stderr)
            return 2
    print(f"[chat_v1] database {db.name}: {load_to_db(ds, db, reset=args.reset or args.check_only)}")
    if not args.check_only:
        print(f"[chat_v1] ingest_events: {load_events(ds, db, reset=True)}")
    from datetime import datetime

    now = datetime.fromisoformat(ds["labels"]["meta"]["now"]) if ds["labels"]["meta"].get("now") else None
    print(f"[chat_v1] đối soát: {reconcile_all(ds, db, now=now)}")
    result = verify(ds, db)
    print(f"[chat_v1] so với labels.json: {result['labels']} dòng đáp án, {result['reconciliations']} bản ghi đối soát, "
          f"{len(result['mismatches'])} lệch, {len(result['extra_records'])} bản ghi thừa → {'KHỚP' if result['ok'] else 'CHƯA KHỚP'}")
    for m in result["mismatches"][:15]:
        print("   ", m)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
