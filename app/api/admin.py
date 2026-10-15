"""[A] Công tắc lỗi nạp: delay_ms, fail_rate (dùng cho kịch bản lớp vận hành)."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/admin/ingest-fault")
def admin_endpoint():
    # TODO(A): cài thật. Model pydantic theo contracts/schemas.
    raise HTTPException(status_code=501, detail="not implemented")
