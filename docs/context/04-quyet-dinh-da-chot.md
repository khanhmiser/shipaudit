# Các quyết định đã chốt

Gom từ các phiên làm việc 11/10 đến 16/10/2026. Mới hơn thắng cũ.

## Dự án và đội
- 11/10: chọn **ShipAudit** làm dự án chính thức cho MUGVN Hackathon 2026 (Real-time Operations, MongoDB × Datadog). Tên "ShipAudit", bỏ hậu tố "AI" trừ khi có thành phần AI thật.
- ShipAudit là hệ thống kiểm toán và đối soát cước vận tải / 3PL cho doanh nghiệp bán hàng.
- Đội 2 người. **Người dùng là B** (nghiệp vụ / data: engine quy tắc, sinh dữ liệu, Aggregation Pipeline, Streamlit, Datadog nghiệp vụ; còn phụ trách tìm nguồn dữ liệu). **A** là bạn của người dùng (IT / platform: API, nạp dữ liệu, Change Streams, telemetry, Datadog vận hành, webhook).
- Tham chiếu cách trình bày và kiểm thử: demo.edufun.ai team-649 (incident response), team-636 (AML Monitoring), team-793 (SENTRA). Chỉ học cách trình bày, các dự án đó không dùng MongoDB hay Datadog.

## Nghiệp vụ
- Công thức đối soát bắt buộc: **Tiền đối soát = Tiền thu hộ + Shop trả trước (nếu có) + Shop trả phí khi trả hàng (nếu có) − Phí giao hàng − Phí bảo hiểm (nếu có) − Phí chuyển hoàn (nếu có) − Phí lưu kho (nếu có) − Phí thay đổi địa chỉ (nếu có) − Phí đồng kiểm (nếu có) + Khuyến mãi (nếu có) − Phí chuyển khoản.** Phải phủ các ca phát sinh khi vận chuyển: hoàn hàng, trả hàng, hàng lỗi. Cài đặt tại `contracts/interfaces.py` (`Breakdown.expected_amount`).
- Chênh lệch = số tiền phải nhận − số tiền thực nhận. Năm loại: FEE_MISMATCH, RETURN_FEE_DOUBLE, MISSING_IN_STATEMENT, COD_MISMATCH, LATE_PAYOUT.
- Quản lý quy tắc từng hãng nằm trong phạm vi: dashboard và monitor Datadog cho thấy hãng nào tuân thủ quy định, hãng nào lệch, và đây là nỗi đau của khách hàng.
- Quy tắc hãng là **dữ liệu** trong `carrier_rules`, không hard-code. Ba hãng giả có ba hạn khiếu nại khác nhau, có một hãng 24 giờ.

## Cách viết (tài liệu, giao diện, slide, demo)
- Không viết câu quy kết hoặc xếp hạng độ "đáng tin" của hãng vận chuyển (đã bỏ vì quá nhạy cảm). Dùng cách nói trung tính: "sai lệch", "chênh lệch", "thiếu thước đo chung giữa các hãng", "khó so sánh các hãng".
- Hãng trong demo là hãng giả/mô phỏng (Carrier A/B/C), không gán lỗi cho thương hiệu thật.
- Khách hàng gọi là "doanh nghiệp bán hàng" (định nghĩa một lần, sau đó gọi tắt "doanh nghiệp"), gồm cả bán hàng nhỏ, vừa và lớn. Không gọi "shop".
- Bối cảnh không nhắc ShipAudit hay giải pháp. Văn phong ngắn gọn, chuyên nghiệp, không văn nói.
- Không dùng số liệu thị trường cũ trong Bối cảnh. Mọi con số về tiết kiệm hay thất thoát phải ghi rõ là kịch bản giả định.
- Tài liệu Word của dự án: phông Times New Roman, trình bày rõ ràng (người dùng chê bản Arial là khó đọc, thiếu khoa học).

## Hồ sơ dự án
- 12/10: chốt Bối cảnh, Vấn đề, Bài toán cần giải. 15/10: chốt Mục tiêu (một câu mục tiêu + 5 lợi ích có giải thích). 15/10: chốt Giải pháp, tách "Giải pháp tổng thể" rồi "Giải pháp kỹ thuật", gắn với tiêu chí chấm. Xem `02-` và `03-`.
- Các phần luồng sử dụng đầu-cuối, giới hạn và rủi ro, chỉ số thí điểm, ma trận trạng thái sản phẩm: viết sau khi code xong, chỉ ghi cái đã làm thật.

