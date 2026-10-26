# Việc còn mở và chỗ tài liệu lệch nhau

Tình trạng ghi nhận ngày 21/10/2026 (cập nhật 22/10), dựa trên GitHub (main chỉ có bộ khung repo, chưa có nhánh `a/` hay `b/`) và các phiên làm việc trước. Cập nhật file này khi xong từng việc.

## Việc còn mở

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Thay `@A-GITHUB-USERNAME` trong `.github/CODEOWNERS` bằng tài khoản GitHub thật của A, và mời A vào repo | Chưa có tên tài khoản của A. Phải làm trước khi bật bắt buộc review từ code owner, nếu không PR vào thư mục của A sẽ kẹt |
| 2 | Bật branch protection cho `main` (PR + 1 approval) | Chưa biết đã bật chưa |
| 3 | Merge PR từ nhánh `docs/plan-branch-convention` | Nhánh đã đẩy lên GitHub, chưa mở PR. Chứa file kế hoạch có mục "Quy ước nhánh Git" và bản Times New Roman |
| 4 | Datadog: mời A vào tổ chức, tạo API key và Application Key cho mỗi người | Đã xong (21/10): tổ chức trial của người dùng ở site `uk1.datadoghq.com`, Agent trên máy người dùng đang báo về. Còn: mời A, tạo key (cần cho B9, A8), đổi `DD_SITE` trong `.env.example` thành `uk1.datadoghq.com` rồi báo A. Quyền Claude trên Datadog hiện chỉ đọc (MCP Write Access đang tắt) |
| 5 | Thử Time Series và Change Streams trên Atlas (việc C4) | Xong 22/10: kết nối từ máy B được; gói M0 chạy được Time Series (có TTL) và Change Streams. Đã tạo `ingest_events` dạng Time Series trên `shipaudit_b_dev` |
| 5a | Đặt lại mật khẩu người dùng Atlas `shipaudit` và xóa người dùng cũ không dùng | Mật khẩu đã xuất hiện trong khung chat. Làm sau khi kết nối chạy, nhớ cập nhật `.env` |
| 5b | Mời A dùng chung cluster (tạo người dùng riêng cho A, thêm IP của A vào Network Access) | Mỗi người một tên database khi phát triển |
| 6 | Xác minh giấy phép dataset Olist trên Kaggle, ghi vào `docs/reuse-and-data.md` | Chưa xác minh. Có phương án dự phòng 100% tổng hợp |
| 7 | Chốt tham số Carrier A/B/C (`generator/carriers/params.py`) | 22/10: B2 đã có bản đề xuất (kịch bản giả định) cùng `status_policy` cho hoàn hàng, trả hàng, hàng lỗi; hạn khiếu nại A 168h, B 72h, C 24h. 22/10 tối: người dùng đã chốt status_policy, nghĩa "trả trước", kỳ tuần ISO giờ VN và mốc hạn khiếu nại là tham số `claim_deadline_anchor` (xem `docs/decisions.md`). Còn: A xem trước khi khóa |
| 8 | Cập nhật bảng theo dõi tiến độ (mục 10 file kế hoạch) | 22/10: đã cập nhật B1–B5 trong `05-`. File Word `ShipAudit_03` chép từ `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx` nên chưa đổi theo |
| 8a | Cân nhắc Datadog RUM để theo dõi frontend và thao tác người dùng (B8/B9) | Người dùng yêu cầu ghi nhớ 22/10. Tổ chức chưa có ứng dụng RUM. Giao diện là Streamlit nên cần thử cách gắn SDK; nếu không được thì dùng log/metric phía máy chủ cho thao tác UI |
| 9 | Hồ sơ nộp: README, sơ đồ kiến trúc, mô tả sự cố, video demo, slide, khai báo AI và tái sử dụng | Xem 12 mục bài nộp trong `01-` |

## Chỗ tài liệu lệch nhau (đã biết)

1. **Docs "ShipAudit - Hồ sơ dự án" (ngày 11/10) đã cũ ở phần Giải pháp.** Nó dùng tên collection `contracts`, `shipments`, `invoices`, `findings`, `disputes` và tên metric `billing_error_rate`, `unresolved_variance_vnd`... Bản chốt là 6 collection trong `contracts/schemas/` và namespace `shipaudit.ops.*` / `shipaudit.biz.*`. Docs cũng chưa có phần Mục tiêu. Theo `contracts/` và các file `02-`, `03-` ở đây.
2. **`README.md` ở gốc repo còn viết quy tắc cũ:** "mỗi người một nhánh feature" và "đổi contract thì sửa cùng PR". Quy ước đã chốt ngày 16/10: nhánh theo mốc và đổi contract qua nhánh `contract/`. Nên sửa README cho khớp (qua PR).
3. **Bảng "Tình trạng hiện tại" trong file kế hoạch (`05-`) ghi mốc 15/10:** ghi "Code chưa bắt đầu". Đừng coi là tình trạng hiện tại.
4. **Lịch:** các mốc ghép I1 (18/10) và I2 (21/10) đã đến hạn trong khi repo mới có bộ khung. Cần xếp lại lịch cho phần còn lại (checkpoint 23/10, đóng băng 29/10, nộp 30/10).
5. `docs/decisions.md` trong repo mới có 2 dòng. `04-quyet-dinh-da-chot.md` ở đây là bản đầy đủ hơn; nên chuyển các dòng cần thiết vào `docs/decisions.md`.
