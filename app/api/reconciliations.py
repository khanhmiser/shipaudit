"""[A] GET /reconciliations: liệt kê kết quả đối soát."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/reconciliations")
def reconciliations_endpoint():
    # TODO(A): cài thật. Model pydantic theo contracts/schemas.
    raise HTTPException(status_code=501, detail="not implemented")
