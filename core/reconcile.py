"""[B] reconcile_statement(statement_id, db): ghép dòng bảng kê với đơn, tính diff,
phân loại diff_type, tính claim_deadline_at, ghi `reconciliations`.

Idempotent theo (statement_id, order_code). Khớp contracts.interfaces.ReconcileFn.
"""


def reconcile_statement(statement_id: str, db) -> list[dict]:
    # TODO(B): cài thật.
    raise NotImplementedError
