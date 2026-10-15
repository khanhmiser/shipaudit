"""Enum dùng chung. Khớp contracts/schemas/*.json."""
from enum import Enum


class DiffType(str, Enum):
    NONE = "NONE"
    FEE_MISMATCH = "FEE_MISMATCH"                  # cước tính lệch quy định
    RETURN_FEE_DOUBLE = "RETURN_FEE_DOUBLE"        # phí hoàn trừ lệch / hai lần
    MISSING_IN_STATEMENT = "MISSING_IN_STATEMENT"  # đơn đã giao thiếu trong bảng kê
    COD_MISMATCH = "COD_MISMATCH"                  # tiền thu hộ ghi thiếu / lệch
    LATE_PAYOUT = "LATE_PAYOUT"                    # tiền chuyển chậm so với hạn hẹn


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    RECOVERED = "RECOVERED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"                    # hoàn hàng
    RETURN_BY_CUSTOMER = "RETURN_BY_CUSTOMER"  # trả hàng
    DEFECTIVE = "DEFECTIVE"                  # hàng lỗi
    LOST = "LOST"


class Collections:
    CARRIER_RULES = "carrier_rules"
    ORDERS = "orders"
    STATEMENT_LINES = "statement_lines"
    RECONCILIATIONS = "reconciliations"
    CLAIMS = "claims"
    INGEST_EVENTS = "ingest_events"


# Tên tag dùng chung cho metric/log
TAG_CARRIER = "carrier"
TAG_DIFF_TYPE = "diff_type"
