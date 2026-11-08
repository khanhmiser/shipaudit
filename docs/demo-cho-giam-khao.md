# Bản demo cho giám khảo

Mục tiêu: giám khảo xem được ShipAudit **không cần máy của đội bật**, **không sửa được dữ liệu** (giao diện chỉ xem); khóa truy cập cấp riêng khi giám khảo cần tự kiểm tra.
Dữ liệu demo là bộ `chat_v1`: 100% tổng hợp, hãng giả định Carrier A/B/C (5.308 đơn, 24 bảng kê 3 hãng × 8 tuần W35–W42,
5.281 bản ghi đối soát, 352 khoản chênh lệch).

| Phần | Giám khảo xem bằng | Ghi chú |
|---|---|---|
| Giao diện doanh nghiệp | Link Streamlit Community Cloud (chỉ xem) | Chạy 24/7, không phụ thuộc máy của đội |
| Datadog | Tài khoản Read Only hoặc link dashboard công khai; ảnh chụp và video | Trial hiện tại hết khoảng 1/11/2026 |
| Luồng sự cố đầy đủ | Video demo | Bắt buộc theo đề |
| Mã nguồn | Repo GitHub, cấp quyền cho tài khoản giám khảo BTC cung cấp | README có cách chạy lại |

## 0. Làm ngay, trước khi trial Datadog hết (khoảng 1/11/2026)

Tổ chức Datadog hiện tại (uk1) báo "2 days left in your trial" ngày 30/10. Sau khi hết hạn, giám khảo không mở được gì trên đó.

1. Quay video luồng đầy đủ (xem mục 5).
2. Chụp ảnh: dashboard `ShipAudit [biz]` (có vạch sự kiện), danh sách 6 monitor nghiệp vụ và 4 monitor vận hành, một monitor
   đang báo động, notebook điều tra, SLO, Log Explorer lọc `service:(shipaudit-api OR shipaudit-ui)`, Event Explorer
   `project:shipaudit`, work item `SHIP-…` trong Work Management.
3. Giữ JSON trong `datadog/biz/` và `datadog/ops/` để dựng lại trên tài khoản khác (mục 3).

## 1. Dữ liệu demo cố định trên Atlas

1. Nạp bộ demo vào database riêng `shipaudit_demo` (đối soát lại và so với `labels.json`):
   `make seed-chat` hoặc `python -m generator.chat_v1 --db shipaudit_demo --reset`.
2. Tạo người dùng **chỉ đọc** cho bản demo: Atlas → Database Access → Add New Database User → Password → Database User
   Privileges → Specific Privileges → `read` trên database `shipaudit_demo`. Ví dụ tên `demo_readonly`. Không dùng tài khoản `shipaudit`.
3. Network Access: thêm `0.0.0.0/0` (Streamlit Community Cloud không có IP cố định). Chấp nhận được vì người dùng chỉ đọc và
   dữ liệu tổng hợp; gỡ sau khi chấm.
4. Gói miễn phí có thể tạm dừng khi lâu không dùng: kiểm tra cluster đang chạy trước ngày chấm.

## 2. Giao diện trên Streamlit Community Cloud

1. Đẩy repo (nhánh có code mới) lên GitHub. Repo private vẫn được.
2. Vào share.streamlit.io, đăng nhập bằng GitHub, chọn **Create app** → **Deploy a public app from GitHub**:
   - Repository, branch: repo và nhánh vừa đẩy.
   - Main file path: `ui/app.py`.
   - App URL: ví dụ `shipaudit-demo` (thành `shipaudit-demo.streamlit.app`).
   - Advanced settings → Python 3.12; **Secrets**: dán nội dung theo `.streamlit/secrets.toml.example`
     (`MONGO_URI` của người dùng chỉ đọc, `MONGO_DB = "shipaudit_demo"`, `SHIPAUDIT_NOW`, `SHIPAUDIT_READ_ONLY = "true"`).
3. Community Cloud cài thư viện từ `requirements.txt` (chỉ phần giao diện). Không cần đặt khóa Datadog ở đây.
4. Kiểm tra bằng cửa sổ ẩn danh: thanh bên có dòng "Bản demo chỉ xem", không có nút duyệt, gửi hãng, ghi nhận thu hồi;
   các trang Tổng quan, Chênh lệch, Chi tiết đơn, Hạn khiếu nại, Claims, So sánh hãng, Thông tin hãng đều mở được.
5. Ứng dụng ngủ khi lâu không có người xem; lần mở đầu mất vài chục giây để chạy lại. Mở link một lần trước giờ chấm.

