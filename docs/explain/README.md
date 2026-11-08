# explain() các truy vấn chính

Database `shipaudit_b_dev`, hãng `carrier_b`, kỳ `2026-W42`, now `2026-10-19T12:00:00+07:00`. Dữ liệu: {'orders': 6000, 'statement_lines': 5948, 'reconciliations': 6045}.

Tạo bằng `python -m pipelines.explain`. File JSON đầy đủ nằm cạnh file này. Với aggregate, số key / doc / trả về là của stage đọc đầu tiên ($cursor), trước $group / $lookup; cột Index gồm cả index mà $lookup dùng.

| Truy vấn | Kế hoạch thắng (stage ← input) | Index dùng | Trả về | Key đã quét | Doc đã quét | ms |
|---|---|---|---|---|---|---|
| reconcile_lines_by_statement | FETCH ← IXSCAN(statement_order) | statement_order | 735 | 735 | 735 | 1 |
| reconcile_orders_due_in_period | FETCH ← IXSCAN(carrier_delivered_at) | carrier_delivered_at | 726 | 726 | 726 | 2 |
| diff_by_carrier | PROJECTION_SIMPLE ← FETCH ← IXSCAN(carrier_period_diff_type) | carrier_period_diff_type | 742 | 742 | 742 | 5 |
| diff_trend | GROUP ← FETCH ← IXSCAN(carrier_period_diff_type) | carrier_period_diff_type | 21 | 341 | 337 | 4 |
| missing_orders | PROJECTION_SIMPLE ← FETCH ← IXSCAN(carrier_delivered_at) | carrier_delivered_at, order_carrier | 726 | 726 | 726 | 113 |
| claims_expiring | PROJECTION_SIMPLE ← FETCH ← IXSCAN(claim_deadline_diff) | claim_deadline_diff, reconciliation_status | 101 | 140 | 137 | 20 |
