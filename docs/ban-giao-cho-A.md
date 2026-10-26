# Bàn giao cho A: ghép code, chạy Docker, kiểm thử đầu cuối

Ngày lập: 26/10/2026. Người giao: B. Người nhận: A.
Hạn: ghép + Docker xong **28/10**, đóng băng code **29/10**, nộp **30/10** (hạn cứng 31/10 23:59).

Không có khóa, mật khẩu hay chuỗi kết nối nào trong file này. Xem mục 6 để biết cách nhận.

## 1. Tình hình hiện tại

- **Phần B (B1–B10) xong code**, nằm trong repo chính, nhánh `b/m1-rules-and-data`. Trước khi bàn giao B sẽ commit và push nhánh này (xem mục 2, bước 0).
- **Phần A (A2–A10) đã được B viết thay** khi A bận, nằm ở 3 nhánh `a/m1-ingest-skeleton`, `a/m2-api-telemetry`, `a/m3-datadog-ops-webhook` (15 commit, chưa push). Bản Docker (A1) còn lại một ít thay đổi chưa commit ở worktree `../shipaudit-a`.
- Đã thử ghép trong một thư mục nháp: parser và luồng nạp của A cùng engine của B xử lý 24 bảng kê của bộ dữ liệu demo `chat_v1`, đối soát **khớp đáp án `labels.json` 5.281/5.281 dòng**. Chưa merge thật, chưa chạy Docker.
- Test: 169 test qua khi có kết nối Atlas (B: 143 qua + 26 chạy trên Atlas; A có 84 test riêng).
- Dữ liệu demo chính: bộ `generator/out/chat_v1/` (100% tổng hợp, Carrier A/B/C giả). Nạp bằng `make seed-chat` (tương đương `python -m generator.chat_v1 --db <tên> --reset`).

A hãy xem lại nhánh của mình: nhiều việc A2–A10 do B viết, A duyệt hoặc sửa theo ý mình.

## 2. Việc của A, theo thứ tự

### Bước 0 (B làm trước, A chờ báo)
B commit phần B, tách thay đổi `contracts/` (phiên bản làm việc 0.3.0) sang nhánh `contract/...`, push các nhánh. A chỉ bắt đầu bước 1 khi B báo đã push.

### Bước 1. Duyệt contract 0.3.0
Nhánh `contract/...` đổi `contracts/` từ 0.1.0 lên 0.3.0. Xem các thay đổi:

| Thay đổi | Ghi chú |
|---|---|
| `carrier_rules.claim_deadline_anchor` | trường tùy chọn, mặc định `statement_received_at` |
| `carrier_rules.payout_basis` | `delivered_plus_days` hoặc `period_end` |
| mô tả phụ phí | `flat_by_region`, `round_unit`, `round_mode` |
| `orders` thêm trường tùy chọn | |
| `statement_lines.paid_at` | |

Nếu đồng ý: merge nhánh contract vào `main` trước. Nếu không đồng ý điểm nào: ghi vào `docs/decisions.md` và nói với B.

### Bước 2. Ghép code (merge)
Thứ tự gợi ý: `contract/...` → nhánh A (`a/m1` → `a/m2` → `a/m3`) → nhánh B. Mỗi nhánh một PR nhỏ, người kia duyệt, không commit thẳng vào `main`.

Chỗ cần chú ý khi ghép:
1. **`Makefile`**: bản B có thêm `seed-chat`; cả hai bên đều có `scenario-biz`, `scenario-ops`. Gộp lại và đổi `scenario-biz` thành `python -m scenarios.biz.run --db shipaudit_demo --reset` (bắt buộc có `--reset`).
2. **`app/ingest/pipeline.py`**: bản trên `main` vẫn dùng stub; sau khi ghép phải gọi `core.reconcile.reconcile_statement` thật (đã thử và chạy được). Bỏ cờ `stub=true`.
3. **`scenarios/ops/run.py`** trên `main` chỉ có `raise NotImplementedError`; bản thật ở `a/m3`.
4. **Index `statement_lines`**: hai bên cùng dùng index unique tên `statement_order_unique`; `core.indexes.ensure_indexes` tự xóa index cũ `statement_order`.
5. **Docker**: `docker-compose.yml`, `app/Dockerfile`, `.dockerignore`, `README.md` ở `../shipaudit-a` còn sửa chưa commit; commit chúng trước khi ghép.
6. Chạy `pytest -q` trên mongomock rồi trên Atlas sau mỗi lần merge.

