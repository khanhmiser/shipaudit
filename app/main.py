"""[A] Khởi tạo FastAPI và gắn các router. Bật log JSON và tracing trước khi tạo app."""
from fastapi import FastAPI

from app.telemetry.logging import setup_logging
from app.telemetry.tracing import setup_tracing

setup_logging()
setup_tracing()  # phải chạy trước khi tạo FastAPI để ddtrace bọc được app

from app.api import admin, health, reconciliations, statements, webhooks  # noqa: E402
from app.telemetry import http as http_metrics  # noqa: E402

app = FastAPI(title="ShipAudit API", version="0.1.0")
http_metrics.install(app)

app.include_router(health.router)
app.include_router(statements.router)
app.include_router(reconciliations.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
