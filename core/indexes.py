"""[B] Tạo index và Time Series collection. Chụp explain() các truy vấn chính vào docs/.

Mỗi index ghi rõ truy vấn nào dùng nó. Chụp explain(): `python -m pipelines.explain`
(kết quả trong docs/explain/).
"""
from __future__ import annotations

from pymongo import ASCENDING, IndexModel

from common.enums import Collections

# Time Series cho luồng nạp (A ghi): ts là BSON date, meta = {carrier, statement_id}.
INGEST_EVENTS_TTL_SECONDS = 14 * 24 * 3600

INDEXES: dict[str, list[IndexModel]] = {
    Collections.CARRIER_RULES: [
        # core.rules.load_rule: quy tắc theo hãng, version mới nhất.
        IndexModel([("carrier", ASCENDING), ("version", ASCENDING)], unique=True, name="carrier_version_unique"),
    ],
    Collections.ORDERS: [
        # Ghép dòng bảng kê với đơn ($in theo order_code), $lookup từ reconciliations.
        IndexModel([("order_code", ASCENDING)], unique=True, name="order_code_unique"),
        # Đơn đến hạn trong một kỳ (reconcile, pipelines.missing_orders).
        IndexModel([("carrier", ASCENDING), ("delivered_at", ASCENDING)], name="carrier_delivered_at"),
    ],
    Collections.STATEMENT_LINES: [
        # Đọc một bảng kê (reconcile). Unique và cùng tên với index luồng nạp của A (app/ingest/pipeline.py),
        # để hai bên tạo index trên cùng database không xung đột.
        IndexModel([("statement_id", ASCENDING), ("order_code", ASCENDING)], unique=True,
                   name="statement_order_unique"),
        # $lookup từ orders sang các dòng bảng kê của đơn (pipelines.missing_orders).
        IndexModel([("order_code", ASCENDING), ("carrier", ASCENDING)], name="order_carrier"),
    ],
    Collections.RECONCILIATIONS: [
        # Khóa idempotent của reconcile_statement.
        IndexModel([("statement_id", ASCENDING), ("order_code", ASCENDING)], unique=True,
                   name="statement_order_unique"),
        # Claims tra theo reconciliation_id.
        IndexModel([("reconciliation_id", ASCENDING)], unique=True, name="reconciliation_id_unique"),
        # Tổng hợp theo hãng / kỳ (pipelines.diff_by_carrier).
        IndexModel([("carrier", ASCENDING), ("period", ASCENDING), ("diff_type", ASCENDING)],
                   name="carrier_period_diff_type"),
        # Chênh lệch sắp hết hạn khiếu nại (pipelines.claims_expiring).
        IndexModel([("claim_deadline_at", ASCENDING), ("diff", ASCENDING)], name="claim_deadline_diff"),
        # Xu hướng theo ngày giao (pipelines.diff_trend).
        IndexModel([("diff_type", ASCENDING), ("delivered_at", ASCENDING)], name="diff_type_delivered_at"),
    ],
    Collections.CLAIMS: [
        IndexModel([("claim_id", ASCENDING)], unique=True, name="claim_id_unique"),
        IndexModel([("reconciliation_id", ASCENDING), ("status", ASCENDING)], name="reconciliation_status"),
        # Idempotent cho webhook: cùng alert và cùng đối soát chỉ ra một claim.
        IndexModel([("alert_id", ASCENDING), ("reconciliation_id", ASCENDING)], unique=True,
                   partialFilterExpression={"alert_id": {"$type": "string"}}, name="alert_reconciliation_unique"),
        IndexModel([("status", ASCENDING), ("claim_deadline_at", ASCENDING)], name="status_deadline"),
    ],
}


def ensure_time_series(db) -> bool:
    """Tạo Time Series `ingest_events` nếu chưa có. Trả về True nếu vừa tạo."""
    if Collections.INGEST_EVENTS in db.list_collection_names():
        return False
    db.create_collection(
        Collections.INGEST_EVENTS,
        timeseries={"timeField": "ts", "metaField": "meta", "granularity": "seconds"},
        expireAfterSeconds=INGEST_EVENTS_TTL_SECONDS,
    )
    return True


# Index cũ cùng khóa nhưng khác tên / tùy chọn: xóa trước khi tạo bản mới (database tạo trước 22/10).
LEGACY_INDEXES = {Collections.STATEMENT_LINES: ["statement_order"]}


def ensure_indexes(db) -> dict[str, list[str]]:
    for name, legacy in LEGACY_INDEXES.items():
        existing = set(db[name].index_information())
        for index in legacy:
            if index in existing:
                db[name].drop_index(index)
    return {name: db[name].create_indexes(models) for name, models in INDEXES.items()}
