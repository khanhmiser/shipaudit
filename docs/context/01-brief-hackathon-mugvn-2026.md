# MUGVN Hackathon 2026: Real-time Operations (MongoDB × Datadog)

Nguồn: https://mini-hackathon-sep-2026.mugvn.com/ (thể lệ chi tiết: /terms, mục #submission). Thông tin lấy ngày 11/10/2026; có thể thay đổi, cần kiểm tra lại trang chính thức.

## Tổng quan
- Tổ chức: MUGVN (MongoDB User Group Vietnam). Đồng tài trợ: MongoDB và Datadog.
- Quy mô đội: 1–3 người, có 1 trưởng đội làm đầu mối và nhận giải.
- Tổng giá trị giải thưởng: USD 1.500.
- Hạn đăng ký đội: 23:59 ngày 12/10/2026 (đăng ký sau sẽ không nhận được link nộp bài).
- Hạn nộp bài: 23:59 ngày 31/10/2026.
- Liên hệ: email ghi trên trang (ẩn bằng Cloudflare); kênh hỗ trợ kỹ thuật riêng sẽ gửi cho đội đã đăng ký.

## Đề bài
Đề bài mở: tự chọn bài toán và lĩnh vực. Yêu cầu duy nhất là xây một ứng dụng dùng **MongoDB** làm nền tảng dữ liệu và **Datadog** để quan sát, phát hiện và xử lý vấn đề vận hành. Loại ứng dụng tùy ý (web app, API, dịch vụ nền, data pipeline, IoT, e-commerce, fintech, game, công cụ nội bộ...).

Bài thi phải trình diễn trọn vẹn một tình huống vận hành, từ lúc phát sinh đến lúc được xử lý, dựa trên dữ liệu thật của hệ thống mình xây:
1. Phát hiện: monitor/cảnh báo bắt được lỗi, suy giảm hoặc rủi ro vận hành đáng kể, biết trước người dùng.
2. Điều tra: kết nối metrics, logs, traces và bối cảnh vận hành để khoanh vùng nguyên nhân.
3. Phản ứng: khắc phục, rồi chứng minh hệ thống trở lại bình thường bằng dữ liệu.

Gợi ý hướng (không bắt buộc): web app/API có traffic; e-commerce, đặt hàng, thanh toán; fintech, ví điện tử, phát hiện gian lận; pipeline dữ liệu / hệ thống hướng sự kiện; IoT và telemetry; game backend, logistics, công cụ nội bộ.

## Yêu cầu kỹ thuật tối thiểu
Không đáp ứng đủ yêu cầu bắt buộc thì không được đưa vào vòng chấm.

### MongoDB
Bắt buộc:
- MongoDB là nền tảng dữ liệu vận hành chính.
- Mô hình dữ liệu hợp lý, truy cập dữ liệu hiệu quả.
- Dùng Aggregation Pipeline để phân tích dữ liệu phục vụ bài toán.
- Cách dùng MongoDB gắn chặt với bài toán vận hành đã chọn.

Khuyến khích (tùy bài toán): Time Series Collections (sensor/telemetry), Window functions (xu hướng/hành vi), `expireAfterSeconds` (vòng đời dữ liệu), Change Streams, Atlas Search, Vector Search, geospatial, xử lý hướng sự kiện, các tính năng MongoDB phù hợp khác.

### Datadog
Bắt buộc:
- Ít nhất 1 dashboard thể hiện tín hiệu vận hành và sức khỏe hệ thống.
- Ít nhất 1 monitor/alert gắn với một lỗi, suy giảm hoặc rủi ro vận hành có ý nghĩa.
- Ít nhất 1 năng lực bổ sung: Log Management, APM, Distributed Tracing, RUM, Anomaly Detection hoặc Agent Observability.
- Kết nối metrics, logs, traces và bối cảnh vận hành để hỗ trợ phát hiện, điều tra hoặc xử lý.

Tùy chọn nâng cao: AI Observability và Agent Observability (khuyến khích, không bắt buộc).