Chế độ chỉ xem (`SHIPAUDIT_READ_ONLY=true`) chỉ ẩn nút trên giao diện; người dùng Atlas chỉ đọc là lớp chặn thứ hai.

## 3. Datadog cho giám khảo

- **Tổ chức hiện tại còn hạn:** Organization Settings → Users → Invite Users, email giám khảo, vai trò **Datadog Read Only Role**.
  Gửi kèm link dashboard, notebook, SLO, monitor (trong `datadog/biz/deployed.json`, `datadog/ops/deployed.json`).
- **Link dashboard công khai:** mở dashboard → Share → Generate public URL. Chỉ chia sẻ được dashboard, không gồm log và monitor.
- **Sau khi trial hết, dựng lại trên tài khoản khác:**
  1. `.env`: `DD_API_KEY`, `DD_APP_KEY`, `DD_SITE` của tài khoản mới (xem site trên thanh địa chỉ khi đăng nhập).
  2. Xóa `datadog/biz/deployed.json`, `datadog/ops/deployed.json` cũ (chứa id của tổ chức cũ).
  3. Work Management → New Project "ShipAudit" → Settings → Integrations → Datadog Monitors → bật, lấy handle `@case-...`,
     ghi vào `SHIPAUDIT_CASE_HANDLE` trong `.env`.
  4. Webhook `shipaudit-claims`: Integrations → Webhooks → New, theo mẫu `datadog/ops/webhook.json`
     (URL là tunnel của API + `/webhooks/datadog`, header `X-ShipAudit-Secret` = `WEBHOOK_SECRET` trong `.env`).
  5. `python datadog/ops/apply.py --notify @webhook-shipaudit-claims` và
     `python datadog/biz/apply.py --notify @webhook-shipaudit-claims`.
  6. Chạy `.\scripts\demo.ps1 -Tunnel` và kịch bản để có số liệu và monitor báo động.
- **Cấp quyền truy cập cho giám khảo (người dùng chốt 5/11):** được gửi API key, Application Key và thông tin kết nối Mongo cho giám khảo để họ tự vào xem và chạy lại.
  Gửi riêng qua kênh BTC chỉ định (email hoặc tin nhắn riêng), **không ghi giá trị khóa vào repo, README, docs hay video**.
  Nên dùng khóa/tài khoản lập riêng cho giám khảo (Mongo: người dùng `demo_readonly` chỉ đọc `shipaudit_demo`; Datadog: Application Key tạo bằng tài khoản Read Only nếu có), và xoay hoặc xóa toàn bộ sau khi chấm.
  Không gửi khóa/mật khẩu của người dùng `shipaudit` (quyền ghi mọi database) hay khóa đã lộ trong chat.

## 4. Đưa vào bài nộp

- Link giao diện demo (Community Cloud), link video, ảnh chụp Datadog.
- Repo và tài khoản giám khảo được cấp quyền; README có phần chạy lại (có Docker và không Docker).
- Mô tả sự cố trình diễn (mục 5) và khai báo dữ liệu tổng hợp, công cụ AI (`docs/ai-usage-log.md`, `docs/reuse-and-data.md`).

## 5. Chạy demo trên máy để quay video (bộ chat_v1)

```powershell
.\scripts\demo.ps1 -Tunnel        # metric, API, giao diện, 2 tunnel; database shipaudit_b_chat_v1, giờ mô phỏng 23/10 08:00
```

Cập nhật URL webhook `shipaudit-claims` trên Datadog theo địa chỉ tunnel API mới. Kịch bản video gợi ý:

1. Dashboard Datadog: Carrier C còn 18 giờ tới hạn khiếu nại, monitor "Sắp hết hạn khiếu nại" báo động.
2. Datadog gọi webhook, claim nháp xuất hiện trên trang Claims (log webhook và vạch sự kiện "Tạo claim nháp" trên Datadog).
3. Mở notebook điều tra: loại chênh lệch, bảng kê, log theo `alert_id`.
4. Trên giao diện: Chi tiết đơn (vì sao lệch theo quy tắc hãng), duyệt hàng loạt, ghi nhận đã gửi hãng.
5. Ghi nhận hãng hoàn tiền: thẻ "Đã thu hồi" ở Tổng quan, nhóm "Kết quả khiếu nại" trên dashboard, monitor về OK.

Kịch bản Carrier B có sẵn (`python -m scenarios.biz.run --db shipaudit_scenario --reset --webhook real ...`) cũng dùng được;
xem README.
