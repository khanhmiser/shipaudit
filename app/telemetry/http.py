"""[A] Middleware đo mỗi request: `shipaudit.ops.api_latency_ms` (timing → .p95, .max) và
`shipaudit.ops.api_requests` (count) theo route, method, nhóm mã trả về (2xx, 4xx, 5xx).

Có Agent thì APM (ddtrace) cũng có trace.fastapi.request; middleware này giúp vẫn có p95 khi chạy không Agent.
Tag `route` là mẫu đường dẫn (vd /statements), không phải URL thật, để không nổ số chuỗi metric.
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request

from app.telemetry.metrics import increment, timing

LATENCY = "shipaudit.ops.api_latency_ms"
REQUESTS = "shipaudit.ops.api_requests"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_metrics(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            tags = {"route": route, "method": request.method}
            timing(LATENCY, (time.perf_counter() - start) * 1000, tags)
            increment(REQUESTS, 1, {**tags, "status_class": f"{status // 100}xx"})
