"""[A] Kịch bản lớp vận hành: bật độ trễ/lỗi nạp, chờ monitor, chứng minh phục hồi bằng dữ liệu.

    python -m scenarios.ops.run --api http://localhost:8000                      # 3 pha × 6 phút
    python -m scenarios.ops.run --api http://localhost:8000 --hold-minutes 0.5   # chạy nhanh để thử

Cần API đang chạy (uvicorn app.main:app) với DD_API_KEY (metric gửi thẳng Datadog khi không có Agent) và
DD_LOGS_AGENTLESS=true (log lỗi lên Log Management). Các pha:
1. Bình thường: công tắc lỗi tắt, cứ `--every` giây nạp lại bảng kê mẫu của `--carrier` qua POST /statements.
2. Sự cố: bật công tắc lỗi nạp (delay_ms, fail_rate). Độ trễ nạp và p95 POST /statements tăng, một phần lượt
   nạp trả 503 và ghi log ERROR → các monitor vận hành (datadog/ops/monitors.json) kích hoạt.
3. Khắc phục: tắt công tắc, nạp tiếp; số liệu về bình thường → monitor về OK.
Nạp lại cùng một file ra cùng statement_id nên không nhân đôi dữ liệu. Có ADMIN_TOKEN thì gửi kèm X-Admin-Token.
Báo cáo ghi ra generator/out/scenario/ops-report.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "contracts" / "samples"
OUT_DIR = ROOT / "generator" / "out" / "scenario"
DEPLOYED = ROOT / "datadog" / "ops" / "deployed.json"


class Api:
    def __init__(self, base: str, admin_token: str = "", timeout: float = 120):
        self.base = base.rstrip("/")
        self.admin_token = admin_token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"detail": raw[:200].decode(errors="replace")}

    def health(self):
        return self._call("GET", "/health")

    def set_fault(self, delay_ms: int, fail_rate: float):
        body = json.dumps({"delay_ms": delay_ms, "fail_rate": fail_rate}).encode()
        return self._call("POST", "/admin/ingest-fault", body, self._admin({"Content-Type": "application/json"}))

    def reset_fault(self):
        return self._call("POST", "/admin/ingest-fault/reset", b"", self._admin({}))

    def upload(self, carrier: str, path: Path):
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="carrier"\r\n\r\n{carrier}\r\n'.encode(),
            (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
             "Content-Type: text/csv\r\n\r\n").encode() + path.read_bytes() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self._call("POST", "/statements", b"".join(parts),
                          {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def _admin(self, headers: dict) -> dict:
        return {**headers, "X-Admin-Token": self.admin_token} if self.admin_token else headers


@dataclass
class PhaseStats:
    name: str
    uploads: int = 0
    by_http: dict[str, int] = field(default_factory=dict)
    lags: list[float] = field(default_factory=list)
    durations: list[int] = field(default_factory=list)
    round_trip_ms: list[float] = field(default_factory=list)

    def add(self, status: int, body: dict, rt_ms: float) -> None:
        self.uploads += 1
        self.by_http[str(status)] = self.by_http.get(str(status), 0) + 1
        self.round_trip_ms.append(rt_ms)
        if isinstance(body, dict) and "lag_seconds" in body:
            self.lags.append(float(body["lag_seconds"]))
            self.durations.append(int(body.get("duration_ms", 0)))

    def summary(self) -> dict:
        errors = sum(n for code, n in self.by_http.items() if not code.startswith("2"))
        return {
            "name": self.name, "uploads": self.uploads, "by_http": dict(sorted(self.by_http.items())),
            "error_rate": round(errors / self.uploads, 3) if self.uploads else None,
            "max_lag_seconds": max(self.lags, default=None),
            "max_round_trip_ms": round(max(self.round_trip_ms, default=0)),
        }


def run_phase(api: Api, name: str, carrier: str, sample: Path, minutes: float, every: float,
              log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic) -> dict:
    stats = PhaseStats(name)
    end = clock() + minutes * 60
    while True:
        started = clock()
        status, body = api.upload(carrier, sample)
        rt = (clock() - started) * 1000
        stats.add(status, body, rt)
        log(f"  [{name}] POST /statements → {status}, lag {body.get('lag_seconds') if isinstance(body, dict) else '?'} giây")
        if clock() >= end:
            break
        sleep(max(0.0, every - (clock() - started)))
    s = stats.summary()
    log(f"  → {s['uploads']} lượt, mã trả về {s['by_http']}, tỉ lệ lỗi {s['error_rate']}, "
        f"độ trễ nạp lớn nhất {s['max_lag_seconds']} giây")
    return s


def run(api: Api, *, carrier: str = "carrier_b", minutes: float = 6, every: float = 20, delay_ms: int = 7_000,
        fail_rate: float = 0.5, out_dir: Path | None = OUT_DIR, log: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    sample = SAMPLES / f"statement_{carrier}.csv"
    status, health = api.health()
    if status != 200:
        raise RuntimeError(f"API chưa sẵn sàng: /health trả {status} {health}")
    log(f"API {api.base}: {health}")

    api.reset_fault()
    log(f"\n== 1. Bình thường ({minutes:g} phút) ==")
    normal = run_phase(api, "binh-thuong", carrier, sample, minutes, every, log, sleep)

    status, fault = api.set_fault(delay_ms, fail_rate)
    log(f"\n== 2. Sự cố: bật công tắc lỗi nạp {fault} ({minutes:g} phút) ==")
    try:
        incident = run_phase(api, "su-co", carrier, sample, minutes, every, log, sleep)
    finally:
        status, fault = api.reset_fault()
    log(f"\n== 3. Khắc phục: tắt công tắc {fault} ({minutes:g} phút) ==")
    recovered = run_phase(api, "khac-phuc", carrier, sample, minutes, every, log, sleep)

    report = {"api": api.base, "carrier": carrier, "fault": {"delay_ms": delay_ms, "fail_rate": fail_rate},
              "phases": [normal, incident, recovered]}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ops-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
        log(f"\nBáo cáo: {out_dir / 'ops-report.json'}")
    if DEPLOYED.exists():
        deployed = json.loads(DEPLOYED.read_text(encoding="utf-8"))
        log("Xem trên Datadog: " + ", ".join(m["url"] for m in deployed.get("monitors", []))
            + (f", dashboard {deployed['dashboard']['url']}" if "dashboard" in deployed else ""))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Kịch bản lớp vận hành ShipAudit")
    parser.add_argument("--api", default=os.getenv("SHIPAUDIT_API_URL", "http://localhost:8000"))
    parser.add_argument("--carrier", default="carrier_b", choices=["carrier_a", "carrier_b", "carrier_c"])
    parser.add_argument("--hold-minutes", type=float, default=6, help="số phút mỗi pha (monitor cần cửa sổ 5 phút)")
    parser.add_argument("--every", type=float, default=20, help="số giây giữa hai lượt nạp")
    parser.add_argument("--delay-ms", type=int, default=7_000)
    parser.add_argument("--fail-rate", type=float, default=0.5)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    api = Api(args.api, os.getenv("ADMIN_TOKEN", ""))
    run(api, carrier=args.carrier, minutes=args.hold_minutes, every=args.every, delay_ms=args.delay_ms,
        fail_rate=args.fail_rate, log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
