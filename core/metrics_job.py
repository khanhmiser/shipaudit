"""[B] Job định kỳ phát metric shipaudit.biz.*: diff_amount, diff_count, claim_hours_left.
Phát qua hàm metric() theo contracts.interfaces.Metrics (fallback console khi chưa có Datadog).

    python -m core.metrics_job                  # lặp mỗi 60 giây, gửi Datadog nếu có DD_API_KEY
    python -m core.metrics_job --once --sink console
    python -m core.metrics_job --now 2026-10-19T12:00:00+07:00   # xem dữ liệu seed tại một thời điểm cố định

Số liệu lấy từ pipelines/open_diffs.py (chênh lệch doanh nghiệp nhận thiếu, chưa xử lý xong):
- `shipaudit.biz.diff_amount` (VNĐ) và `shipaudit.biz.diff_count`: tag carrier, diff_type, deadline
  (expired | lt24h | lt48h | lt96h | later). Mọi tổ hợp đều được phát, không có khoản nào thì là 0,
  để đồ thị liền mạch và monitor tự về OK.
- `shipaudit.biz.claim_hours_left`: tag carrier. Số giờ còn lại tới hạn khiếu nại của khoản gần hạn nhất
  (khoản đã quá hạn không tính), chặn trên HOURS_CAP. Hãng không còn khoản nào cần xử lý thì bằng HOURS_CAP.
- `shipaudit.biz.claim_amount` (VNĐ): tag carrier, claim_status (submitted | recovered | rejected). Tiền đã khiếu nại theo
  trạng thái hiện tại của claim; `submitted` là đang chờ hãng phản hồi.
- `shipaudit.biz.recovered_amount` (VNĐ): tag carrier. Tiền hãng đã hoàn lại cho các claim đã thu hồi (cộng dồn).
LATE_PAYOUT không có tiền chênh lệch (tiền đủ, chỉ chậm) nên không nằm trong các metric tiền này.
Mốc thời gian của điểm metric là giờ thật lúc gửi; `now` chỉ dùng để tính hạn khiếu nại.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from common.enums import TAG_CARRIER, TAG_DIFF_TYPE, DiffType
from contracts.interfaces import Metrics
from core import queries
from core.periods import as_aware
from pipelines import claims_outcome, open_diffs

PREFIX = "shipaudit.biz."
DIFF_AMOUNT = PREFIX + "diff_amount"
DIFF_COUNT = PREFIX + "diff_count"
CLAIM_HOURS_LEFT = PREFIX + "claim_hours_left"
CLAIM_AMOUNT = PREFIX + "claim_amount"
RECOVERED_AMOUNT = PREFIX + "recovered_amount"
TAG_CLAIM_STATUS = "claim_status"
CLAIM_STATUSES = ("SUBMITTED", "RECOVERED", "REJECTED")  # các trạng thái claim đã gửi hãng
TAG_DEADLINE = "deadline"
HOURS_CAP = 168  # 7 ngày: thanh hạn trên giao diện cũng đầy từ mốc này
OWED_TYPES = [t.value for t in DiffType if t not in (DiffType.NONE, DiffType.LATE_PAYOUT)]

log = logging.getLogger("shipaudit.biz.metrics_job")


@dataclass(frozen=True)
class Point:
    name: str
    value: float
    tags: dict[str, str]


def collect(db: Any, now: datetime) -> list[Point]:
    """Tính các điểm metric tại thời điểm `now` (không gửi)."""
    out = open_diffs.run(db, now)
    carrier_codes = sorted({c["carrier"] for c in queries.carriers(db)}
                           | {b["carrier"] for b in out["buckets"]})
    got = {(b["carrier"], b["diff_type"], b["deadline"]): b for b in out["buckets"]}
    nearest = {n["carrier"]: n["min_hours_left"] for n in out["nearest"]}
    outcomes = {(o["carrier"], o["status"]): o for o in claims_outcome.run(db)}
    diff_types = OWED_TYPES + sorted({b["diff_type"] for b in out["buckets"]} - set(OWED_TYPES))

    points: list[Point] = []
    for carrier in carrier_codes:
        for diff_type in diff_types:
            for deadline in open_diffs.DEADLINE_BUCKETS:
                b = got.get((carrier, diff_type, deadline), {})
                tags = {TAG_CARRIER: carrier, TAG_DIFF_TYPE: diff_type, TAG_DEADLINE: deadline}
                points.append(Point(DIFF_AMOUNT, b.get("amount", 0), tags))
                points.append(Point(DIFF_COUNT, b.get("count", 0), tags))
        hours = nearest.get(carrier)
        points.append(Point(CLAIM_HOURS_LEFT, HOURS_CAP if hours is None else min(hours, HOURS_CAP),
                            {TAG_CARRIER: carrier}))
        for status in CLAIM_STATUSES:
            points.append(Point(CLAIM_AMOUNT, outcomes.get((carrier, status), {}).get("amount", 0),
                                {TAG_CARRIER: carrier, TAG_CLAIM_STATUS: status.lower()}))
        points.append(Point(RECOVERED_AMOUNT, sum(o.get("recovered", 0) for (c, _), o in outcomes.items() if c == carrier),
                            {TAG_CARRIER: carrier}))
    return points


def emit(points: list[Point], metric: Metrics) -> int:
    for p in points:
        metric(p.name, p.value, p.tags)
    flush = getattr(metric, "flush", None)
    if callable(flush):
        flush()
    return len(points)


def summary(points: list[Point]) -> dict[str, dict]:
    """Tóm tắt theo hãng để in log: tiền và số khoản còn trong hạn, đã quá hạn, giờ còn lại ngắn nhất."""
    out: dict[str, dict] = {}
    for p in points:
        s = out.setdefault(p.tags[TAG_CARRIER], {"open_amount": 0, "open_count": 0, "expired_amount": 0})
        expired = p.tags.get(TAG_DEADLINE) == "expired"
        if p.name == DIFF_AMOUNT:
            s["expired_amount" if expired else "open_amount"] += p.value
        elif p.name == DIFF_COUNT and not expired:
            s["open_count"] += p.value
        elif p.name == CLAIM_HOURS_LEFT:
            s["claim_hours_left"] = p.value
    return out


def run_once(db: Any, metric: Metrics, now: datetime | None = None) -> list[Point]:
    points = collect(db, now or datetime.now(timezone.utc))
    emit(points, metric)
    return points


def run_forever(db: Any, metric: Metrics, interval: float, now_fn: Callable[[], datetime],
                sleep: Callable[[float], None] = time.sleep, max_runs: int | None = None) -> None:
    """Lặp mỗi `interval` giây. Lỗi một lượt (mạng, Datadog) thì ghi log rồi chạy tiếp lượt sau."""
    runs = 0
    while max_runs is None or runs < max_runs:
        started = time.monotonic()
        try:
            points = run_once(db, metric, now_fn())
            log.info("phát %d điểm metric: %s", len(points), summary(points))
        except Exception as e:  # noqa: BLE001
            log.error("lượt phát metric lỗi: %s", e)
        runs += 1
        if max_runs is None or runs < max_runs:
            sleep(max(0.0, interval - (time.monotonic() - started)))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # pipe trên Windows mặc định cp1252, không in được tiếng Việt
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    from common.db import get_db
    from core.metrics_sink import make_metrics

    parser = argparse.ArgumentParser(description="Phát metric shipaudit.biz.* định kỳ")
    parser.add_argument("--interval", type=float, default=60, help="số giây giữa hai lượt (mặc định 60)")
    parser.add_argument("--once", action="store_true", help="chạy một lượt rồi thoát")
    parser.add_argument("--sink", choices=["auto", "datadog", "console"], default="auto")
    parser.add_argument("--now", help="giờ cố định (ISO) để tính hạn; mặc định theo SHIPAUDIT_NOW hoặc giờ thật")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    fixed = args.now or os.getenv("SHIPAUDIT_NOW")
    now_fn = (lambda: as_aware(fixed)) if fixed else (lambda: datetime.now(timezone.utc))
    metric = make_metrics(args.sink)
    log.info("sink=%s database=%s now=%s", type(metric).__name__, get_db().name, fixed or "giờ thật")
    run_forever(get_db(), metric, args.interval, now_fn, max_runs=1 if args.once else None)


if __name__ == "__main__":
    main()
