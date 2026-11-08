# Kịch bản video demo ShipAudit

Khán giả: ban giám khảo và người xem không chuyên về vận tải. Lời dẫn dùng tiếng thường, giải thích thuật ngữ ngay lần đầu, mỗi cảnh mở bằng một câu "cảnh này để làm gì".
Thời lượng đề xuất: **5–6 phút** (đề không quy định độ dài; nếu BTC có giới hạn thì cắt cảnh 6 và rút gọn cảnh 5).
Dữ liệu: bộ `chat_v1`, 100% tổng hợp, hãng giả định Carrier A/B/C. Mọi con số tiền trong video là **kịch bản giả định**.
Cách chạy máy để quay: `.\scripts\demo.ps1 -Tunnel` (giờ mô phỏng 23/10 08:00), xem `docs/demo-cho-giam-khao.md` mục 5.

## Chuẩn bị trước khi bấm quay

- [ ] Cluster Atlas đang chạy (Resume nếu bị tạm dừng); `.env` đúng `MONGO_DB`.
- [ ] Datadog còn truy cập được (trial uk1 hết khoảng 1/11). Nếu mất, dựng lại theo `docs/demo-cho-giam-khao.md` mục 3 trước khi quay.
- [ ] Cập nhật URL webhook `shipaudit-claims` theo địa chỉ tunnel mới.
- [ ] Mở sẵn các tab: dashboard `ShipAudit [biz]`, danh sách monitor, notebook điều tra, Log Explorer, giao diện Streamlit.
- [ ] Độ phân giải 1920×1080, phóng to chữ trình duyệt 110–125%, tắt thông báo hệ thống.
- [ ] Che hoặc không mở `.env`, khóa Datadog, chuỗi kết nối Atlas.
- [ ] Quay thử một lượt, bám đúng thứ tự dưới đây.

## Cảnh 1 · Vấn đề (0:00–0:40)

**Hình:** trang Tổng quan của giao diện (hoặc một slide có 3 hãng, 3 bảng kê).
**Lời dẫn:**
> Hãy hình dung một doanh nghiệp bán hàng online, mỗi ngày gửi hàng trăm đơn qua nhiều hãng vận chuyển. Hãng giao hàng, thu tiền hộ, rồi cuối kỳ gửi một bảng kê trả lại tiền.
> Mỗi hãng một cách tính phí, một hạn khiếu nại riêng. Số tiền thực nhận hay lệch so với số đáng lẽ phải nhận, nhưng gần như không ai kiểm từng đơn, và khi phát hiện thì đã quá hạn đòi lại.
> ShipAudit tính số tiền phải nhận của từng đơn theo quy tắc của hãng, so với số tiền thực nhận, và cảnh báo theo hạn khiếu nại.

## Cảnh 2 · Cách tính và dữ liệu (0:40–1:30)

**Hình:** trang Chi tiết đơn của một đơn lệch phí; sau đó lướt qua sơ đồ kiến trúc (nếu có).
**Lời dẫn:**
> Với mỗi đơn, hệ thống tính số tiền đáng lẽ phải nhận bằng một công thức cố định: lấy tiền thu hộ, trừ phí giao, phí bảo hiểm, phí chuyển hoàn và các phí phát sinh khác, trừ phí chuyển khoản.
> Quy tắc của từng hãng được lưu như dữ liệu, nên đổi bảng giá không phải sửa chương trình. Và việc tính tiền hoàn toàn theo quy tắc, không dùng AI đoán, nên kết quả khớp từng đồng.
> Chênh lệch là số phải nhận trừ số thực nhận, gồm năm loại: sai phí, phí hoàn hàng bị tính hai lần, đơn thiếu trong bảng kê, lệch tiền thu hộ, và trả tiền trễ.
> Dữ liệu demo: 5.308 đơn, 24 bảng kê của 3 hãng trong 8 tuần, 352 khoản chênh lệch, đều là dữ liệu tổng hợp.

**Nhấn:** trên Chi tiết đơn, chỉ ra từng dòng phí và chỗ lệch so với quy tắc hãng.

## Cảnh 3 · Sự cố: sắp hết hạn khiếu nại (1:30–2:40)

