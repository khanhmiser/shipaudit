"""[A] POST /statements: nhận file CSV + mã hãng, gọi app.ingest.pipeline.

Mã trả về: 201 khi nạp xong (OK hoặc PARTIAL, xem `status` và `errors`), 422 khi sai định dạng file,
503 khi công tắc lỗi nạp làm hỏng lượt nạp, 500 khi đối soát hoặc ghi dữ liệu lỗi. Thân trả về luôn là IngestResponse.
"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.models import PERIOD_PATTERN, Carrier, IngestResponse
from app.deps import get_db
from app.ingest import faults
from app.ingest.pipeline import ERROR, ingest

router = APIRouter(tags=["statements"])

MAX_BYTES = 10 * 1024 * 1024
ERROR_STATUS = {"format": 422, "fault": 503, "reconcile": 500}


@router.post("/statements", response_model=IngestResponse, status_code=201,
             responses={422: {"model": IngestResponse}, 503: {"model": IngestResponse}, 500: {"model": IngestResponse}})
def upload_statement(
    file: Annotated[UploadFile, File(description="File CSV bảng kê của hãng")],
    carrier: Annotated[Carrier, Form(description="Mã hãng: carrier_a, carrier_b, carrier_c")],
    statement_id: Annotated[str | None, Form(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = None,
    period: Annotated[str | None, Form(pattern=PERIOD_PATTERN, description="Kỳ đối soát, vd 2026-W42")] = None,
    db: Any = Depends(get_db),
):
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file lớn hơn {MAX_BYTES // (1024 * 1024)} MB")
    if not raw.strip():
        raise HTTPException(status_code=422, detail="file rỗng")
    result = ingest(db, carrier, raw, file.filename, statement_id=statement_id, period=period, faults=faults.get())
    body = IngestResponse(**result.to_dict())
    if result.status == ERROR:
        return JSONResponse(status_code=ERROR_STATUS[result.error_kind], content=body.model_dump(mode="json"))
    return body