## Bài nộp gồm
1. Tên dự án và mô tả bài toán
2. Thông tin đội và đầu mối liên hệ
3. Kiến trúc giải pháp và ứng dụng
4. Kiến trúc dữ liệu và data model trên MongoDB
5. Kiến trúc observability trên Datadog
6. Repository mã nguồn và hướng dẫn cài đặt (có thể private nếu cấp quyền cho tài khoản giám khảo do BTC cung cấp)
7. README: yêu cầu môi trường, triển khai, cấu hình, các bước kiểm thử
8. MVP chạy được hoặc bản demo truy cập được
9. Video demo
10. Slide thuyết trình chung kết
11. Mô tả sự cố / tình huống vận hành được trình diễn
12. Khai báo thành phần tái sử dụng, dataset bên ngoài và công cụ AI đã dùng

## Tiêu chí chấm điểm
| Tiêu chí | Trọng số | Nội dung |
|---|---|---|
| Sáng tạo | 30% | Độc đáo của ý tưởng và cách dùng MongoDB/Datadog |
| Kỹ thuật | 30% | Kiến trúc, triển khai MongoDB và observability với Datadog |
| Tác động | 30% | Giá trị kinh doanh/vận hành và luồng phát hiện–điều tra–xử lý trọn vẹn |
| Trình bày | 10% | Chất lượng MVP, tài liệu, video demo, phần thuyết trình |

Thang điểm áp dụng tại chung kết, nhất quán với kỳ Mini Hackathon trước. Bằng điểm do ban giám khảo quyết định.

## Lịch trình (giờ Việt Nam, UTC+7)
- 25/09: mở đăng ký, công bố thể lệ
- 12/10 và 13/10: Lunch & Learn online (12:00–13:00)
  - Thứ Hai 12/10: Datadog workshop (Bang Truong): dashboard, monitor, kết nối metrics/logs/traces
  - Thứ Ba 13/10: MongoDB workshop (Jackson Nguyen): Time Series, Aggregation Pipeline, quản lý vòng đời dữ liệu
  - Link tham gia gửi qua email cho đội đã đăng ký
- 12/10, 23:59: đóng đăng ký đội
- 17/10 – 31/10: build MVP; tài khoản Datadog trial được kích hoạt trong giai đoạn này
- 31/10, 23:59: hạn nộp bài
- 01/11 – 04/11: chấm sơ loại (dự kiến)
- 05/11: công bố 8 đội chung kết (fanpage + email trưởng đội) (dự kiến)
- 08/11: chung kết online, thuyết trình và trao giải (dự kiến, giờ cụ thể sẽ cập nhật)

## Giải thưởng
- Giải nhất 15.000.000 VNĐ; nhì 10.000.000 VNĐ; ba 5.000.000 VNĐ (tổng 30.000.000 VNĐ tiền mặt)
- 8 đội chung kết đều nhận quà từ MongoDB và Datadog (áo, sticker, phụ kiện, quà công nghệ)
- Đội/cá nhân nổi bật có cơ hội nhận voucher thi chứng chỉ MongoDB (Associate Developer / DBA), số lượng có hạn

## Quy định / FAQ quan trọng
- Điều kiện: từ 18 tuổi, có tư cách pháp lý tham gia, có **email công việc** để đăng ký Datadog trial. Nhân viên của BTC, MongoDB, Datadog và người thân trực tiếp không đủ điều kiện nhận giải.
- Dùng code/template/thư viện có sẵn được nếu tuân thủ giấy phép và khai báo rõ; phần giải pháp cốt lõi phải xây trong thời gian build 17/10–31/10.
- Dùng công cụ AI viết code được nếu khai báo; đội vẫn phải hiểu và giải thích được giải pháp trước ban giám khảo.
- KHÔNG dùng dữ liệu thật của công ty (dữ liệu cá nhân, mật, production, thuộc diện quản lý). Dùng dữ liệu tổng hợp hoặc dataset công khai.
- Đội giữ toàn bộ quyền sở hữu dự án; MUGVN, MongoDB, Datadog được giới thiệu/showcase các dự án vào chung kết.
- Kỳ trước (Mini Hackathon 05/2026, chung kết 06/06/2026): 120+ lượt đăng ký, 7 đội chung kết.

## Link
- Đăng ký đội: https://docs.google.com/forms/d/e/1FAIpQLSe5ONx5FDne8fkp1qaGCFdphY6ddVFTK8-SI_em7CfbMxRvlw/viewform
- Thể lệ: https://mini-hackathon-sep-2026.mugvn.com/terms
