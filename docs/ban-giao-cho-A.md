# Bàn giao cho A: ghép code, chạy Docker, kiểm thử đầu cuối

Ngày lập: 26/10/2026. Người giao: B. Người nhận: A.
Hạn: ghép + Docker xong **28/10**, đóng băng code **29/10**, nộp **30/10** (hạn cứng 31/10 23:59).

Không có khóa, mật khẩu hay chuỗi kết nối nào trong file này. Xem mục 6 để biết cách nhận.

## 1. Tình hình hiện tại

- **Phần B (B1–B10) xong code**, đã commit local trên nhánh `b/m1-rules-and-data` (4 commit) và nhánh `contract/payout-basis-optional-fields` (1 commit, contract 0.3.0). Chưa push.
- **Phần A (A2–A10) đã được B viết thay** khi A bận, ở nhánh `a/m3-datadog-ops-webhook` (đã chứa `a/m1`, `a/m2`; 16 commit gồm bản sửa Docker A1). Chưa push.
- **Đã ghép sẵn (26/10)** ở nhánh `integration/ab-merge` = nhánh B + nhánh A, không xung đột, kèm các sửa ở mục 2 bước 2. Test trên nhánh này: 220 qua, 28 bỏ qua (đều là test cần Atlas, vì lúc chạy Atlas không kết nối được).
- Trước đó đã thử ghép đầu cuối: parser và luồng nạp của A cùng engine của B xử lý 24 bảng kê `chat_v1`, đối soát **khớp đáp án `labels.json` 5.281/5.281 dòng**. Chưa chạy Docker.
- Dữ liệu demo chính: bộ `generator/out/chat_v1/` (100% tổng hợp, Carrier A/B/C giả). Nạp bằng `make seed-chat` (tương đương `python -m generator.chat_v1 --db <tên> --reset`).

A hãy xem lại nhánh của mình: nhiều việc A2–A10 do B viết, A duyệt hoặc sửa theo ý mình.

## 2. Việc của A, theo thứ tự

### Bước 0 (B làm trước, A chờ báo)
Đã commit local (xem mục 1). B còn phải **push** bốn nhánh: `contract/payout-basis-optional-fields`, `b/m1-rules-and-data`, `a/m3-datadog-ops-webhook` (kèm `a/m1`, `a/m2`) và `integration/ab-merge`, rồi báo A. A bắt đầu bước 1 khi B báo đã push.

### Bước 1. Duyệt contract 0.3.0
Nhánh `contract/payout-basis-optional-fields` đổi `contracts/` từ 0.1.0 lên 0.3.0. Xem các thay đổi:

| Thay đổi | Ghi chú |
|---|---|
| `carrier_rules.claim_deadline_anchor` | trường tùy chọn, mặc định `statement_received_at` |
| `carrier_rules.payout_basis` | `delivered_plus_days` hoặc `period_end` |
| mô tả phụ phí | `flat_by_region`, `round_unit`, `round_mode` |
| `orders` thêm trường tùy chọn | |
| `statement_lines.paid_at` | |

Nếu đồng ý: merge nhánh contract vào `main` trước. Nếu không đồng ý điểm nào: ghi vào `docs/decisions.md` và nói với B.

### Bước 2. Ghép code (B đã làm sẵn, A xem lại và mở PR)
Nhánh `integration/ab-merge` đã gộp nhánh B và nhánh A. Thứ tự mở PR vào `main`: `contract/...` trước, rồi `integration/ab-merge` (hoặc tách `a/m3` và `b/m1` thành hai PR nhỏ nếu muốn duyệt riêng). Không commit thẳng vào `main`.

