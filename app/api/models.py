"""[A] Model pydantic cho API, theo contracts/schemas. Tiền là số nguyên VNĐ."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from common.enums import DiffType

Carrier = Literal["carrier_a", "carrier_b", "carrier_c"]
IngestStatus = Literal["OK", "PARTIAL", "ERROR"]
PERIOD_PATTERN = r"^\d{4}-W\d{2}$"


class IngestResponse(BaseModel):
    statement_id: str
    carrier: str
    status: IngestStatus
    rows: int = Field(description="Số dòng statement_lines đã ghi (mỗi mã đơn một dòng)")
    skipped: int = Field(description="Số dòng hỏng bị bỏ qua")
    errors: list[str] = Field(default_factory=list, description="Lý do bỏ qua từng dòng hỏng")
    reconciled: int = Field(description="Số bản ghi reconciliations do reconcile_statement trả về")
    stub: bool = Field(description="true nếu dùng stub_reconcile_statement vì B chưa cài")
    duration_ms: int
    lag_seconds: float
    file: str | None = None
    error: str | None = None
    error_kind: Literal["format", "fault", "reconcile"] | None = None


class Reconciliation(BaseModel):
    """contracts/schemas/reconciliations.json. Trường B ghi thêm (period, breakdown thực nhận...) vẫn trả về."""
    model_config = ConfigDict(extra="allow")

    statement_id: str
    order_code: str
    carrier: str
    expected_amount: int
    actual_amount: int
    diff: int
    diff_type: DiffType
    breakdown: dict | None = None
    claim_deadline_at: datetime | None = None
    claim_hours_left: float | None = None
    created_at: datetime | None = None
    stub: bool | None = None


class ReconciliationList(BaseModel):
    count: int
    limit: int
    items: list[Reconciliation]


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    mongo: str


class FaultConfig(BaseModel):
    delay_ms: int = Field(ge=0, le=120_000, description="Trễ thêm cho mỗi lượt nạp, mili giây")
    fail_rate: float = Field(ge=0, le=1, description="Xác suất một lượt nạp bị hỏng (0–1)")


class FaultUpdate(BaseModel):
    delay_ms: int | None = Field(default=None, ge=0, le=120_000)
    fail_rate: float | None = Field(default=None, ge=0, le=1)
