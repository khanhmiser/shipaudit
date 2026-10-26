"""[B] Nơi nhận metric cho job nghiệp vụ, theo contracts.interfaces.Metrics: gọi `sink(name, value, tags)`.

- `ConsoleMetrics`: in ra console (fallback khi chưa có Datadog), giống stub_metric.
- `DatadogHttpMetrics`: gom điểm rồi `flush()` một lần lên Datadog Metrics API v2 (`/api/v2/series`, kiểu gauge)
  bằng DD_API_KEY, không cần Datadog Agent. Site lấy theo DD_SITE (của đội là uk1.datadoghq.com).
- `make_metrics("auto")`: có DD_API_KEY thì gửi Datadog, không thì in console.

Khi ghép với A: hàm `metric()` của A (DogStatsD qua Agent) cũng dùng được vì cùng chữ ký; job chỉ gọi `flush()` nếu có.
Không bao giờ in hoặc ghi log khóa API.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable

from contracts.interfaces import stub_metric

GAUGE = 3  # MetricIntakeType của API v2


def _tag_list(tags: dict[str, str] | None) -> list[str]:
    return [f"{k}:{v}" for k, v in sorted((tags or {}).items())]


class ConsoleMetrics:
    def __call__(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        stub_metric(name, value, tags)

    def flush(self) -> int:
        return 0


class DatadogHttpMetrics:
    def __init__(self, api_key: str, site: str = "datadoghq.com", base_tags: dict[str, str] | None = None,
                 timeout: float = 10, opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.time):
        self.url = f"https://api.{site}/api/v2/series"
        self._api_key = api_key
        self.base_tags = dict(base_tags or {})
        self.timeout = timeout
        self._opener = opener
        self._clock = clock
        self._series: list[dict] = []

    def __call__(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        self._series.append({
            "metric": name,
            "type": GAUGE,
            "points": [{"timestamp": int(self._clock()), "value": float(value)}],
            "tags": _tag_list({**self.base_tags, **(tags or {})}),
        })

    def payload(self) -> dict:
        return {"series": list(self._series)}

    def flush(self) -> int:
        """Gửi các điểm đang gom. Trả về số điểm đã gửi. Lỗi mạng hoặc lỗi API thì ném RuntimeError (không lộ khóa)."""
        if not self._series:
            return 0
        body = json.dumps(self.payload()).encode()
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "DD-API-KEY": self._api_key})
        n = len(self._series)
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                status = resp.status
                detail = resp.read()[:300].decode(errors="replace")
        except urllib.error.HTTPError as e:
            status, detail = e.code, e.read()[:300].decode(errors="replace")
        except OSError as e:
            raise RuntimeError(f"không gửi được metric lên {self.url}: {type(e).__name__}: {e}") from None
        if status >= 300:
            raise RuntimeError(f"Datadog trả {status} khi nhận metric: {detail}")
        self._series.clear()
        return n


def make_metrics(kind: str = "auto"):
    """kind: auto | datadog | console."""
    api_key = os.getenv("DD_API_KEY", "")
    if kind == "console" or (kind == "auto" and not api_key):
        return ConsoleMetrics()
    if not api_key:
        raise RuntimeError("chưa đặt DD_API_KEY trong .env")
    return DatadogHttpMetrics(api_key, site=os.getenv("DD_SITE", "datadoghq.com"),
                              base_tags={"env": os.getenv("DD_ENV", "dev"), "service": "shipaudit-biz"})
