"""[A] GET /reconciliations: liệt kê kết quả đối soát, lọc theo hãng, diff_type, bảng kê; chênh lệch lớn trước."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.models import Carrier, Reconciliation, ReconciliationList
from app.deps import get_db
from common.enums import Collections, DiffType

router = APIRouter(tags=["reconciliations"])


@router.get("/reconciliations", response_model=ReconciliationList)
def list_reconciliations(
    carrier: Carrier | None = None,
    diff_type: DiffType | None = None,
    statement_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: Any = Depends(get_db),
) -> ReconciliationList:
    query: dict = {}
    if carrier:
        query["carrier"] = carrier
    if diff_type:
        query["diff_type"] = diff_type.value
    if statement_id:
        query["statement_id"] = statement_id
    cursor = db[Collections.RECONCILIATIONS].find(query, {"_id": 0}).sort([("diff", -1), ("order_code", 1)])
    items = [Reconciliation(**doc) for doc in cursor.limit(limit)]
    return ReconciliationList(count=len(items), limit=limit, items=items)
