# datadog/biz

[B] Dashboard và monitor nghiệp vụ: chênh lệch vượt ngưỡng, sắp hết hạn khiếu nại, Anomaly Detection.

## Metric (do `core/metrics_job.py` phát, mỗi 60 giây)

| Metric | Tag | Ý nghĩa |
|---|---|---|
| `shipaudit.biz.diff_amount` | carrier, diff_type, deadline | Tiền doanh nghiệp nhận thiếu (VNĐ), chưa xử lý xong |
| `shipaudit.biz.diff_count` | carrier, diff_type, deadline | Số khoản tương ứng |
| `shipaudit.biz.claim_hours_left` | carrier | Giờ còn lại tới hạn khiếu nại của khoản gần hạn nhất, chặn trên 168 (168 = không còn khoản nào cần gấp) |

- "Chưa xử lý xong" = chưa có claim, hoặc claim còn DRAFT / APPROVED. Claim đã gửi hãng (SUBMITTED), đã thu hồi hoặc bị từ chối thì không tính.
- `deadline`: `expired` (đã quá hạn), `lt24h`, `lt48h`, `lt96h`, `later`. Mốc trùng với "Mức khẩn" trên giao diện.
- Mọi tổ hợp hãng × loại × mức hạn đều được phát (không có khoản nào thì là 0), nên đồ thị liền mạch và monitor tự về OK.
- Tag chung: `env` (theo DD_ENV), `service:shipaudit-biz`. `LATE_PAYOUT` không có tiền chênh lệch nên không có trong các metric tiền.
- Nguồn: Aggregation Pipeline `pipelines/open_diffs.py` ($lookup sang `claims`, $switch chia mức hạn, $facet).

Chạy:

```bash
python -m core.metrics_job --once --sink console            # in ra console, không cần Datadog
python -m core.metrics_job                                   # lặp mỗi 60 giây, gửi Datadog nếu .env có DD_API_KEY
python -m core.metrics_job --now 2026-10-19T12:00:00+07:00   # tính hạn tại một giờ cố định (hoặc đặt SHIPAUDIT_NOW)
```

Gửi thẳng lên Metrics API v2 (`https://api.<DD_SITE>/api/v2/series`) bằng DD_API_KEY, không cần Datadog Agent. Khi chạy trong compose có Agent, có thể thay bằng `metric()` của A (cùng chữ ký `Metrics`).

## Monitor (`monitors.json`)

| Monitor | Truy vấn | Ngưỡng |
|---|---|---|
| Chênh lệch nhận thiếu vượt ngưỡng | `sum:shipaudit.biz.diff_amount{!deadline:expired} by {carrier}`, max 5 phút | cảnh báo > 10 triệu, nghiêm trọng > 15 triệu VNĐ |
| Sắp hết hạn khiếu nại | `min:shipaudit.biz.claim_hours_left by {carrier}`, min 5 phút | cảnh báo < 48 giờ, nghiêm trọng < 24 giờ |
| Chênh lệch tăng bất thường (Anomaly Detection) | `anomalies(sum:shipaudit.biz.diff_amount{!deadline:expired} by {carrier}, 'basic', 2, direction='above')` | vượt dải trong 5 phút |

Ngưỡng tiền là kịch bản giả định, đặt theo dữ liệu seed: một kỳ của Carrier B thường có 5–12 triệu VNĐ nhận thiếu, Carrier A và C ít hơn.
Message có `$UI_URL` (link màn Streamlit) và `$NOTIFY` (handle thông báo, ví dụ webhook), thay lúc chạy `apply.py`.

## Dashboard (`dashboard.json`)

"ShipAudit [biz] Đối soát cước: chênh lệch và hạn khiếu nại": 4 KPI (tiền và số khoản còn trong hạn, giờ còn lại ngắn nhất, chênh lệch đã quá hạn), đồ thị theo hãng kèm dải Anomaly Detection và vạch ngưỡng, giờ còn lại theo hãng, tiền theo loại chênh lệch, số khoản theo mức hạn, trạng thái các monitor nghiệp vụ. Biến `carrier`, `env`.

## Năng lực Datadog thêm (30/10/2026, không cần Docker hay Agent)

