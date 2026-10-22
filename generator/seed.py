"""[B] python -m generator.seed --source synthetic

Sinh dữ liệu ShipAudit vào generator/out/ (JSONL dạng Extended JSON, nạp được bằng load_mongo.py
hoặc mongoimport). Seed cố định + `--now` cố định để chạy lại ra đúng cùng dữ liệu.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from generator import inject, statements, synthetic
from generator.carriers.params import CARRIER_PARAMS, STATUS_POLICY
from generator.synthetic import VN_TZ

DEFAULT_NOW = "2026-10-23T08:00:00+07:00"
DEFAULT_OUT = Path(__file__).resolve().parent / "out"


def _encode(obj):
    if isinstance(obj, datetime):
        return {"$date": obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    raise TypeError(type(obj))


def _write_jsonl(path: Path, docs: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False, default=_encode, separators=(",", ":")) + "\n")


def _clean_order(o: dict) -> dict:
    return {k: v for k, v in o.items() if not k.startswith("_") and v is not None}


def _rule_docs(now: datetime) -> list[dict]:
    docs = []
    for carrier in sorted(CARRIER_PARAMS):
        p = {k: v for k, v in CARRIER_PARAMS[carrier].items() if k != "prefix"}
        docs.append(
            {
                "carrier": carrier,
                **p,
                "claim_anchor": "statement_received_at",  # chờ chốt; trường mở rộng
                "payout_basis": "period_end",  # cod_payout_days tính từ cuối kỳ
                "status_policy": STATUS_POLICY,  # chờ chốt
                "updated_at": now,
            }
        )
    return docs


def generate(seed: int, now: datetime, weeks: int, incident: bool) -> dict:
    rng = random.Random(seed)
    orders = synthetic.make_orders(rng, now, weeks)
    mondays = synthetic.week_starts(now, weeks)
    last_week = len(mondays) - 1
    plans = []
    for o in orders:
        plan = inject.plan_line(rng, o, last_week, incident)
        if plan is not None:
            plans.append(plan)
    built = statements.build_statements(rng, orders, plans, mondays, now)
    built["orders"] = [_clean_order(o) for o in orders]
    built["rules"] = _rule_docs(now)
    built["mondays"] = mondays
    return built


def summarize(built: dict) -> dict:
    labels = built["labels"]
    by_carrier: dict[str, Counter] = {}
    for lb in labels:
        by_carrier.setdefault(lb["carrier"], Counter())[lb["diff_type"]] += 1
    total_loss = sum(lb["diff"] for lb in labels if lb["diff"] > 0)
    return {
        "orders": len(built["orders"]),
        "statement_lines": len(built["lines"]),
        "statements": len(built["meta"]),
        "ingest_events": len(built["events"]),
        "lost_orders_excluded": len(built["excluded"]),
        "diff_type_counts": dict(Counter(lb["diff_type"] for lb in labels)),
        "diff_type_by_carrier": {c: dict(v) for c, v in sorted(by_carrier.items())},
        "incident_lines": sum(1 for lb in labels if lb["incident"]),
        "total_underpaid_vnd": total_loss,
    }


def write_out(built: dict, out: Path, seed: int, now: datetime, weeks: int, incident: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    _write_jsonl(out / "carrier_rules.jsonl", built["rules"])
    _write_jsonl(out / "orders.jsonl", built["orders"])
    _write_jsonl(out / "statement_lines.jsonl", built["lines"])
    _write_jsonl(out / "ingest_events.jsonl", built["events"])
    for name, text in built["raw_files"].items():
        (raw_dir / name).write_text(text, encoding="utf-8", newline="\n")
    summary = summarize(built)
    labels_doc = {
        "meta": {
            "seed": seed,
            "now": now.isoformat(),
            "weeks": weeks,
            "incident": incident,
            "note": "Dữ liệu tổng hợp. expected_amount = số tiền phải nhận; diff = phải nhận - thực nhận.",
        },
        "summary": summary,
        "lines": built["labels"],
        "excluded": built["excluded"],
    }
    (out / "labels.json").write_text(json.dumps(labels_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {"seed": seed, "now": now.isoformat(), "weeks": weeks, "incident": incident, **summary}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["olist", "synthetic"], default="synthetic")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--now", default=DEFAULT_NOW, help="Mốc 'bây giờ' của bộ dữ liệu (ISO 8601).")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--no-incident", action="store_true", help="Tắt kịch bản sự cố Carrier C kỳ mới nhất.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.source == "olist":
        print("--source olist chưa được cài (cần file Olist và xác minh giấy phép). Dùng --source synthetic.", file=sys.stderr)
        return 2

    now = datetime.fromisoformat(args.now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=VN_TZ)
    built = generate(args.seed, now, args.weeks, not args.no_incident)
    manifest = write_out(built, args.out, args.seed, now, args.weeks, not args.no_incident)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
