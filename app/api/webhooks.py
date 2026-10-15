"""[A] POST /webhooks/datadog: kiểm tra secret, tạo claim nháp, idempotent theo alert id."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/webhooks/datadog")
def webhooks_endpoint():
    # TODO(A): cài thật. Model pydantic theo contracts/schemas.
    raise HTTPException(status_code=501, detail="not implemented")