Sáu chỗ dễ vướng, tình trạng sau khi ghép:
1. **`Makefile`**: xong. `make scenario-biz` chạy `--db $(SCENARIO_DB) --reset` (mặc định `shipaudit_scenario`); `make seed-chat` nạp vào `$(DEMO_DB)` (mặc định `shipaudit_demo`). Hai database tách nhau vì kịch bản nghiệp vụ **xóa và seed lại** database của nó, nên không được trỏ vào database demo.
2. **`app/ingest/pipeline.py`**: xong. Bỏ đường dự phòng stub, luôn gọi `core.reconcile.reconcile_statement` thật; bỏ cờ `stub` khỏi kết quả nạp và API (`app/api/models.py`). Webhook `app/api/webhooks.py` cũng bỏ `StubClaimService`, dùng `core.claims.ClaimService`. Test nạp dùng hàm đối soát giả khai báo trong test, các test khác chạy đối soát thật.
3. **`scenarios/ops/run.py`**: xong, bản thật của `a/m3` đã vào nhánh ghép.
4. **Index `statement_lines`**: hai bên cùng khai báo index unique tên `statement_order_unique`, `ensure_indexes` tự xóa `statement_order` cũ. **Lưu ý**: trên mongomock, nếu `ensure_storage` (A) chạy trước `ensure_indexes` (B) thì báo "already exists with different options". Thứ tự ngược lại và gọi lặp lại đều ổn. Nghi là đặc điểm của mongomock (cùng đặc tả, tên và unique) nhưng **chưa kiểm được trên MongoDB thật** vì Atlas đang không kết nối. A kiểm trên Atlas khi chạy bước 3; nếu lỗi thật thì để một bên gọi hàm của bên kia.
5. **Docker**: xong. Các sửa A1 đã commit ở `a/m3` (commit `715f48b`).
6. **Test**: chạy trên mongomock, 220 qua. Test cần Atlas (28) chưa chạy lại, A chạy khi Atlas sẵn sàng.

### Bước 3. Chạy Docker thật (A1)
1. Bật Docker Desktop. `cp .env.example .env`, điền `MONGO_URI`, `MONGO_DB`, `DD_API_KEY`, `DD_SITE=uk1.datadoghq.com`.
2. `docker compose up --build`. Services: `api` (8000), `worker`, `metrics-job`, `ui` (8501), `datadog-agent`.
3. Kiểm:
   - `/health` trả 200 (ping Mongo); `ui` ở `http://localhost:8501`.
   - Agent nhận metric/log/trace: tìm service `shipaudit-api` trong APM, log có `dd.trace_id` (liên kết log-trace chưa từng thử vì chưa có Agent).
   - Lưu ý `DD_TRACE_PYMONGO_ENABLED=false` do ddtrace 4.16 lỗi với pymongo 4.19; thử cặp phiên bản khác nếu muốn trace Mongo.
4. Nếu build lỗi: sửa trong nhánh A, ghi vào `docs/decisions.md`.

### Bước 4. Database demo chung và kịch bản hai lớp (I3, I4)
1. Nạp database demo chung: `make seed-chat` (mặc định `shipaudit_demo`, đổi bằng `DEMO_DB=<tên> make seed-chat`).
2. Trong `.env`: `MONGO_DB=shipaudit_demo`.
3. Chạy kịch bản từ trạng thái sạch:
   - Lớp vận hành: `python -m scenarios.ops.run --api http://127.0.0.1:8000`. Kỳ vọng: 4 monitor vận hành (72794–72797) kích hoạt ở pha sự cố, về OK ở pha khắc phục.
   - Lớp nghiệp vụ: `make scenario-biz` (xóa và seed lại database riêng `shipaudit_scenario`, **không** đụng database demo). **Lưu ý**: kịch bản này hiện dùng dữ liệu `generator.seed` (sự cố Carrier B, 80 đơn thiếu 150.000đ), chưa chuyển sang `chat_v1` (sự cố Carrier C, kỳ W42). B sẽ quyết định có đổi hay không và báo A.
4. Kiểm Datadog uk1: dashboard `3ti-98m-p8s` (nghiệp vụ) và `yh5-e7m-dd2` (vận hành); monitor nghiệp vụ 72687, 72690, 72691.

### Bước 5. Webhook Datadog gọi thật (A9)
Datadog không gọi được `localhost`. Dựng tunnel (ví dụ cloudflared hoặc ngrok) tới cổng 8000, đặt URL công khai vào cấu hình webhook `datadog/ops/webhook.json`, giữ header `X-ShipAudit-Secret` khớp `WEBHOOK_SECRET`. Kiểm: monitor Alert → claim nháp xuất hiện, gọi lại cùng `alert_id` không tạo thêm. Nếu không kịp, giữ cách giả lập bằng `create_drafts_for_carrier` và ghi rõ trong README.

## 3. Tiêu chí hoàn thành

- [ ] `contract/payout-basis-optional-fields` merge, `contracts/VERSION` = 0.3.0.
- [ ] `integration/ab-merge` (hoặc hai nhánh A, B) merge vào `main`, `pytest -q` qua hết (kể cả 28 test Atlas).
- [ ] `docker compose up --build` chạy sạch từ máy mới, mọi service healthy.
- [ ] Nạp 24 bảng kê chat_v1 qua API, đối soát khớp `labels.json`.
- [ ] Hai kịch bản chạy từ trạng thái sạch ra đúng kết quả mô tả, hai bên đều thấy trên Datadog.
- [ ] README có phần chạy (cả Docker và không Docker) và cách xem Datadog cho giám khảo (xem `docs/context/01-brief-hackathon-mugvn-2026.md`).

