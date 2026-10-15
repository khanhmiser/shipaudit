"""Hợp đồng giữa A và B. Chỉ định nghĩa kiểu và stub, KHÔNG chứa logic thật.

- B cài thật: reconcile_statement, ClaimService.
- A cài thật: Metrics (app/telemetry/metrics.py).
Trong lúc chờ nhau, mỗi bên dùng bản Stub* ở cuối file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Tiền luôn là số nguyên VNĐ.
Money = int


@dataclass
class Breakdown:
    """Các khoản cộng/trừ của MỘT đơn theo công thức đối soát đã chốt.

    Tiền đối soát = thu hộ + shop trả trước + shop trả phí khi trả hàng
                    - phí giao hàng - phí bảo hiểm - phí chuyển hoàn - phí lưu kho
                    - phí thay đổi địa chỉ - phí đồng kiểm + khuyến mãi - phí chuyển khoản
    Các khoản "nếu có" mặc định 0.
    """

    cod_collected: Money = 0          # tiền thu hộ (+)
    prepaid_by_shop: Money = 0        # shop trả trước (+)
    return_fee_paid_by_shop: Money = 0  # shop trả phí khi trả hàng (+)
    shipping_fee: Money = 0           # phí giao hàng (-)
    insurance_fee: Money = 0          # phí bảo hiểm (-)
    return_shipping_fee: Money = 0    # phí chuyển hoàn (-)
    storage_fee: Money = 0            # phí lưu kho (-)
    address_change_fee: Money = 0     # phí thay đổi địa chỉ (-)
    inspection_fee: Money = 0         # phí đồng kiểm (-)
    promotion: Money = 0              # khuyến mãi (+)
    transfer_fee: Money = 0           # phí chuyển khoản (-)

    @property
    def expected_amount(self) -> Money:
        plus = (
            self.cod_collected
            + self.prepaid_by_shop
            + self.return_fee_paid_by_shop
            + self.promotion
        )
        minus = (
            self.shipping_fee
            + self.insurance_fee
            + self.return_shipping_fee
            + self.storage_fee
            + self.address_change_fee
            + self.inspection_fee
            + self.transfer_fee
        )
        return plus - minus


# ── Điểm tiếp xúc 2: B cung cấp, A gọi trong luồng nạp ──
@runtime_checkable
class ReconcileFn(Protocol):
    def __call__(self, statement_id: str, db: Any) -> list[dict]:
        """Đối soát toàn bộ dòng của một bảng kê, ghi `reconciliations`.

        Idempotent theo (statement_id, order_code). Trả về danh sách bản ghi reconciliation.
        """


# ── Điểm tiếp xúc 3: B cung cấp, A (webhook) gọi ──
@runtime_checkable
class ClaimService(Protocol):
    def create_draft(self, reconciliation_id: str, source: str, alert_id: str | None = None) -> dict:
        """Tạo claim nháp (trạng thái DRAFT). Idempotent theo alert_id nếu có."""


# ── Điểm tiếp xúc 4: A cung cấp, B gọi ──
@runtime_checkable
class Metrics(Protocol):
    def __call__(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Gửi custom metric. A: shipaudit.ops.*  ·  B: shipaudit.biz.*"""


# ───────────── Stub dùng khi bên kia chưa xong ─────────────
def stub_reconcile_statement(statement_id: str, db: Any) -> list[dict]:
    return [
        {
            "statement_id": statement_id,
            "order_code": "STUB-001",
            "carrier": "carrier_a",
            "expected_amount": 100_000,
            "actual_amount": 95_000,
            "diff": 5_000,
            "diff_type": "FEE_MISMATCH",
        }
    ]


class StubClaimService:
    def create_draft(self, reconciliation_id: str, source: str, alert_id: str | None = None) -> dict:
        return {"reconciliation_id": reconciliation_id, "status": "DRAFT", "source": source, "alert_id": alert_id}


def stub_metric(name: str, value: float, tags: dict[str, str] | None = None) -> None:
    print(f"[metric-stub] {name}={value} tags={tags or {}}")
