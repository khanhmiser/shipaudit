"""[B] Chụp explain("executionStats") các truy vấn chính vào docs/explain/.

    python -m pipelines.explain [--carrier carrier_b] [--period 2026-W42] [--now 2026-10-19T12:00:00+07:00]

Ghi mỗi truy vấn một file JSON (đã bỏ thông tin máy chủ) và docs/explain/README.md tóm tắt:
stage thắng, index dùng, số key / document đã quét so với số trả về, thời gian.
Chạy trên database theo MONGO_DB (cần có dữ liệu seed: python -m generator.seed --load --reconcile).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bson import json_util

from common.enums import Collections
from core.periods import as_aware, to_db
from core.rules import delivery_window, load_rule
from pipelines import claims_expiring, diff_by_carrier, diff_trend, missing_orders

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "explain"
DROP_KEYS = {"serverInfo", "$clusterTime", "operationTime", "signature", "command", "serverParameters"}


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in DROP_KEYS}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def _walk(x, key):
    if isinstance(x, dict):
        for k, v in x.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v, key)


def _stages(plan) -> list[str]:
    out = []
    while isinstance(plan, dict):
        if "stage" in plan:
            out.append(plan["stage"] + (f"({plan['indexName']})" if plan.get("indexName") else ""))
        plan = plan.get("inputStage") or (plan.get("inputStages") or [None])[0] or plan.get("queryPlan")
    return out


def summarize(explain: dict) -> dict:
    plans = list(_walk(explain, "winningPlan"))
    stats = next(_walk(explain, "executionStats"), {}) or {}
    # Chỉ index của kế hoạch thắng (bỏ rejectedPlans) và index mà $lookup dùng.
    indexes = sorted({n for plan in plans for n in _walk(plan, "indexName") if isinstance(n, str)}
                     | {n for lst in _walk(explain, "indexesUsed") for n in (lst or [])})
    return {
        "plan": " ← ".join(_stages(plans[0])) if plans else "",
        "indexes": indexes,
        "nReturned": stats.get("nReturned"),
        "keysExamined": stats.get("totalKeysExamined"),
        "docsExamined": stats.get("totalDocsExamined"),
        "ms": stats.get("executionTimeMillis"),
    }


def explain_find(db, coll: str, flt: dict) -> dict:
    return db.command({"explain": {"find": coll, "filter": flt}, "verbosity": "executionStats"})


def explain_aggregate(db, coll: str, pipeline: list[dict]) -> dict:
    return db.command({"explain": {"aggregate": coll, "pipeline": pipeline, "cursor": {}},
                       "verbosity": "executionStats"})


def capture(db, carrier: str, period: str, now) -> dict[str, dict]:
    rule = load_rule(db, carrier)
    start, end = delivery_window(period, rule.cod_payout_days, rule.payout_basis)
    sid = db[Collections.STATEMENT_LINES].find_one({"carrier": carrier, "period": period}, {"statement_id": 1})
    sid = sid["statement_id"] if sid else ""
    return {
        "reconcile_lines_by_statement": explain_find(db, Collections.STATEMENT_LINES, {"statement_id": sid}),
        "reconcile_orders_due_in_period": explain_find(
            db, Collections.ORDERS,
            {"carrier": carrier, "delivered_at": {"$gte": to_db(start), "$lt": to_db(end)}}),
        "diff_by_carrier": explain_aggregate(db, diff_by_carrier.COLLECTION, diff_by_carrier.pipeline(carrier, [period])),
        "diff_trend": explain_aggregate(db, diff_trend.COLLECTION, diff_trend.pipeline(carrier)),
        "missing_orders": explain_aggregate(
            db, missing_orders.COLLECTION, missing_orders.pipeline(carrier, period, rule.cod_payout_days, rule.payout_basis)),
        "claims_expiring": explain_aggregate(
            db, claims_expiring.COLLECTION, claims_expiring.pipeline(now, 72, carrier)),
    }


def write(results: dict[str, dict], out_dir: Path, note: str) -> dict[str, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, ex in results.items():
        ex = _strip(json.loads(json_util.dumps(ex)))
        (out_dir / f"{name}.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
        summary[name] = summarize(ex)
    rows = [
        f"| {n} | {s['plan'] or '-'} | {', '.join(s['indexes']) or '-'} | {s['nReturned']} | "
        f"{s['keysExamined']} | {s['docsExamined']} | {s['ms']} |"
        for n, s in summary.items()
    ]
    (out_dir / "README.md").write_text(
        "# explain() các truy vấn chính\n\n"
        f"{note}\n\nTạo bằng `python -m pipelines.explain`. File JSON đầy đủ nằm cạnh file này. "
        "Với aggregate, số key / doc / trả về là của stage đọc đầu tiên ($cursor), trước $group / $lookup; "
        "cột Index gồm cả index mà $lookup dùng.\n\n"
        "| Truy vấn | Kế hoạch thắng (stage ← input) | Index dùng | Trả về | Key đã quét | Doc đã quét | ms |\n"
        "|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    from common.db import get_db

    parser = argparse.ArgumentParser()
    parser.add_argument("--carrier", default="carrier_b")
    parser.add_argument("--period", default="2026-W42")
    parser.add_argument("--now", default="2026-10-19T12:00:00+07:00")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()
    db = get_db()
    counts = {c: db[c].estimated_document_count() for c in (Collections.ORDERS, Collections.STATEMENT_LINES,
                                                             Collections.RECONCILIATIONS)}
    note = (f"Database `{db.name}`, hãng `{args.carrier}`, kỳ `{args.period}`, now `{args.now}`. "
            f"Dữ liệu: {counts}.")
    summary = write(capture(db, args.carrier, args.period, as_aware(args.now)), Path(args.out), note)
    for name, s in summary.items():
        print(f"{name}: {s}")


if __name__ == "__main__":
    main()