## 4. Không làm / lưu ý

- Không đổi công thức đối soát hay quy tắc 3 hãng; tham số hãng là dữ liệu trong `carrier_rules`.
- `core/` không import từ `app/`.
- Không commit `.env`, khóa Datadog, chuỗi kết nối Atlas.
- Nếu đổi `contracts/` thì làm trên nhánh `contract/<mô tả>`, tăng `contracts/VERSION`, báo B.
- Mỗi quyết định mới ghi một dòng vào `docs/decisions.md`.

## 5. Việc B vẫn giữ

Kịch bản nghiệp vụ (B10) và việc chuyển sang chat_v1, hồ sơ nộp (slide, video, mô tả giải pháp), cập nhật tiến độ trong `docs/word/src/theo-doi-tien-do.md`.

## 6. Cập nhật 30/10/2026: B sửa trong phần của A (A xem lại)

Hạn nộp gia hạn đến 8/11. B chạy thật Datadog và Atlas không dùng Docker và sửa mấy chỗ trong `app/`:

- `app/main.py`: nạp `.env` (`from common import config`) trước `setup_logging()`. Trước đó chạy trên máy không Docker thì `DD_LOGS_AGENTLESS=true` không có tác dụng (chưa có `DD_API_KEY` lúc bật log). Đã kiểm: log webhook lên Datadog.
- `app/api/webhooks.py`: đọc `SHIPAUDIT_NOW` (để demo ở giờ mô phỏng, cùng cách `ui/shared.py`), phát sự kiện Datadog "tạo claim nháp" chỉ cho claim mới tạo ở lần gọi đó, log thêm `amount`. Test: `test_follows_shipaudit_now`, `test_events_only_for_claims_created_by_this_call`.
- `.env.example`: thêm `SHIPAUDIT_DD_EVENTS`, `SHIPAUDIT_CASE_HANDLE`.
- Webhook `shipaudit-claims` đã tạo trên Datadog bằng API, URL là tunnel Cloudflare tạm thời (đổi mỗi lần mở lại tunnel). Đã kiểm bằng Test Notifications và bằng kịch bản `--webhook real`: Datadog gọi thật, tạo 181 claim nháp, gọi lại không tạo thêm. Bước 5 ở trên coi như xong phần kiểm thử; còn lại là địa chỉ công khai cố định nếu muốn.

## 7. Khóa và quyền truy cập

- **Datadog**: B mời A vào tổ chức `uk1.datadoghq.com`; A tự tạo API key của mình (và Application key nếu cần chạy `datadog/*/apply.py`). Không gửi khóa của B qua chat hay email.
- **Atlas**: B thêm IP của A vào Network Access và gửi thông tin đăng nhập qua trình quản lý mật khẩu. A dùng database riêng khi phát triển (không dùng `shipaudit_b_dev`).
- Sau khi nộp: đặt lại mật khẩu người dùng Atlas `shipaudit` (mật khẩu từng xuất hiện trong khung chat) và xóa key không dùng.

## 8. Cập nhật 09/11/2026: Datadog chuyển sang tổ chức mới (A xem lại)

- **Site đổi:** tổ chức uk1 hết thời gian dùng thử. Đội dựng lại Datadog nghiệp vụ trên tổ chức mới, site `datadoghq.com` (US1). `.env.example` đã đổi `DD_SITE=datadoghq.com`. Trong `.env` của A cần đặt cùng giá trị, kèm khóa API và Application Key của tổ chức mới (không đưa vào repo).
- **ID đối tượng đổi:** xem `datadog/biz/deployed.json` (monitor, SLO, notebook, dashboard `wbi-fix-kq8`).
- **Chưa có webhook `shipaudit-claims`** trên tổ chức mới, nên các monitor chưa gọi API claim. Muốn gắn lại: mở tunnel hoặc dùng địa chỉ API công khai, tạo webhook `shipaudit-claims` (Integrations → Webhooks) trỏ tới `/webhooks/...` của API (xem `datadog/ops/README.md`), rồi chạy `python datadog/biz/apply.py --notify @webhook-shipaudit-claims`.
- **Chưa có Case Management** (`@case-shipaudit`) ở tổ chức mới. Tạo project rồi chạy `apply.py --case-handle @case-<handle>`.
- Monitor và dashboard vận hành trong `datadog/ops/` chưa được dựng lại trên tổ chức mới. A chạy `python datadog/ops/apply.py` nếu cần.
