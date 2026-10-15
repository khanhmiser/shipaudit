"""[A] POST /statements: nhận file CSV + mã hãng, gọi app.ingest.pipeline."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/statements")
def statements_endpoint():
    # TODO(A): cài thật. Model pydantic theo contracts/schemas.
    raise HTTPException(status_code=501, detail="not implemented")