| Năng lực | Ở đâu | Dùng để |
|---|---|---|
| Log Management (gửi thẳng Logs API) | `DD_LOGS_AGENTLESS=true` khi chạy API và Streamlit; `logs.json`: pipeline gắn tag `carrier`, `alert_id`, `monitor_id`, `claim_id`, `ui_event` và 2 log-based metric `shipaudit.biz.logs.claim_actions`, `shipaudit.biz.logs.webhook_calls` | Từ cảnh báo bấm "Related Logs" ra đúng log của hãng; lần theo `alert_id` từ monitor → webhook → claim |
| Notebook điều tra | `notebook.json` (13 ô) | Đi 5 bước: phát hiện, sát hạn, loại chênh lệch, webhook đã tạo claim chưa, kết quả xử lý; ô Kết luận để điền |
| Forecast monitor | `monitors.json` (`x_ref: forecast`) | Cảnh báo sớm khi xu hướng cho thấy tiền nhận thiếu sẽ chạm 15 triệu trong 24 giờ |
| Outlier monitor | `monitors.json` (`x_ref: outlier`) | So sánh các hãng trên cùng thước đo, báo hãng khác biệt so với nhóm (không xếp hạng); chỉ xét hãng trên 5 triệu (`clamp_min`) |
| Composite monitor + Case Management | `monitors.json` (`x_ref: composite`), `$CASE` | Chỉ khi vừa lệch lớn vừa sát hạn mới mở case (tránh nhiều case) |
| SLO (time slice) | `slos.json` | % thời gian mọi khoản nhận thiếu chưa xử lý của mỗi hãng còn ≥ 24 giờ tới hạn khiếu nại; mục tiêu 99% / 7 ngày (giả định) |
| Events | `core/events.py`, `SHIPAUDIT_DD_EVENTS=true` | Mỗi thao tác claim là một vạch đứng trên đồ thị (gộp theo hãng): tạo nháp, duyệt, gửi hãng, hoàn tiền, từ chối |

Mọi tin nhắn monitor có liên kết sang notebook (`$REF[notebook_url]`) và log của hãng. Dashboard thêm vạch sự kiện trên 2 đồ thị chính và nhóm "Điều tra và mục tiêu" (SLO, luồng log thao tác claim và webhook, liên kết notebook).

Chạy để có log và sự kiện (không Docker):

```bash
DD_LOGS_AGENTLESS=true SHIPAUDIT_DD_EVENTS=true uvicorn app.main:app --port 8000
DD_LOGS_AGENTLESS=true SHIPAUDIT_DD_EVENTS=true streamlit run ui/app.py
SHIPAUDIT_DD_EVENTS=true python -m scenarios.biz.run --db shipaudit_scenario --reset --approve-by "Tên" --recover-by "Tên"
```

Case Management (đã làm 30/10: project ShipAudit, handle `@case-shipaudit`, lưu ở `SHIPAUDIT_CASE_HANDLE` trong `.env`; làm một lần trên giao diện Datadog): Case Management → tạo project "ShipAudit" → Project Settings → Integrations → Datadog Monitors → bật để lấy handle `@case-<handle>`, rồi chạy `apply.py --case-handle @case-<handle>` (hoặc đặt `SHIPAUDIT_CASE_HANDLE`).

## Tạo trên Datadog

Đã tạo ngày 22/10/2026 (nhập JSON trên giao diện Datadog): dashboard `3ti-98m-p8s`, monitor 72687, 72690, 72691. Id và đường dẫn trong `deployed.json`. Cách thủ công: Dashboard → Configure → Import dashboard JSON; Monitors → New Monitor → Import from JSON (dán bản đã thay `$UI_URL`, `$NOTIFY`).

Cần `DD_API_KEY` và `DD_APP_KEY` trong `.env` (Application Key tạo ở Organization Settings → Application Keys), `DD_SITE=uk1.datadoghq.com`.

```bash
python datadog/biz/apply.py --dry-run
python datadog/biz/apply.py                               # tạo hoặc cập nhật theo đúng tên, ghi deployed.json
python datadog/biz/apply.py --notify @webhook-shipaudit-claims --case-handle @case-shipaudit
python datadog/biz/apply.py --only monitors               # một phần: logs | slos | notebook | monitors | dashboard
```

Thứ tự tạo: log → SLO → notebook → monitor (monitor gộp sau cùng) → dashboard; `$REF[khóa]` nối các đối tượng với nhau. Script chỉ tạo hoặc sửa dashboard / monitor có đúng tên trong JSON, không xóa gì, không đụng các dashboard / monitor khác của tổ chức.
Sửa trên giao diện Datadog thì chép lại JSON vào đây để tái tạo được.

## Ghép với webhook của A (A9)

Monitor "Sắp hết hạn khiếu nại" chỉ cho biết hãng (`{{carrier.name}}`), không chỉ ra từng đơn. Webhook nên lấy `carrier` từ `$ALERT_SCOPE` / `$TAGS`, mã alert từ `$ALERT_ID` (hoặc `$AGGREG_KEY`) rồi gọi `ClaimService.create_drafts_for_carrier(carrier, source="datadog_webhook", alert_id=..., within_hours=48)`. Idempotent theo alert id. Chỉ tạo claim nháp, con người duyệt trước khi gửi hãng.
