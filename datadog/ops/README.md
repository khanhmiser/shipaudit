# datadog/ops

[A] Dashboard, monitor vận hành và mẫu webhook: độ trễ nạp, tỉ lệ lỗi, latency p95, log lỗi (Log Management).

## Metric (do `app/` phát, namespace `shipaudit.ops.*`)

| Metric | Kiểu | Tag | Nơi phát |
|---|---|---|---|
| `ingest_lag_seconds`, `ingest_duration_ms`, `statement_rows`, `ingest_errors` | gauge | carrier, status | `app/ingest/pipeline.py`, mỗi lượt nạp |
| `ingest_runs` | count | carrier, status | mỗi lượt nạp (tính tỉ lệ lỗi) |
| `api_latency_ms.p95`, `api_latency_ms.max` | gauge (mỗi 10 giây) | route, method | `app/telemetry/http.py` |
| `api_requests` | count | route, method, status_class | `app/telemetry/http.py` |
| `fault_delay_ms`, `fault_fail_rate` | gauge | | `app/api/admin.py` khi đổi công tắc lỗi |
| `reconciliation_diff_events`, `change_stream_errors` | count | carrier, diff_type / error | `app/workers/change_stream.py` |
| `webhook_calls` | count | carrier, result | `app/api/webhooks.py` |

Giá trị tag bị Datadog đổi thành chữ thường (`status:ERROR` thành `status:error`).
Không có Datadog Agent thì đặt `DD_API_KEY` (và `DD_LOGS_AGENTLESS=true` cho log): app gửi thẳng Metrics API và Logs API.
Trace (APM) cần Agent.

## Monitor (`monitors.json`)

| Monitor | Truy vấn | Ngưỡng |
|---|---|---|
| Độ trễ nạp bảng kê cao | `max:shipaudit.ops.ingest_lag_seconds by {carrier}`, max 5 phút | cảnh báo > 2 giây, nghiêm trọng > 5 giây |
| Tỉ lệ nạp bảng kê lỗi cao | `ingest_runs{status:error} / ingest_runs`, 10 phút | cảnh báo > 10%, nghiêm trọng > 30% |
| Độ trễ API p95 cao | `max:shipaudit.ops.api_latency_ms.p95{route:/statements}`, 5 phút | cảnh báo > 1.500 ms, nghiêm trọng > 3.000 ms |
| Log lỗi nạp bảng kê (Log Management) | `service:shipaudit-api status:error @logger:shipaudit.ingest`, 5 phút | cảnh báo > 1, nghiêm trọng > 3 dòng |

Ngưỡng là kịch bản giả định cho bản demo. Kích hoạt thật bằng `python -m scenarios.ops.run` (bật công tắc lỗi nạp).

## Dashboard (`dashboard.json`)

"ShipAudit [ops] Vận hành: nạp bảng kê và API": 4 KPI (độ trễ nạp, tỉ lệ lỗi, p95 /statements, công tắc lỗi), độ trễ theo hãng, lượt nạp theo trạng thái, p95 theo route, sự kiện Change Streams, luồng log lỗi, trạng thái monitor vận hành.

## Tạo trên Datadog

```bash
python datadog/ops/apply.py --dry-run
python datadog/ops/apply.py              # cần DD_API_KEY, DD_APP_KEY, DD_SITE=uk1.datadoghq.com
```

Hoặc nhập JSON trên giao diện: Dashboard → Configure → Import dashboard JSON; Monitors → New Monitor → Import from JSON.
Id đã tạo ghi ở `deployed.json`.

## Webhook tạo claim nháp (`webhook.json`)

Mẫu cấu hình Integrations → Webhooks của Datadog cho `POST /webhooks/datadog`:
- `url`: địa chỉ công khai của API (Datadog không gọi được localhost; khi demo trên máy dùng tunnel).
- Custom header `X-ShipAudit-Secret` = giá trị WEBHOOK_SECRET trong `.env` (không ghi giá trị thật vào repo).
- Payload: `alert_id` = `$ALERT_CYCLE_KEY` (một mã cho cả vòng báo động → hết, dùng làm khóa idempotent), scope chứa tag `carrier:`.

Tạo xong webhook tên `shipaudit-claims` thì gắn vào monitor "Sắp hết hạn khiếu nại" của lớp nghiệp vụ:
`python datadog/biz/apply.py --notify @webhook-shipaudit-claims`.
