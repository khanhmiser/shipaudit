---
title: "Brief hackathon và checklist"
author: "ShipAudit · MUGVN Hackathon 2026 · Real-time Operations (MongoDB × Datadog)"
date: "Cập nhật 22/10/2026 · brief lấy ngày 11/10/2026, cần kiểm tra lại trang chính thức"
---

# 1. Thông tin chính

| Hạng mục | Nội dung |
|--------------------|--------------------------------------------------------------------------------|
| Tổ chức | MUGVN (MongoDB User Group Vietnam). Đồng tài trợ: MongoDB và Datadog |
| Đội | 1 đến 3 người, có 1 trưởng đội làm đầu mối và nhận giải |
| Hạn nộp bài | 23:59 ngày 31/10/2026 |
| Build MVP | 17/10 đến 31/10. Tài khoản Datadog trial được kích hoạt trong giai đoạn này |
| Sau khi nộp | 01/11 đến 04/11 chấm sơ loại. 05/11 công bố 8 đội chung kết. 08/11 chung kết online (đều là dự kiến) |
| Giải thưởng | Nhất 15.000.000 VNĐ, nhì 10.000.000 VNĐ, ba 5.000.000 VNĐ. 8 đội chung kết đều nhận quà từ MongoDB và Datadog |
| Trang chính thức | mini-hackathon-sep-2026.mugvn.com (thể lệ: /terms, mục #submission) |

# 2. Đề bài và luồng phải trình diễn

Đề bài mở: tự chọn bài toán. Yêu cầu duy nhất là xây ứng dụng dùng **MongoDB** làm nền tảng dữ liệu và **Datadog** để quan sát, phát hiện và xử lý vấn đề vận hành. Bài thi phải trình diễn trọn vẹn một tình huống vận hành, dựa trên dữ liệu của chính hệ thống mình xây:

1. **Phát hiện:** monitor hoặc cảnh báo bắt được lỗi, suy giảm hoặc rủi ro vận hành, biết trước người dùng.
2. **Điều tra:** kết nối metrics, logs, traces và bối cảnh vận hành để khoanh vùng nguyên nhân.
3. **Phản ứng:** khắc phục, rồi chứng minh hệ thống trở lại bình thường bằng dữ liệu.

# 3. Yêu cầu bắt buộc và cách ShipAudit đáp ứng

Không đáp ứng đủ yêu cầu bắt buộc thì không được đưa vào vòng chấm.

| Yêu cầu bắt buộc | ShipAudit đáp ứng bằng | Trạng thái (21/10) |
|--------------------------------|-------------------------------------------|--------------------------|
| MongoDB là nền tảng dữ liệu vận hành chính | 6 collection: carrier_rules, orders, statement_lines, reconciliations, claims, ingest_events | Đang làm: đủ 6 collection trên Atlas (claims có code và test, ingest_events là Time Series). Luồng nạp của A đã có trên nhánh `a/m1-ingest-skeleton` (22/10, chờ A duyệt): ghi statement_lines, reconciliations, ingest_events; đã thử trên Atlas |
| Mô hình dữ liệu hợp lý, truy cập hiệu quả | Schema trong contracts/schemas/, index và chụp explain() | Xong phía B (22/10): 13 index, `docs/explain/` cho 6 truy vấn chính, đều dùng index |
| Dùng Aggregation Pipeline | 4 pipeline trong pipelines/: $lookup, $facet, $setWindowFields, claim sắp hết hạn | Xong (22/10), có test trên dữ liệu seed |
| Cách dùng MongoDB gắn chặt với bài toán | Chênh lệch, đơn thiếu, xu hướng và hạn khiếu nại đều tính bằng pipeline | Chưa làm |
| Ít nhất 1 dashboard Datadog | Dashboard vận hành (A) và dashboard nghiệp vụ (B) | Có: dashboard nghiệp vụ `3ti-98m-p8s` và dashboard vận hành `yh5-e7m-dd2` trên Datadog, có metric thật (22/10) |
| Ít nhất 1 monitor gắn với rủi ro có ý nghĩa | Độ trễ nạp, chênh lệch vượt ngưỡng, sắp hết hạn khiếu nại | Đang làm: 3 monitor nghiệp vụ (chênh lệch vượt ngưỡng, sắp hết hạn khiếu nại, Anomaly Detection) Có: 3 monitor nghiệp vụ (72687, 72690, 72691) và 4 monitor vận hành (72794–72797), đều đã kích hoạt thật bằng kịch bản rồi về OK (22/10) |
| Ít nhất 1 năng lực bổ sung | Log Management và APM (ddtrace); thêm Anomaly Detection | Đang làm: log JSON và ddtrace cho FastAPI có trên nhánh `a/m2-api-telemetry` (22/10); Có (22/10): Anomaly Detection (monitor 72691 đã kích hoạt thật) và Log Management (log lỗi nạp gửi thẳng Logs API, monitor log 72797 đã kích hoạt thật). APM cần Datadog Agent nên chưa có 30/10: thêm log giao diện và webhook gửi thẳng Logs API (đã thấy trên Datadog), sự kiện claim (Events, đã thấy trên Datadog); đã viết và test, chờ Application Key để tạo: Forecast, Outlier, Composite monitor, SLO time slice, notebook điều tra, Case Management. 30/10 (tối): đã tạo thật Forecast, Outlier, Composite, SLO, notebook, pipeline log; Outlier đã báo thật. |
| Kết nối metrics, logs, traces và bối cảnh vận hành | Log JSON kèm trace_id, carrier, order_code; metric shipaudit.ops.* và shipaudit.biz.* | Đang làm (22/10): metric shipaudit.ops.* và shipaudit.biz.* đã lên Datadog; log JSON kèm carrier, statement_id, error_kind lên Log Management; monitor dẫn sang log và dashboard. Trace (APM) và trace_id thật trong log cần Datadog Agent (Docker), chưa thử 30/10: log mang tag `carrier`, `alert_id`, `claim_id` giống metric; tin nhắn monitor dẫn sang notebook và log của hãng; vạch sự kiện claim trên đồ thị. Log của API đã có `trace_id` (ddtrace), trace thật vẫn cần Agent. |
| Luồng phát hiện, điều tra, phản ứng trọn vẹn | Kịch bản hai lớp: vận hành (A) và nghiệp vụ (B), có webhook tạo claim nháp | Có (22/10): cả hai lớp chạy trọn trên Datadog. Nghiệp vụ: monitor kích hoạt, claim nháp, duyệt, gửi hãng, về OK. Vận hành: bật công tắc lỗi nạp, 4 monitor kích hoạt, điều tra bằng log, tắt công tắc, về OK. Webhook có code và test nhưng Datadog chưa gọi thật (cần địa chỉ công khai) 30/10: webhook Datadog gọi thật qua tunnel, tạo 181 claim nháp; duyệt, gửi hãng, hãng hoàn tiền (Đã thu hồi), cả 9 nhóm monitor về OK. |
| Chỉ dùng dữ liệu tổng hợp hoặc công khai | Olist làm nền, tự sinh phần còn lại; hãng giả Carrier A/B/C | Xong phần dữ liệu demo (23/10): bộ chat_v1 100% tổng hợp, hãng giả Carrier A/B/C, khai báo trong docs/reuse-and-data.md. Olist chưa dùng (giấy phép chưa xác minh) |
| Khai báo công cụ AI, thành phần tái sử dụng, dataset ngoài | docs/ai-usage-log.md, docs/reuse-and-data.md | Có khung, đang bổ sung |

# 4. Danh sách bài nộp (12 mục)

| # | Bài nộp | Nằm ở đâu | Trạng thái (21/10) |
|------|---------------------------------|------------------------------|-------------------------------|
| 1 | Tên dự án và mô tả bài toán | Hồ sơ dự án (file Word số 01) | Đã có bản chốt |
| 2 | Thông tin đội và đầu mối liên hệ | Chưa có file | Chưa làm, còn thiếu tên A và trưởng đội |
| 3 | Kiến trúc giải pháp và ứng dụng | Hồ sơ dự án, mục Giải pháp kỹ thuật | Có văn bản, chưa có sơ đồ trong repo |
| 4 | Kiến trúc dữ liệu và data model MongoDB | contracts/schemas/ và sơ đồ data model | Có schema, chưa có sơ đồ |
| 5 | Kiến trúc observability trên Datadog | datadog/ops/, datadog/biz/ | Đang làm: `datadog/biz/` và `datadog/ops/` có dashboard, monitor, `apply.py`, README, `deployed.json` (22/10) |
| 6 | Repository mã nguồn và hướng dẫn cài đặt | github.com/khanhmiser/shipaudit | Có khung. Nếu để private, phải cấp quyền cho tài khoản giám khảo |
| 7 | README: môi trường, triển khai, cấu hình, kiểm thử | README.md | Có bản ngắn, chưa hoàn chỉnh |
| 8 | MVP chạy được hoặc bản demo truy cập được | docker compose up | Đang làm: chạy được trên máy không Docker (API, worker, UI, job metric); Dockerfile và compose đã sửa 23/10, chưa chạy `docker compose up` 30/10: bản demo cho giám khảo đã chuẩn bị (giao diện chỉ xem, sẵn sàng Streamlit Community Cloud, `scripts/demo.ps1`, `docs/demo-cho-giam-khao.md`); link tạm qua tunnel đã chạy thử. Còn: đẩy repo, triển khai, người dùng Atlas chỉ đọc. |
| 9 | Video demo | Chưa có | Chưa làm 30/10: kịch bản quay đã viết (`docs/demo-cho-giam-khao.md` mục 5); phải quay trước khi trial Datadog hết (khoảng 1/11). |
| 10 | Slide thuyết trình chung kết | Chưa có | Chưa làm (cần khi vào chung kết) |
| 11 | Mô tả sự cố / tình huống vận hành được trình diễn | docs/submission | Có khung kịch bản hai lớp, chưa viết đầy đủ |
| 12 | Khai báo thành phần tái sử dụng, dataset ngoài, công cụ AI | docs/ai-usage-log.md, docs/reuse-and-data.md | Có khung, giấy phép Olist chưa xác minh |

# 5. Tiêu chí chấm điểm

| Tiêu chí | Trọng số | Nội dung |
|------------------|--------------|--------------------------------------------------------------------|
| Sáng tạo | 30% | Độc đáo của ý tưởng và cách dùng MongoDB, Datadog |
| Kỹ thuật | 30% | Kiến trúc, triển khai MongoDB và observability với Datadog |
| Tác động | 30% | Giá trị kinh doanh, vận hành và luồng phát hiện, điều tra, xử lý trọn vẹn |
| Trình bày | 10% | Chất lượng MVP, tài liệu, video demo, phần thuyết trình |

# 6. Quy định cần nhớ

- Dùng code, template, thư viện có sẵn được nếu tuân thủ giấy phép và khai báo rõ. Phần giải pháp cốt lõi phải xây trong thời gian build 17/10 đến 31/10.
- Dùng công cụ AI viết code được nếu khai báo. Đội vẫn phải hiểu và giải thích được giải pháp trước ban giám khảo.
- **Không** dùng dữ liệu thật của công ty (dữ liệu cá nhân, mật, production, thuộc diện quản lý). Dùng dữ liệu tổng hợp hoặc dataset công khai.
- Cần email công việc để đăng ký Datadog trial. Thành viên phải từ 18 tuổi trở lên.
- Đội giữ toàn bộ quyền sở hữu dự án. MUGVN, MongoDB, Datadog được giới thiệu các dự án vào chung kết.
