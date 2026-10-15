"""[A] Nghe change stream của `reconciliations`.

Có bản ghi mới với diff != 0 thì ghi log JSON (trace_id, carrier, order_code, diff)
và đếm metric shipaudit.ops.* qua app.telemetry.metrics.
"""
