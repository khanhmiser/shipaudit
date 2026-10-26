# Giải pháp đã chốt (tổng thể + kỹ thuật)

Chốt ngày 15/10/2026 ("chốt giải pháp này"). File này tóm lại nội dung đã chốt để code đúng thiết kế. Bản văn đầy đủ (kèm 3 sơ đồ) nằm ở file Word "Giải pháp" xuất theo yêu cầu ngày 15/10, nếu người dùng còn giữ; không có trong repo. Bản "Hồ sơ dự án" trên Docs còn phần Giải pháp CŨ (ngày 11/10, đặt tên collection khác); khi mâu thuẫn, theo file này và `contracts/`.

## Giải pháp tổng thể

ShipAudit tính **số tiền phải nhận** của từng đơn theo quy tắc từng hãng, so với **số tiền thực nhận**, và cảnh báo chênh lệch theo hạn khiếu nại.

Mỗi insight trong "Vấn đề" có một cách xử lý:

| Insight | Cách xử lý |
|---|---|
| Mỗi hãng một bộ quy tắc | Quản lý quy tắc theo hãng (`carrier_rules`, là dữ liệu) và thước đo chung giữa các hãng |
| Chênh lệch phát sinh ở nhiều khâu | Tính lại từng đơn theo công thức đối soát đã chốt |
| Thiếu số tiền phải nhận để đối chiếu | Tính sẵn số phải nhận cho từng đơn |
| Thời hạn khiếu nại ngắn | Đồng hồ đếm ngược hạn khiếu nại (`claim_hours_left`) |

Luồng: phát hiện, điều tra, phản ứng, chứng minh phục hồi.

Nguyên tắc thiết kế:
- Mỗi chênh lệch truy vết được bằng chứng (dòng gốc của bảng kê, breakdown từng khoản, quy tắc hãng đã dùng).
- Con người duyệt trước khi gửi khiếu nại cho hãng (claim nháp, rồi duyệt).
- Số tiền do quy tắc xác định (deterministic) tính. Không dùng AI/LLM để tính tiền.

Ba sơ đồ đã chọn cho phần Giải pháp: kiến trúc tổng thể; luồng phát hiện, điều tra, phản ứng, chứng minh phục hồi; data model MongoDB.

## Giải pháp kỹ thuật

Viết theo tiêu chí chấm (Kỹ thuật 30%, Tác động 30%) để giám khảo kiểm từng yêu cầu.

**Kiến trúc:** Bảng kê / đơn → FastAPI → MongoDB → Streamlit. Datadog thu metrics, log, trace và gọi webhook ngược về FastAPI. Chạy bằng Docker Compose, dữ liệu tổng hợp, hãng giả Carrier A/B/C.

**MongoDB**
- Collection: `carrier_rules`, `orders`, `statement_lines`, `reconciliations`, `claims`, cộng Time Series `ingest_events` (có `expireAfterSeconds`).
- Aggregation Pipeline: `$lookup` (đối chiếu bảng kê với đơn, tìm đơn thiếu), `$facet` (tổng chênh lệch theo hãng/loại), `$setWindowFields` (xu hướng chênh lệch theo thời gian).
- Change Streams (worker nghe `reconciliations`), index kiểm bằng `explain()`.

**Datadog**
- Dashboard (nghiệp vụ + vận hành); monitor: chênh lệch vượt ngưỡng, sắp hết hạn khiếu nại, độ trễ nạp, Anomaly Detection.
- Log Management + APM (ddtrace, liên kết log-trace), custom metrics (`shipaudit.ops.*` của A, `shipaudit.biz.*` của B).
- Webhook: monitor gọi `POST /webhooks/datadog`, backend tạo claim nháp (idempotent theo alert id).
- JSON dashboard và monitor lưu trong repo (`datadog/ops/`, `datadog/biz/`) để tái tạo được.

**Ranh giới nói thật:** kết quả trên dữ liệu tổng hợp chỉ chứng minh tích hợp và khả năng chạy lại, không chứng minh hiệu quả trên dữ liệu thật.

## Kịch bản sự cố hai lớp (khung cho demo)

- Lớp vận hành (A): bật công tắc lỗi nạp (độ trễ hoặc tỉ lệ lỗi), `ingest_lag_seconds` tăng, monitor kích hoạt, điều tra bằng log và trace, tắt công tắc, chứng minh phục hồi bằng dữ liệu.
- Lớp nghiệp vụ (B): nạp bảng kê Carrier B có nhiều đơn bị trừ lệch, một số sát hạn khiếu nại. Monitor chênh lệch vượt ngưỡng và sắp hết hạn kích hoạt, webhook tạo claim nháp, người duyệt, chứng minh đã xử lý bằng dữ liệu.

## Phần để viết SAU khi code xong (chỉ ghi cái đã làm thật)

Luồng sử dụng đầu-cuối; giới hạn và rủi ro còn lại; chỉ số thí điểm đề xuất; ma trận trạng thái sản phẩm.
