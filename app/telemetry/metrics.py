"""[A] metric(name, value, tags). Gửi DogStatsD khi có Agent, gửi thẳng Datadog API khi chỉ có API key,
không thì in ra console.

Đây là cài đặt thật của contracts.interfaces.Metrics. B import hàm `metric` này
(hoặc dùng stub_metric trong lúc chờ).
- Có Agent: đặt DD_AGENT_HOST (compose đặt sẵn là datadog-agent), cổng DD_DOGSTATSD_PORT (mặc định 8125).
- Không có Agent nhưng có DD_API_KEY (chạy trên máy, không Docker): gom điểm trong bộ nhớ, cứ
  DD_METRICS_FLUSH_SECONDS giây (mặc định 10) gửi một lần lên Metrics API v2 của DD_SITE. Tắt bằng
  DD_METRICS_AGENTLESS=false.
- Không có cả hai (chạy test): in một dòng `[metric] ...` ra stdout, không lỗi.
- `metric` là gauge (giá trị tại thời điểm), `increment` là count (cộng dồn số sự kiện),
  `timing` gom các mẫu thời gian (ms) rồi phát `<tên>.p95` và `<tên>.max` mỗi lần gửi.
"""
from __future__ import annotations

import atexit
import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Callable

log = logging.getLogger("shipaudit.telemetry")

GAUGE, COUNT = 3, 1  # MetricIntakeType của API v2


def _tag_list(tags: dict[str, str] | None) -> list[str]:
    return [f"{k}:{v}" for k, v in sorted((tags or {}).items())]


def p95(samples: list[float]) -> float:
    """Phân vị 95 theo kiểu nearest-rank."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


class HttpSender:
    """Gom gauge / count / timing theo (tên, tag) rồi gửi một lần lên /api/v2/series."""

    def __init__(self, api_key: str, site: str, base_tags: dict[str, str] | None = None,
                 opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.time):
        self.url = f"https://api.{site}/api/v2/series"
        self._api_key = api_key
        self.base_tags = dict(base_tags or {})
        self._opener = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._gauges: dict[tuple, float] = {}
        self._counts: dict[tuple, float] = {}
        self._timings: dict[tuple, list[float]] = {}
        self._last_flush = clock()

    def _key(self, name: str, tags: dict[str, str] | None) -> tuple:
        return name, tuple(_tag_list({**self.base_tags, **(tags or {})}))

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, tags)] = float(value)

    def increment(self, name: str, value: float = 1, tags: dict[str, str] | None = None) -> None:
        with self._lock:
            key = self._key(name, tags)
            self._counts[key] = self._counts.get(key, 0.0) + float(value)

    def timing(self, name: str, value_ms: float, tags: dict[str, str] | None = None) -> None:
        with self._lock:
            self._timings.setdefault(self._key(name, tags), []).append(float(value_ms))

    def series(self) -> list[dict]:
        """Lấy và xóa các điểm đang gom thành danh sách series của API v2."""
        now = self._clock()
        with self._lock:
            gauges, counts, timings = self._gauges, self._counts, self._timings
            self._gauges, self._counts, self._timings = {}, {}, {}
            interval = max(1, int(now - self._last_flush))
            self._last_flush = now
        ts = int(now)
        out = [{"metric": n, "type": GAUGE, "points": [{"timestamp": ts, "value": v}], "tags": list(t)}
               for (n, t), v in gauges.items()]
        out += [{"metric": n, "type": COUNT, "interval": interval, "points": [{"timestamp": ts, "value": v}],
                 "tags": list(t)} for (n, t), v in counts.items()]
        for (n, t), samples in timings.items():
            for suffix, value in (("p95", p95(samples)), ("max", max(samples))):
                out.append({"metric": f"{n}.{suffix}", "type": GAUGE, "points": [{"timestamp": ts, "value": value}],
                            "tags": list(t)})
        return out

    def flush(self) -> int:
        series = self.series()
        if not series:
            return 0
        req = urllib.request.Request(self.url, data=json.dumps({"series": series}).encode(), method="POST", headers={
            "Content-Type": "application/json", "DD-API-KEY": self._api_key})
        try:
            with self._opener(req, timeout=10) as resp:
                if resp.status >= 300:
                    log.warning("Datadog không nhận metric", extra={"status": resp.status})
        except (urllib.error.URLError, OSError) as e:  # không lộ khóa trong log
            log.warning("không gửi được metric lên Datadog", extra={"error": type(e).__name__})
            return 0
        return len(series)


def _start_flusher(sender: HttpSender, every: float) -> None:
    def loop():
        while True:
            time.sleep(every)
            sender.flush()

    threading.Thread(target=loop, name="dd-metrics-flush", daemon=True).start()
    atexit.register(sender.flush)


@lru_cache(maxsize=1)
def _client():
    """("statsd", client) | ("http", HttpSender) | (None, None)."""
    base = {"env": os.getenv("DD_ENV", "dev")}
    host = os.getenv("DD_AGENT_HOST")
    if host:
        try:
            from datadog.dogstatsd import DogStatsd

            return "statsd", DogStatsd(host=host, port=int(os.getenv("DD_DOGSTATSD_PORT", "8125")),
                                       constant_tags=_tag_list(base))
        except Exception:  # noqa: BLE001 - chưa cài datadog
            return None, None
    api_key = os.getenv("DD_API_KEY", "")
    if api_key and os.getenv("DD_METRICS_AGENTLESS", "true").lower() != "false":
        sender = HttpSender(api_key, os.getenv("DD_SITE", "datadoghq.com"),
                            {**base, "service": os.getenv("DD_SERVICE", "shipaudit-api")})
        _start_flusher(sender, float(os.getenv("DD_METRICS_FLUSH_SECONDS", "10")))
        return "http", sender
    return None, None


def _send(kind: str, name: str, value: float, tags: dict[str, str] | None) -> None:
    mode, client = _client()
    if mode == "statsd":
        try:
            getattr(client, "distribution" if kind == "timing" else kind)(name, value, tags=_tag_list(tags))
            return
        except Exception:  # noqa: BLE001
            pass
    elif mode == "http":
        {"gauge": client.gauge, "increment": client.increment, "timing": client.timing}[kind](name, value, tags)
        return
    if kind != "timing":  # console: không in từng mẫu thời gian cho đỡ rối
        print(f"[metric] {kind} {name}={value} tags={_tag_list(tags)}", flush=True)


def metric(name: str, value: float, tags: dict[str, str] | None = None) -> None:
    _send("gauge", name, value, tags)


def increment(name: str, value: float = 1, tags: dict[str, str] | None = None) -> None:
    _send("increment", name, value, tags)


def timing(name: str, value_ms: float, tags: dict[str, str] | None = None) -> None:
    _send("timing", name, value_ms, tags)


def flush() -> int:
    """Gửi ngay các điểm đang gom (chế độ không Agent). Dùng trong script trước khi thoát."""
    mode, client = _client()
    return client.flush() if mode == "http" else 0
