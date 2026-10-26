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

## Tạo trên Datadog

Đã tạo ngày 22/10/2026 (nhập JSON trên giao diện Datadog): dashboard `3ti-98m-p8s`, monitor 72687, 72690, 72691. Id và đường dẫn trong `deployed.json`. Cách thủ công: Dashboard → Configure → Import dashboard JSON; Monitors → New Monitor → Import from JSON (dán bản đã thay `$UI_URL`, `$NOTIFY`).

Cần `DD_API_KEY` và `DD_APP_KEY` trong `.env` (Application Key tạo ở Organization Settings → Application Keys), `DD_SITE=uk1.datadoghq.com`.

```bash
python datadog/biz/apply.py --dry-run
python datadog/biz/apply.py                               # tạo hoặc cập nhật theo đúng tên, ghi deployed.json
python datadog/biz/apply.py --notify @webhook-shipaudit   # khi A đã tạo webhook integration (A9)
```

Script chỉ tạo hoặc sửa dashboard / monitor có đúng tên trong JSON, không xóa gì, không đụng các dashboard / monitor khác của tổ chức.
Sửa trên giao diện Datadog thì chép lại JSON vào đây để tái tạo được.

## Ghép với webhook của A (A9)

Monitor "Sắp hết hạn khiếu nại" chỉ cho biết hãng (`{{carrier.name}}`), không chỉ ra từng đơn. Webhook nên lấy `carrier` từ `$ALERT_SCOPE` / `$TAGS`, mã alert từ `$ALERT_ID` (hoặc `$AGGREG_KEY`) rồi gọi `ClaimService.create_drafts_for_carrier(carrier, source="datadog_webhook", alert_id=..., within_hours=48)`. Idempotent theo alert id. Chỉ tạo claim nháp, con người duyệt trước khi gửi hãng.
