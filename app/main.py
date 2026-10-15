"""[A] Khởi tạo FastAPI và gắn các router."""
from fastapi import FastAPI

from app.api import admin, health, reconciliations, statements, webhooks

app = FastAPI(title="ShipAudit API")

app.include_router(health.router)
app.include_router(statements.router)
app.include_router(reconciliations.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