**Hình:** dashboard Datadog `ShipAudit [biz]`, rồi danh sách monitor.
**Lời dẫn:**
> Đây là phần quan trọng nhất. Trong kịch bản giả định, Carrier C chỉ còn khoảng 18 giờ nữa là hết hạn khiếu nại, mà vẫn còn các khoản chênh lệch chưa xử lý. Hết hạn là doanh nghiệp mất quyền đòi lại.
> Dashboard Datadog cho thấy số tiền lệch, số khoản và số giờ còn lại của từng hãng. Cảnh báo "Sắp hết hạn khiếu nại" chuyển đỏ.

**Nhấn:** chỉ vào biểu đồ giờ còn lại, trạng thái monitor, vạch sự kiện.

## Cảnh 4 · Cảnh báo tạo claim nháp tự động (2:40–3:30)

**Hình:** Datadog (monitor/webhook, sự kiện "Tạo claim nháp") → trang Claims của giao diện.
**Lời dẫn:**
> Khi cảnh báo đỏ, Datadog tự gọi sang ShipAudit, và hệ thống soạn sẵn các bản nháp khiếu nại cho hãng đó. Báo lại nhiều lần cũng không tạo trùng.
> Hệ thống không tự gửi gì cho hãng: người phụ trách phải duyệt trước.

**Nhấn:** claim nháp xuất hiện trên Claims; log webhook trong Log Explorer.

## Cảnh 5 · Điều tra bằng Datadog (3:30–4:20)

**Hình:** notebook điều tra → Log Explorer lọc `service:(shipaudit-api OR shipaudit-ui)`.
**Lời dẫn:**
> Muốn biết vì sao cảnh báo đỏ, ta mở sổ điều tra: loại chênh lệch nào, bảng kê nào, và nhật ký hệ thống của chính cảnh báo đó. Từ một cảnh báo lần ra được đúng claim và đúng đơn.
> Đội còn dùng thêm mục tiêu chất lượng dịch vụ, cảnh báo dự báo, cảnh báo so sánh hãng và quản lý công việc của Datadog để theo dõi cả quy trình.

## Cảnh 6 · Duyệt, gửi và thu hồi (4:20–5:30)

**Hình:** trang Claims: duyệt hàng loạt → ghi nhận đã gửi hãng → ghi nhận hãng hoàn tiền → Tổng quan.
**Lời dẫn:**
> Người phụ trách xem lý do lệch của từng đơn, duyệt cả loạt, rồi ghi nhận đã gửi hãng.
> Khi hãng hoàn tiền, ghi nhận thu hồi: thẻ "Đã thu hồi" ở Tổng quan tăng, dashboard có nhóm "Kết quả khiếu nại", monitor trở về bình thường.
> Nếu hãng từ chối, hệ thống bắt buộc ghi lý do, lưu nhật ký trao đổi và hẹn liên hệ lại.

**Nhấn:** thẻ Tổng quan trước và sau; monitor về OK.

## Cảnh 7 · MongoDB và kết (5:30–6:00)

**Hình:** trang So sánh hãng, rồi slide tóm tắt.
**Lời dẫn:**
> Toàn bộ dữ liệu nằm trên MongoDB Atlas. Các bảng tổng hợp theo hãng, theo tuần và theo hạn khiếu nại do chính cơ sở dữ liệu tính (Aggregation Pipeline), có chỉ mục và đã kiểm chứng tốc độ truy vấn.
> Trang So sánh hãng đặt các hãng trên cùng một thước đo, không xếp hạng hãng nào đáng tin hơn.
> ShipAudit giúp doanh nghiệp biết mình lệch bao nhiêu, lệch ở đâu, và còn bao lâu để đòi lại.
> Giám khảo có thể tự xem bản demo chỉ xem qua link trong bài nộp; khóa truy cập Datadog và MongoDB được gửi riêng (không hiện trong video).

## Ghi chú khi quay

- Nói chậm, mỗi cảnh dừng 1–2 giây trên màn hình trước khi chỉ chuột.
- Gọi khách hàng là "doanh nghiệp"; dùng đúng thuật ngữ: số tiền phải nhận, số tiền thực nhận, chênh lệch, hạn khiếu nại.
- Nêu rõ số liệu là dữ liệu tổng hợp, kịch bản giả định; không dùng số liệu thị trường.
- Nếu một bước lỗi khi quay, dừng và quay lại cảnh đó; ghép sau.
- Ngoài video, chụp ảnh: dashboard, 6 monitor nghiệp vụ + 4 monitor vận hành, monitor đang báo động, notebook, SLO, Log Explorer, Event Explorer `project:shipaudit`, work item `SHIP-…`.
