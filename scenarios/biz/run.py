"""[B] Kịch bản lớp nghiệp vụ: nạp bảng kê Carrier B có nhiều đơn bị trừ lệch, một số sát hạn.

    python -m scenarios.biz.run --db shipaudit_b_scenario --reset                       # chờ người duyệt trên giao diện
    python -m scenarios.biz.run --db shipaudit_b_scenario --reset --approve-by "Tên người duyệt"
    python -m scenarios.biz.run --db shipaudit_b_scenario --reset --hold-minutes 0 --sink console   # chạy nhanh, không Datadog
    python -m scenarios.biz.run --db shipaudit_scenario --reset --webhook real                      # webhook Datadog gọi thật
    python -m scenarios.biz.run --db shipaudit_scenario --reset --approve-by "Tên" --recover-by "Tên"   # chạy tới khi hãng hoàn tiền

Các pha (giờ mô phỏng theo dòng thời gian của dữ liệu seed, giờ Việt Nam; điểm metric vẫn gắn giờ thật):
1. Bình thường, 20/10 10:00: đã nhận mọi bảng kê tới kỳ W42 trừ bảng kê W42 của Carrier B (hãng gửi muộn).
2. Sự cố, cùng lúc: bảng kê W42 của Carrier B về, có ERRORS đơn bị ghi thiếu tiền thu hộ SHORTFALL đồng
   (ngoài các chênh lệch đã cài sẵn trong seed). Tiền nhận thiếu của B vượt ngưỡng → monitor ngưỡng và Anomaly Detection.
3. 51 giờ sau, 22/10 13:00, chưa ai xử lý: B còn 21 giờ để khiếu nại → monitor "Sắp hết hạn khiếu nại".
4. Webhook tạo claim nháp cho các khoản của B sắp hết hạn: giả lập (mặc định) hoặc `--webhook real`: chờ monitor Datadog
   báo động rồi gọi POST /webhooks/datadog của API (cần API chạy với cùng MONGO_DB và SHIPAUDIT_NOW = giờ pha 3, có địa chỉ
   công khai và webhook `shipaudit-claims` trên Datadog; không thấy claim sau `--webhook-wait-minutes` thì dùng giả lập dự phòng),
   con người duyệt và ghi nhận đã gửi hãng (trên giao diện, hoặc --approve-by), metric về 0 → các monitor về OK.

5. Hãng chấp nhận khiếu nại và hoàn tiền (chỉ khi có `--recover-by` hoặc `--wait-recovery-minutes`): claim chuyển sang
   Đã thu hồi, `recovered_amount` tăng, tiền nhận thiếu còn lại về 0.

Mỗi pha giữ metric `--hold-minutes` phút (mặc định 8) để monitor trên Datadog kịp đánh giá (cửa sổ 5 phút).
Trong lúc chạy, tắt job `python -m core.metrics_job` đang chạy riêng (nếu có), vì hai nơi cùng phát một chuỗi metric.
Database đích bị xóa và seed lại (seed 42) nên bắt buộc `--reset`. Báo cáo và file bảng kê ghi vào generator/out/scenario/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from common.enums import Collections
from core import events, metrics_job, queries
from core.claims import ClaimService
from core.periods import VN_TZ, to_db
from core.reconcile import reconcile_statement
from generator.seed import build_dataset, load_to_db
from generator.statements import statement_id_for, to_csv

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "generator" / "out" / "scenario"
MONITORS = ROOT / "datadog" / "biz" / "monitors.json"
DEPLOYED = ROOT / "datadog" / "biz" / "deployed.json"

SEED = 42
CARRIER = "carrier_b"
PERIOD = "2026-W42"
T0 = datetime(2026, 10, 20, 10, 0, tzinfo=VN_TZ)
JUMP = timedelta(hours=51)
ERRORS = 80
SHORTFALL = 150_000
MIN_COD = 300_000      # chỉ sửa đơn có thu hộ đủ lớn để số tiền sau khi trừ vẫn dương
DRAFT_WINDOW_HOURS = 48
CLEAR = (Collections.ORDERS, Collections.STATEMENT_LINES, Collections.RECONCILIATIONS, Collections.CLAIMS)


# ── Đánh giá điều kiện monitor tại chỗ (cùng ngưỡng với datadog/biz/monitors.json) ──
def load_thresholds(path: Path = MONITORS) -> dict[str, dict]:
    monitors = json.loads(path.read_text(encoding="utf-8"))
    return {"threshold": monitors[0]["options"]["thresholds"], "deadline": monitors[1]["options"]["thresholds"]}


def monitor_states(summary: dict[str, dict], thresholds: dict[str, dict]) -> dict[str, dict[str, str]]:
    th, dl = thresholds["threshold"], thresholds["deadline"]
    out = {}
    for carrier, s in summary.items():
        amount, hours = s["open_amount"], s["claim_hours_left"]
        out[carrier] = {
            "threshold": "ALERT" if amount > th["critical"] else "WARN" if amount > th["warning"] else "OK",
            "deadline": "ALERT" if hours < dl["critical"] else "WARN" if hours < dl["warning"] else "OK",
        }
    return out


# ── Các bước ──
def setup(db: Any, seed: int = SEED) -> tuple[dict, list[dict]]:
    """Seed lại database; giữ bảng kê W42 của Carrier B ở ngoài (chưa nhận). Trả về (dataset, các dòng đang giữ)."""
    for name in CLEAR:
        db[name].delete_many({})
    ds = build_dataset("synthetic", seed=seed)
    load_to_db(ds, db, reset=True)
    held_sid = statement_id_for(CARRIER, PERIOD)
    held = [ln for ln in ds["statement_lines"] if ln["statement_id"] == held_sid]
    db[Collections.STATEMENT_LINES].delete_many({"statement_id": held_sid})
    for sid in ds["manifest"]["statements"]:
        if sid != held_sid:
            reconcile_statement(sid, db, now=T0)
    return ds, held


def incident(db: Any, ds: dict, held: list[dict], now: datetime, errors: int = ERRORS,
             shortfall: int = SHORTFALL) -> dict:
    """Nạp bảng kê đang giữ, ghi thiếu thu hộ ở `errors` đơn vốn không có chênh lệch, rồi đối soát."""
    labelled = {a["order_code"] for a in ds["labels"]["anomalies"]}
    candidates = sorted((ln for ln in held if ln["order_code"] not in labelled and ln["cod_collected"] >= MIN_COD),
                        key=lambda ln: ln["order_code"])
    changed = {ln["order_code"] for ln in candidates[:errors]}
    if len(changed) < errors:
        raise RuntimeError(f"chỉ có {len(changed)} đơn đủ điều kiện để cài sai, cần {errors}")
    lines = []
    for ln in held:
        ln = {**ln, "raw": dict(ln["raw"]), "ingested_at": to_db(now)}
        if ln["order_code"] in changed:
            ln["cod_collected"] -= shortfall
            ln["net_paid"] -= shortfall
            ln["raw"]["thu_ho"], ln["raw"]["thuc_tra"] = str(ln["cod_collected"]), str(ln["net_paid"])
        lines.append(ln)
    sid = lines[0]["statement_id"]
    db[Collections.STATEMENT_LINES].insert_many([dict(ln) for ln in lines], ordered=False)
    recs = reconcile_statement(sid, db, now=now)
    detected = {r["order_code"]: r["diff_type"] for r in recs if r["order_code"] in changed}
    return {
        "statement_id": sid, "lines": len(lines), "changed": sorted(changed), "shortfall": shortfall,
        "detected": detected, "csv": to_csv(CARRIER, [ln["raw"] for ln in lines]),
    }


def simulate_webhook(db: Any, now: datetime, alert_id: str, announce: bool = True) -> list[dict]:
    """Việc webhook POST /webhooks/datadog sẽ làm khi monitor hạn khiếu nại báo động (idempotent theo alert id).
    `announce`: phát sự kiện Datadog (lần gọi lại cùng alert thì không)."""
    svc = ClaimService(db, now=lambda: now)
    drafts = svc.create_drafts_for_carrier(CARRIER, source="datadog_webhook", alert_id=alert_id,
                                           within_hours=DRAFT_WINDOW_HOURS)
    if announce:
        events.publish("created", drafts, by="webhook giả lập", source="datadog_webhook")
    return drafts


def webhook_claims(db: Any, carrier: str = CARRIER) -> list[dict]:
    """Claim nháp do webhook thật (Datadog gọi API) tạo cho hãng."""
    return list(db[Collections.CLAIMS].find({"carrier": carrier, "source": "datadog_webhook"},
                                            {"_id": 0, "claim_id": 1, "alert_id": 1}))


def wait_for_webhook(db: Any, metric, now: datetime, minutes: float, interval: float,
                     on_poll: Callable[[], None] = lambda: None,
                     sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    """Chờ webhook thật tạo claim. Trong lúc chờ vẫn phát metric tại giờ `now` để monitor giữ trạng thái báo động."""
    deadline = time.monotonic() + minutes * 60
    while True:
        claims = webhook_claims(db)
        if claims or time.monotonic() >= deadline:
            return claims
        hold(db, now, metric, 0, interval, sleep)
        on_poll()
        sleep(interval)


def approve_and_submit(db: Any, now: datetime, claim_ids: list[str], by: str) -> int:
    svc = ClaimService(db, now=lambda: now)
    approved, submitted = [], []
    for cid in claim_ids:
        claim = svc.get(cid)
        if claim["status"] == "DRAFT":
            claim = svc.approve(cid, by)
            approved.append(claim)
        if claim["status"] == "APPROVED":
            submitted.append(svc.submit(cid, by))
    events.publish("approved", approved, by)
    events.publish("submitted", submitted, by)
    return len(claim_ids)


def wait_for_submission(db: Any, claim_ids: list[str], timeout_s: float, poll_s: float,
                        on_poll: Callable[[int], None] = lambda n: None,
                        sleep: Callable[[float], None] = time.sleep) -> int:
    """Chờ người duyệt và gửi hãng trên giao diện. Trả về số claim chưa gửi khi hết giờ chờ."""
    deadline = time.monotonic() + timeout_s
    while True:
        left = db[Collections.CLAIMS].count_documents(
            {"claim_id": {"$in": claim_ids}, "status": {"$in": ["DRAFT", "APPROVED"]}})
        on_poll(left)
        if left == 0 or time.monotonic() >= deadline:
            return left
        sleep(poll_s)


def recover_claims(db: Any, now: datetime, claim_ids: list[str], by: str) -> tuple[int, int]:
    """Hãng chấp nhận và hoàn đủ tiền: ghi nhận đã thu hồi các claim đã gửi hãng. Trả về (số claim, tổng tiền hoàn)."""
    svc = ClaimService(db, now=lambda: now)
    done = []
    for cid in claim_ids:
        claim = svc.get(cid)
        if claim["status"] == "SUBMITTED":
            done.append(svc.mark_recovered(cid, int(claim["amount"]), by))
    events.publish("recovered", done, by)
    return len(done), sum(c["recovered_amount"] for c in done)


def wait_for_recovery(db: Any, claim_ids: list[str], timeout_s: float, poll_s: float,
                      on_poll: Callable[[int], None] = lambda n: None,
                      sleep: Callable[[float], None] = time.sleep) -> int:
    """Chờ người ghi nhận hãng đã hoàn tiền trên giao diện. Trả về số claim còn chờ hãng phản hồi khi hết giờ."""
    deadline = time.monotonic() + timeout_s
    while True:
        left = db[Collections.CLAIMS].count_documents({"claim_id": {"$in": claim_ids}, "status": "SUBMITTED"})
        on_poll(left)
        if left == 0 or time.monotonic() >= deadline:
            return left
        sleep(poll_s)


def hold(db: Any, now: datetime, metric, minutes: float, interval: float,
         sleep: Callable[[float], None] = time.sleep) -> dict[str, dict]:
    """Phát metric tại giờ mô phỏng `now` trong `minutes` phút (ít nhất một lượt). Trả về tóm tắt lượt cuối."""
    rounds = max(1, int(minutes * 60 // interval)) if minutes > 0 else 1
    summary = {}
    for i in range(rounds):
        points = metrics_job.collect(db, now)
        if metric is not None:
            metrics_job.emit(points, metric)
        summary = metrics_job.summary(points)
        if i < rounds - 1:
            sleep(interval)
    return summary


def run(db: Any, *, metric=None, hold_minutes: float = 8, interval: float = 60, approve_by: str | None = None,
        wait_minutes: float = 30, errors: int = ERRORS, shortfall: int = SHORTFALL, out_dir: Path | None = OUT_DIR,
        webhook: str = "simulate", webhook_wait_minutes: float = 15,
        recover_by: str | None = None, wait_recovery_minutes: float = 0,
        log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> dict:
    thresholds = load_thresholds()
    run_id = datetime.now(VN_TZ).strftime("%Y%m%d-%H%M%S")
    phases: list[dict] = []

    def phase(name: str, now: datetime, minutes: float = hold_minutes) -> dict:
        log(f"\n== {name} (giờ mô phỏng {now:%d/%m %H:%M}) - phát metric {minutes:g} phút ==")
        summary = hold(db, now, metric, minutes, interval, sleep)
        states = monitor_states(summary, thresholds)
        for carrier, s in sorted(summary.items()):
            st = states[carrier]
            log(f"  {carrier}: nhận thiếu còn hạn {s['open_amount']:>12,.0f}đ, {s['open_count']:>4.0f} khoản, "
                f"còn {s['claim_hours_left']:>6} giờ | monitor ngưỡng {st['threshold']}, monitor hạn {st['deadline']}")
        phases.append({"name": name, "now": now.isoformat(), "summary": summary, "monitors": states})
        return states

    log(f"Database {db.name}: seed lại (seed {SEED}), giữ bảng kê {statement_id_for(CARRIER, PERIOD)} chưa nạp")
    ds, held = setup(db)
    phase("1. Bình thường", T0)

    inc = incident(db, ds, held, T0, errors, shortfall)
    found = sum(1 for t in inc["detected"].values() if t == "COD_MISMATCH")
    log(f"\nBảng kê {inc['statement_id']} về: {inc['lines']} dòng, {len(inc['changed'])} đơn bị ghi thiếu "
        f"{shortfall:,}đ thu hộ; đối soát nhận ra {found}/{len(inc['changed'])} là COD_MISMATCH")
    phase("2. Sự cố: bảng kê Carrier B bị trừ lệch", T0)

    t1 = T0 + JUMP
    phase("3. Chưa ai xử lý, sát hạn khiếu nại", t1)

    alert_id = f"scenario-biz-{run_id}"
    drafts: list[dict] = []
    webhook_mode = "simulated"
    if webhook == "real":
        log(f"\nChờ webhook thật (monitor Datadog báo động → POST /webhooks/datadog) tối đa {webhook_wait_minutes:g} phút...")
        drafts = wait_for_webhook(db, metric, t1, webhook_wait_minutes, interval,
                                  on_poll=lambda: log("  chưa có claim từ webhook, tiếp tục chờ"), sleep=sleep)
        if drafts:
            webhook_mode = "real"
            alert_id = drafts[0].get("alert_id") or alert_id
            log(f"Webhook thật (alert {alert_id}): {len(drafts)} claim nháp cho {CARRIER}")
        else:
            webhook_mode = "simulated-fallback"
            log("Webhook không gọi về trong thời gian chờ: dùng giả lập dự phòng")
    again: list[dict] = []
    if webhook_mode != "real":
        drafts = simulate_webhook(db, t1, alert_id)
        again = simulate_webhook(db, t1, alert_id, announce=False)
        log(f"\nWebhook (giả lập, alert {alert_id}): {len(drafts)} claim nháp cho {CARRIER}; "
            f"gọi lại cùng alert ra {len(again)} claim, không tạo thêm")
    claim_ids = [d["claim_id"] for d in drafts]
    phase("4a. Đã có claim nháp, chờ duyệt", t1, minutes=min(hold_minutes, 1))

    if approve_by:
        n = approve_and_submit(db, t1, claim_ids, approve_by)
        log(f"\n{approve_by} duyệt và ghi nhận đã gửi hãng {n} claim")
        not_sent = 0
    else:
        log(f"\nChờ người duyệt trên giao diện (Streamlit, trang Claims, database {db.name}) tối đa {wait_minutes:g} phút...")
        not_sent = wait_for_submission(db, claim_ids, wait_minutes * 60, min(interval, 30),
                                       on_poll=lambda n: log(f"  còn {n} claim chưa gửi hãng"), sleep=sleep)
    phase("4b. Sau khi gửi claim", t1)

    recovered = {"claims": 0, "amount": 0, "still_waiting": None}
    if recover_by and not not_sent:
        n, total = recover_claims(db, t1, claim_ids, recover_by)
        log(f"\nHãng chấp nhận khiếu nại và hoàn tiền: {recover_by} ghi nhận đã thu hồi {n} claim, tổng {total:,}đ")
        recovered.update(claims=n, amount=total, still_waiting=0)
    elif wait_recovery_minutes > 0 and not not_sent:
        log(f"\nChờ ghi nhận hãng hoàn tiền trên giao diện (trang Claims) tối đa {wait_recovery_minutes:g} phút...")
        recovered["still_waiting"] = wait_for_recovery(
            db, claim_ids, wait_recovery_minutes * 60, min(interval, 30),
            on_poll=lambda n: log(f"  còn {n} claim chờ hãng phản hồi"), sleep=sleep)
        done = [o for o in queries.claim_outcomes(db, CARRIER) if o["status"] == "RECOVERED"]
        recovered.update(claims=sum(o["count"] for o in done), amount=sum(o["recovered"] for o in done))
    if recovered["claims"]:
        phase("5. Hãng hoàn tiền, claim đã thu hồi", t1)

    report = {
        "run_id": run_id, "database": db.name, "seed": SEED, "carrier": CARRIER,
        "incident": {k: v for k, v in inc.items() if k != "csv"},
        "claims": {"webhook": webhook_mode, "alert_id": alert_id, "drafts": len(drafts),
                   "drafts_on_retry": len(again) if webhook_mode != "real" else None, "recovered": recovered,
                   "not_submitted": not_sent, "approved_by": approve_by},
        "phases": phases,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{inc['statement_id']}.csv").write_text(inc["csv"], encoding="utf-8", newline="\n")
        (out_dir / "biz-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
                                                 encoding="utf-8")
        log(f"\nBáo cáo: {out_dir / 'biz-report.json'}")
    if DEPLOYED.exists():
        deployed = json.loads(DEPLOYED.read_text(encoding="utf-8"))
        log("Xem trên Datadog: " + ", ".join(m["url"] for m in deployed.get("monitors", []))
            + (f", dashboard {deployed['dashboard']['url']}" if "dashboard" in deployed else ""))
    return report


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    from pymongo import MongoClient

    from common import config
    from core.metrics_sink import make_metrics

    parser = argparse.ArgumentParser(description="Kịch bản lớp nghiệp vụ ShipAudit")
    parser.add_argument("--db", default=config.MONGO_DB, help="database đích (bị xóa và seed lại)")
    parser.add_argument("--reset", action="store_true", help="bắt buộc: đồng ý xóa và seed lại database đích")
    parser.add_argument("--hold-minutes", type=float, default=8, help="số phút giữ mỗi pha (0 = chạy nhanh)")
    parser.add_argument("--interval", type=float, default=60, help="số giây giữa hai lượt phát metric")
    parser.add_argument("--sink", choices=["auto", "datadog", "console", "none"], default="auto")
    parser.add_argument("--approve-by", help="tên người duyệt: duyệt và gửi hãng hàng loạt thay vì chờ giao diện")
    parser.add_argument("--wait-minutes", type=float, default=30, help="thời gian chờ người duyệt trên giao diện")
    parser.add_argument("--webhook", choices=["simulate", "real"], default="simulate",
                        help="simulate: giả lập webhook; real: chờ Datadog gọi API thật (không thấy thì giả lập dự phòng)")
    parser.add_argument("--webhook-wait-minutes", type=float, default=15, help="thời gian chờ webhook thật")
    parser.add_argument("--recover-by", help="tên người ghi nhận: hãng hoàn đủ tiền cho các claim đã gửi (pha 5)")
    parser.add_argument("--wait-recovery-minutes", type=float, default=0,
                        help="chờ người ghi nhận hãng hoàn tiền trên giao diện (pha 5), 0 = không chờ")
    parser.add_argument("--errors", type=int, default=ERRORS)
    parser.add_argument("--shortfall", type=int, default=SHORTFALL)
    args = parser.parse_args()
    if not args.reset:
        parser.error(f"kịch bản xóa và seed lại database {args.db!r}; thêm --reset để đồng ý")

    metric = None if args.sink == "none" else make_metrics(args.sink)
    print(f"Sink metric: {type(metric).__name__ if metric else 'không phát'}")
    db = MongoClient(config.MONGO_URI)[args.db]
    run(db, metric=metric, hold_minutes=args.hold_minutes, interval=args.interval, approve_by=args.approve_by,
        wait_minutes=args.wait_minutes, errors=args.errors, shortfall=args.shortfall,
        webhook=args.webhook, webhook_wait_minutes=args.webhook_wait_minutes,
        recover_by=args.recover_by, wait_recovery_minutes=args.wait_recovery_minutes,
        log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