### Bước 3. Chạy Docker thật (A1)
1. Bật Docker Desktop. `cp .env.example .env`, điền `MONGO_URI`, `MONGO_DB`, `DD_API_KEY`, `DD_SITE=uk1.datadoghq.com`.
2. `docker compose up --build`. Services: `api` (8000), `worker`, `metrics-job`, `ui` (8501), `datadog-agent`.
3. Kiểm:
   - `/health` trả 200 (ping Mongo); `ui` ở `http://localhost:8501`.
   - Agent nhận metric/log/trace: tìm service `shipaudit-api` trong APM, log có `dd.trace_id` (liên kết log-trace chưa từng thử vì chưa có Agent).
   - Lưu ý `DD_TRACE_PYMONGO_ENABLED=false` do ddtrace 4.16 lỗi với pymongo 4.19; thử cặp phiên bản khác nếu muốn trace Mongo.
4. Nếu build lỗi: sửa trong nhánh A, ghi vào `docs/decisions.md`.

### Bước 4. Database demo chung và kịch bản hai lớp (I3, I4)
1. Chọn tên database demo chung (ví dụ `shipaudit_demo`), nạp: `python -m generator.chat_v1 --db shipaudit_demo --reset`.
2. Trong `.env`: `MONGO_DB=shipaudit_demo`.
3. Chạy kịch bản từ trạng thái sạch:
   - Lớp vận hành: `python -m scenarios.ops.run --api http://127.0.0.1:8000`. Kỳ vọng: 4 monitor vận hành (72794–72797) kích hoạt ở pha sự cố, về OK ở pha khắc phục.
   - Lớp nghiệp vụ: `python -m scenarios.biz.run --db shipaudit_demo --reset`. **Lưu ý**: kịch bản này hiện dùng dữ liệu `generator.seed` (sự cố Carrier B, 80 đơn thiếu 150.000đ), chưa chuyển sang `chat_v1` (sự cố Carrier C, kỳ W42). B sẽ quyết định có đổi hay không và báo A.
4. Kiểm Datadog uk1: dashboard `3ti-98m-p8s` (nghiệp vụ) và `yh5-e7m-dd2` (vận hành); monitor nghiệp vụ 72687, 72690, 72691.

### Bước 5. Webhook Datadog gọi thật (A9)
Datadog không gọi được `localhost`. Dựng tunnel (ví dụ cloudflared hoặc ngrok) tới cổng 8000, đặt URL công khai vào cấu hình webhook `datadog/ops/webhook.json`, giữ header `X-ShipAudit-Secret` khớp `WEBHOOK_SECRET`. Kiểm: monitor Alert → claim nháp xuất hiện, gọi lại cùng `alert_id` không tạo thêm. Nếu không kịp, giữ cách giả lập bằng `create_drafts_for_carrier` và ghi rõ trong README.

## 3. Tiêu chí hoàn thành

- [ ] `contract/...` merge, `contracts/VERSION` = 0.3.0.
- [ ] Nhánh A và nhánh B đã merge vào `main`, `pytest -q` qua hết (kể cả test Atlas).
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

## 6. Khóa và quyền truy cập

- **Datadog**: B mời A vào tổ chức `uk1.datadoghq.com`; A tự tạo API key của mình (và Application key nếu cần chạy `datadog/*/apply.py`). Không gửi khóa của B qua chat hay email.
- **Atlas**: B thêm IP của A vào Network Access và gửi thông tin đăng nhập qua trình quản lý mật khẩu. A dùng database riêng khi phát triển (không dùng `shipaudit_b_dev`).
- Sau khi nộp: đặt lại mật khẩu người dùng Atlas `shipaudit` (mật khẩu từng xuất hiện trong khung chat) và xóa key không dùng.
