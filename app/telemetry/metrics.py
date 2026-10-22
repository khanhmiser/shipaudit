"""[A] metric(name, value, tags). Gửi DogStatsD khi có Agent, nếu không thì in ra console.

Đây là cài đặt thật của contracts.interfaces.Metrics. B import hàm `metric` này
(hoặc dùng stub_metric trong lúc chờ).
- Có Agent: đặt DD_AGENT_HOST (compose đặt sẵn là datadog-agent), cổng DD_DOGSTATSD_PORT (mặc định 8125).
- Chưa có Agent (chạy trên máy, chạy test): in một dòng `[metric] ...` ra stdout, không lỗi.
- `metric` là gauge (giá trị tại thời điểm), `increment` là count (cộng dồn số sự kiện).
"""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _client():
    host = os.getenv("DD_AGENT_HOST")
    if not host:
        return None
    try:
        from datadog.dogstatsd import DogStatsd

        return DogStatsd(host=host, port=int(os.getenv("DD_DOGSTATSD_PORT", "8125")),
                         constant_tags=[f"env:{os.getenv('DD_ENV', 'dev')}"])
    except Exception:  # noqa: BLE001 - chưa cài datadog
        return None


def _send(kind: str, name: str, value: float, tags: dict[str, str] | None) -> None:
    tag_list = [f"{k}:{v}" for k, v in (tags or {}).items()]
    client = _client()
    if client is not None:
        try:
            getattr(client, kind)(name, value, tags=tag_list)
            return
        except Exception:  # noqa: BLE001
            pass
    print(f"[metric] {kind} {name}={value} tags={tag_list}", flush=True)


def metric(name: str, value: float, tags: dict[str, str] | None = None) -> None:
    _send("gauge", name, value, tags)


def increment(name: str, value: float = 1, tags: dict[str, str] | None = None) -> None:
    _send("increment", name, value, tags)
