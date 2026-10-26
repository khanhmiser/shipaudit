"""[B] python -m generator.seed --source olist|synthetic

Hai chế độ cùng một đầu ra (contracts/schemas). Seed cố định để chạy lại ra đúng cùng dữ liệu.

Đầu ra trong generator/out/ (không commit):
- carrier_rules.json, orders.json, statement_lines.json (bảng kê đã chuẩn hóa), labels.json (đáp án),
  manifest.json (tham số chạy và số lượng).
- statements/STM-<hãng>-<kỳ>.csv: bảng kê thô theo định dạng từng hãng, dùng để nạp qua API của A.

Tùy chọn ghi Mongo (database theo MONGO_DB trong .env):
  --load       ghi carrier_rules, orders, statement_lines, tạo index
  --reset      xóa orders, statement_lines, reconciliations trước khi ghi (chỉ dùng trên database dev)
  --reconcile  chạy reconcile_statement cho mọi bảng kê vừa ghi
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path

from common.enums import Collections
from core.periods import VN_TZ, period_of, shift_period, to_db
from core.rules import rules_from_documents, upsert_rules
from generator import olist_loader, synthetic
from generator.carriers.params import carrier_rule_documents
from generator.inject import inject
from generator.orders import build_orders
from generator.statements import build_statements, statement_id_for

OUT_DIR = Path(__file__).resolve().parent / "out"
DEFAULT_BASE_DATE = "2026-10-20"


def periods_before(base_date: str, count: int) -> list[str]:
    """`count` kỳ (tuần) đã kết thúc trước tuần chứa base_date, cũ đến mới."""
    current = period_of(datetime.combine(date.fromisoformat(base_date), time(12), tzinfo=VN_TZ))
    return [shift_period(current, -k) for k in range(count, 0, -1)]


def build_dataset(
    source: str = "synthetic", seed: int = 42, n: int = 6_000, base_date: str = DEFAULT_BASE_DATE,
    periods: int = 3, olist_dir: Path | str | None = None,
) -> dict:
    rng = random.Random(seed)
    rule_docs = carrier_rule_documents()
    rules = rules_from_documents(rule_docs)
    period_list = periods_before(base_date, periods)

    if source == "olist":
        base = olist_loader.base_orders(rng, n, olist_dir or olist_loader.DEFAULT_DIR)
    else:
        base = synthetic.base_orders(rng, n)
    orders = build_orders(base, rng, rules, period_list)
    placements, anomalies = inject(orders, rules, period_list, rng)
    files, lines = build_statements(placements, period_list)

    labels = {
        "seed": seed,
        "source": source,
        "base_date": base_date,
        "periods": period_list,
        "summary": dict(sorted(Counter(a["injected"] for a in anomalies).items())),
        "anomalies": anomalies,
    }
    manifest = {
        "source": source, "seed": seed, "n": len(orders), "base_date": base_date, "periods": period_list,
        "statements": sorted({statement_id_for(c, p) for c in rules for p in period_list}),
        "counts": {
            "orders": len(orders),
            "statement_lines": len(lines),
            "anomalies": len(anomalies),
            "by_status": dict(sorted(Counter(o["status"] for o in orders).items())),
            "by_carrier": dict(sorted(Counter(o["carrier"] for o in orders).items())),
        },
    }
    return {
        "carrier_rules": rule_docs, "orders": orders, "statement_lines": lines,
        "statement_files": files, "labels": labels, "manifest": manifest,
    }


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def write_outputs(ds: dict, out_dir: Path = OUT_DIR) -> dict[str, str]:
    """Ghi file, trả về {tên file: sha256} để kiểm tra chạy lại ra cùng dữ liệu."""
    out_dir = Path(out_dir)
    (out_dir / "statements").mkdir(parents=True, exist_ok=True)
    contents = {f"{k}.json": _dump(ds[k]) for k in ("carrier_rules", "orders", "statement_lines", "labels")}
    contents.update({f"statements/{name}": text for name, text in ds["statement_files"].items()})
    digests = {}
    for name, text in sorted(contents.items()):
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
        digests[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {**ds["manifest"], "sha256": digests}
    (out_dir / "manifest.json").write_text(_dump(manifest), encoding="utf-8", newline="\n")
    return digests


def load_to_db(ds: dict, db, *, reset: bool = False) -> dict[str, int]:
    from core.indexes import ensure_indexes

    if reset:
        for name in (Collections.ORDERS, Collections.STATEMENT_LINES, Collections.RECONCILIATIONS):
            db[name].delete_many({})
    ensure_indexes(db)
    upsert_rules(db, ds["carrier_rules"])

    orders = [{**o, "delivered_at": to_db(o["delivered_at"])} for o in ds["orders"]]
    db[Collections.ORDERS].delete_many({"order_code": {"$in": [o["order_code"] for o in orders]}})
    if orders:
        db[Collections.ORDERS].insert_many(orders, ordered=False)

    lines = [{**ln, "ingested_at": to_db(ln["ingested_at"])} for ln in ds["statement_lines"]]
    db[Collections.STATEMENT_LINES].delete_many({"statement_id": {"$in": ds["manifest"]["statements"]}})
    if lines:
        db[Collections.STATEMENT_LINES].insert_many(lines, ordered=False)
    return {"carrier_rules": len(ds["carrier_rules"]), "orders": len(orders), "statement_lines": len(lines)}


def reconcile_all(ds: dict, db, now=None) -> dict[str, int]:
    from core.reconcile import reconcile_statement

    counts: Counter = Counter()
    for sid in ds["manifest"]["statements"]:
        for rec in reconcile_statement(sid, db, now=now):
            counts[rec["diff_type"]] += 1
    return dict(sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["olist", "synthetic"], default="synthetic")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=6_000, help="số đơn")
    parser.add_argument("--base-date", default=DEFAULT_BASE_DATE, help="ngày chạy giả định (YYYY-MM-DD)")
    parser.add_argument("--periods", type=int, default=3, help="số kỳ bảng kê (tuần)")
    parser.add_argument("--olist-dir", default=None)
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()

    ds = build_dataset(args.source, args.seed, args.n, args.base_date, args.periods, args.olist_dir)
    write_outputs(ds, Path(args.out))
    m = ds["manifest"]
    print(f"[seed] {m['source']} seed={m['seed']} kỳ={m['periods']} → {args.out}")
    print(f"[seed] {m['counts']}")
    print(f"[seed] chênh lệch đã cài: {ds['labels']['summary']}")

    if args.load or args.reconcile:
        from common.db import get_db

        db = get_db()
        print(f"[seed] ghi Mongo database={db.name}: {load_to_db(ds, db, reset=args.reset)}")
        if args.reconcile:
            print(f"[seed] đối soát: {reconcile_all(ds, db)}")


if __name__ == "__main__":
    main()
