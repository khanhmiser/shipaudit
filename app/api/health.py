"""[A] GET /health: còn sống và ping được MongoDB. Không ping được thì trả 503 (healthcheck của compose dùng)."""
import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.models import Health
from app.deps import get_db

router = APIRouter(tags=["health"])
log = logging.getLogger("shipaudit.api")


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(db: Any = Depends(get_db)):
    try:
        db.client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        log.warning("health: không ping được MongoDB", extra={"error": f"{type(e).__name__}: {e}"})
        return JSONResponse(status_code=503, content=Health(status="degraded", mongo=type(e).__name__).model_dump())
    return Health(status="ok", mongo="ok")
