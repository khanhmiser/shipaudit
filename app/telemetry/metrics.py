"""[A] metric(name, value, tags). Gửi DogStatsD khi có Agent, nếu không thì in ra console.

Đây là cài đặt thật của contracts.interfaces.Metrics. B import hàm `metric` này
(hoặc dùng stub_metric trong lúc chờ).
"""
from __future__ import annotations

try:  # chạy được cả khi chưa cài/không có Agent
    from datadog import statsd as _statsd
except Exception:  # pragma: no cover
    _statsd = None


def metric(name: str, value: float, tags: dict[str, str] | None = None) -> None:
    tag_list = [f"{k}:{v}" for k, v in (tags or {}).items()]
    if _statsd is not None:
        try:
            _statsd.gauge(name, value, tags=tag_list)
            return
        except Exception:
            pass
    print(f"[metric] {name}={value} tags={tag_list}")
