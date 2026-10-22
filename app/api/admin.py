"""[A] Công tắc lỗi nạp: delay_ms, fail_rate (dùng cho kịch bản lớp vận hành).

- GET  /admin/ingest-fault        xem trạng thái
- POST /admin/ingest-fault        bật hoặc đổi (chỉ trường được gửi), vd {"delay_ms": 5000}
- POST /admin/ingest-fault/reset  tắt hết
Đặt ADMIN_TOKEN trong .env thì phải gửi kèm header X-Admin-Token. Để trống chỉ dùng khi chạy trên máy.
Mỗi lần đổi ghi log cảnh báo và phát gauge shipaudit.ops.fault_delay_ms, shipaudit.ops.fault_fail_rate.
"""
import hmac
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.models import FaultConfig, FaultUpdate
from app.ingest import faults
from app.ingest.pipeline import Faults
from app.telemetry.metrics import metric

log = logging.getLogger("shipaudit.admin")


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    token = os.getenv("ADMIN_TOKEN", "")
    if token and not hmac.compare_digest(x_admin_token or "", token):
        raise HTTPException(status_code=401, detail="sai hoặc thiếu X-Admin-Token")


router = APIRouter(prefix="/admin/ingest-fault", tags=["admin"], dependencies=[Depends(require_admin)])


def _publish(state: Faults, action: str) -> FaultConfig:
    log.warning("công tắc lỗi nạp: %s", action, extra={"delay_ms": state.delay_ms, "fail_rate": state.fail_rate})
    metric("shipaudit.ops.fault_delay_ms", state.delay_ms)
    metric("shipaudit.ops.fault_fail_rate", state.fail_rate)
    return FaultConfig(delay_ms=state.delay_ms, fail_rate=state.fail_rate)


@router.get("", response_model=FaultConfig)
def get_fault() -> FaultConfig:
    state = faults.get()
    return FaultConfig(delay_ms=state.delay_ms, fail_rate=state.fail_rate)


@router.post("", response_model=FaultConfig)
def set_fault(update: FaultUpdate) -> FaultConfig:
    return _publish(faults.set(update.delay_ms, update.fail_rate), "bật/đổi")


@router.post("/reset", response_model=FaultConfig)
def reset_fault() -> FaultConfig:
    return _publish(faults.reset(), "tắt")
