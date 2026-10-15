"""[A] Luồng nạp: lưu file > parse > ghi statement_lines > reconcile_statement > ghi ingest_events.

Gọi B qua contracts.interfaces.ReconcileFn (dùng stub_reconcile_statement khi B chưa xong).
Ghi ingest_events (Time Series) với: carrier, rows, duration_ms, status, lag_seconds.
"""