## Kiến trúc và phân việc
- Chia theo **lớp sự cố**, không chia backend/frontend: A lớp vận hành, B lớp nghiệp vụ. Mỗi người 10 việc (A1–A10, B1–B10), hai bên chỉ chạm nhau qua `contracts/` (5 điểm tiếp xúc).
- Tên metric tách namespace: A dùng `shipaudit.ops.*`, B dùng `shipaudit.biz.*`.
- `core/` không import từ `app/`. `ui/` chỉ đọc Mongo qua `core/queries.py`, không đi qua API của A. Mỗi bên dùng stub của bên kia khi chờ.
- Công nghệ: Python ≥ 3.11, FastAPI, PyMongo, Pydantic, Streamlit, pandas, ddtrace, Docker Compose, MongoDB Atlas (hoặc bản tự chạy).
- Tiền luôn là số nguyên VNĐ hoặc `Decimal`, không dùng float.

## Lịch
- Build 17/10 đến 31/10. Bốn lần ghép: I1 tối 18/10, I2 21/10, I3 24/10, I4 27/10. Checkpoint 23/10 (hết tính năng chính). Đóng băng code 29/10 (chỉ sửa lỗi). Mục tiêu tự đặt: nộp 30/10, còn 31/10 chỉ để dự phòng.

## Dữ liệu
- Dùng Olist (Kaggle) làm nền đơn hàng, lấy mẫu 5–20 nghìn đơn, đổi sang VNĐ bằng hệ số cố định; phần COD, hãng, bảng kê, chênh lệch là tự sinh. Có chế độ dự phòng 100% tổng hợp (`--source synthetic`). Seed cố định. Giấy phép Olist chưa xác minh.
- Chỉ dùng dữ liệu tổng hợp hoặc công khai. Không dùng dữ liệu thật của công ty.
- Sinh luôn `labels.json` (đáp án chênh lệch đã cài) để kiểm thử phát hiện đủ 100%.

## Git (chốt 16/10)
- `main` được bảo vệ (PR + 1 approval), không có nhánh `develop`.
- Nhánh theo mốc: A `a/m1-ingest-skeleton`, `a/m2-api-telemetry`, `a/m3-datadog-ops-webhook`, `a/m4-incident-ops`; B `b/m1-rules-and-data`, `b/m2-engine-pipelines`, `b/m3-streamlit-datadog-biz`, `b/m4-incident-biz`.
- `docs/submission` là nhánh chung cho README, sơ đồ, mô tả sự cố, nhật ký AI, khai báo tái sử dụng, kịch bản video.
- Mọi thay đổi trong `contracts/` đi qua nhánh `contract/<mô tả>`, cả A và B duyệt, tăng `contracts/VERSION`. Không sửa `contracts/` trong nhánh `a/` hay `b/`.
- Nhánh sống tối đa 2–3 ngày, PR nhỏ, người kia duyệt trong 12 giờ, merge xong thì xóa. Gắn tag `v1.0-submission` trước khi nộp.
- Không commit `.env`, khóa Datadog, chuỗi kết nối Atlas. Lỡ commit thì xoay khóa.

## Môi trường (chốt 21–22/10)
- 22/10: dùng **MongoDB Atlas** (cluster miễn phí `Cluster0`, bản 8.0.34, replica set 3 nút) làm nơi chạy chính, thay vì MongoDB cài trên máy. Người dùng database `shipaudit`; B phát triển trên database `shipaudit_b_dev`. Chuỗi kết nối chỉ nằm trong `.env`. Chưa xác nhận kết nối từ máy; nên đặt lại mật khẩu sau khi chạy ổn.
- 21/10: Datadog đã nối. Tổ chức trial ở site `uk1.datadoghq.com` (không phải site mặc định), nên `DD_SITE=uk1.datadoghq.com`. Quyền của Claude trên Datadog chỉ đọc; dashboard và monitor của ShipAudit tạo bằng API key và Application Key, đặt tên có tiền tố `ShipAudit`.
- 21/10: khi xong hoặc đổi trạng thái một việc, cập nhật cả bản Markdown (`docs/word/src/theo-doi-tien-do.md`) và bản Word (`bash docs/word/build.sh`).

- 22/10: chốt 4 điểm nghiệp vụ (chi tiết ở `docs/decisions.md`): `status_policy` giữ như bản B2; "trả trước" và "trả phí khi trả hàng" là khoản đã nộp ngoài bảng kê, cộng lại trong công thức; kỳ đối soát là tuần ISO giờ VN; mốc hạn khiếu nại là tham số `claim_deadline_anchor` theo hãng (mặc định lúc nhận bảng kê; thực tế luật là 1 tháng kể từ ngày phát).

## Khai báo bắt buộc của đề
- Ghi công cụ AI vào `docs/ai-usage-log.md` và thư viện, dataset ngoài vào `docs/reuse-and-data.md` ngay khi dùng, để cuối kỳ khai báo không phải nhớ lại. Đội phải hiểu và giải thích được mọi phần code do AI viết.
