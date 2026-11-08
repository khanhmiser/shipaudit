> Bản Markdown của `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx` (cập nhật 16/10/2026). Bảng "Tình trạng hiện tại" ghi mốc 15/10 và đã cũ; xem `06-viec-con-mo-va-canh-bao.md`. Bảng theo dõi tiến độ ở mục 10 chưa được cập nhật.

**ShipAudit**

Kế hoạch kỹ thuật và phân công A / B

MUGVN Hackathon 2026 · Real-time Operations (MongoDB × Datadog) · cập nhật 16/10/2026

**Vai trò:** A = vận hành / platform (tên: \_\_\_\_\_\_\_\_\_\_\_\_). B = nghiệp vụ / data (Quốc Khánh Hoàng).

**Cách dùng file**

- **Mục 1:** nắm tình trạng hiện tại.

- **Mục 3 đến 6:** biết mình làm gì và ghép với nhau ở đâu.

- **Mục 7:** dựng cấu trúc thư mục repo.

- **Mục 10:** bảng theo dõi tiến độ, mỗi tối cập nhật cột Trạng thái và Ghi chú.

- **Màu:** xanh dương là phần của A, xanh lá là phần của B.

- **Phạm vi:** file này chỉ gồm phần kỹ thuật và code.

1\. Tình trạng hiện tại

| **Hạng mục**            | **Tình trạng (15/10/2026)**                                                                                                                                                        |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Hồ sơ dự án**         | Đã chốt các phần Bối cảnh, Vấn đề, Bài toán, Mục tiêu, Giải pháp (tổng thể + kỹ thuật) trong file Docs "ShipAudit - Hồ sơ dự án".                                                  |
| **Phân việc A / B**     | Đã chốt (mục 3-6).                                                                                                                                                                 |
| **Cấu trúc thư mục**    | Đã chốt (mục 7).                                                                                                                                                                   |
| **Code**                | Chưa bắt đầu. Giai đoạn build chính thức từ 17/10.                                                                                                                                 |
| **Dữ liệu**             | Hướng đi: dùng Olist làm nền đơn hàng, tự sinh phần hãng, bảng kê và chênh lệch (mục 8). Chưa tải về.                                                                              |
| **Cần làm trước 17/10** | \(1\) Chọn người đăng ký Datadog trial bằng email công việc (đề bắt buộc), mời người kia vào cùng org. (2) B gửi bộ contracts/ cho A trong ngày 16/10. (3) Tạo repo và CODEOWNERS. |

2\. Nguyên tắc chia việc

- **A sở hữu "đường ống và quan sát":** đưa dữ liệu vào, chạy ổn định, quan sát được, phản ứng tự động.

- **B sở hữu "đúng sai của con số":** dữ liệu, quy tắc, tính toán, truy vấn, giao diện.

- Mỗi người sở hữu trọn một lớp của kịch bản sự cố: A lớp vận hành (nạp dữ liệu chậm/lỗi), B lớp nghiệp vụ (chênh lệch, hạn khiếu nại). Không chia kiểu "backend / frontend" để tránh chờ nhau.

- Hai bên chỉ chạm nhau qua 5 điểm tiếp xúc ở mục 5. Mọi thứ khác nằm gọn trong thư mục của mỗi người.

3\. Việc của A (vận hành / platform)

| **Mã**  | **Việc**              | **Làm như thế nào**                                                                                                                                     | **Xong khi**                                   |
|---------|-----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------|
| **A1**  | Hạ tầng               | docker-compose gồm api, ui, datadog-agent. Có .env.example, kết nối Atlas, healthcheck.                                                                 | "docker compose up" chạy sạch trên máy của B.  |
| **A2**  | API                   | FastAPI: POST /statements (file CSV + mã hãng), GET /reconciliations, GET /health. Model pydantic theo contracts/.                                      | Gọi được bằng curl.                            |
| **A3**  | Parser                | 3 định dạng bảng kê chuẩn hóa thành statement_lines. Dòng hỏng ghi log, không làm sập cả file.                                                          | Đọc đúng 3 file mẫu trong contracts/samples.   |
| **A4**  | Luồng nạp             | Lưu file, parse, ghi statement_lines, gọi reconcile_statement, ghi ingest_events (Time Series: carrier, rows, duration_ms, status, lag_seconds) có TTL. | Một lần nạp tạo đủ dữ liệu ở 3 collection.     |
| **A5**  | Change Streams        | Worker nghe reconciliations: diff khác 0 thì ghi log JSON (kèm trace_id, carrier, order_code, diff) và đếm metric.                                      | Thêm một chênh lệch thì thấy log ngay.         |
| **A6**  | Telemetry             | Log JSON, ddtrace cho FastAPI và PyMongo, helper telemetry.metric(name, value, tags) có fallback in ra console khi chưa có Agent.                       | B gọi helper được ngay cả khi chưa có Datadog. |
| **A7**  | Công tắc lỗi          | Endpoint admin bật độ trễ (delay_ms) hoặc tỉ lệ lỗi (fail_rate) cho luồng nạp.                                                                          | Bật là thấy ingest_lag_seconds tăng.           |
| **A8**  | Datadog vận hành      | Dashboard ops, monitor (độ trễ nạp, tỉ lệ lỗi, latency p95), Log Management, liên kết log-trace. Xuất JSON vào datadog/ops/.                            | Monitor kích hoạt thật khi bật công tắc lỗi.   |
| **A9**  | Webhook               | POST /webhooks/datadog: kiểm tra secret, đọc payload, gọi claims.create_draft, idempotent theo alert id.                                                | Gửi cùng một alert hai lần chỉ ra một claim.   |
| **A10** | Kịch bản + smoke test | Script lớp vận hành, smoke test, README phần chạy và triển khai.                                                                                        | Chạy từ máy sạch ra được kết quả.              |

4\. Việc của B (nghiệp vụ / data)

| **Mã**  | **Việc**           | **Làm như thế nào**                                                                                                                                                       | **Xong khi**                                    |
|---------|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------|
| **B1**  | Dữ liệu nền        | Generator hai chế độ --source olist và --source synthetic, seed cố định, cùng một đầu ra. Lấy mẫu 5-20 nghìn đơn Olist, đổi VNĐ bằng hệ số cố định, gán COD ngẫu nhiên.   | Chạy lại ra đúng cùng dữ liệu.                  |
| **B2**  | Quy tắc hãng       | Đặc tả Carrier A/B/C vào carrier_rules (là dữ liệu, không hard-code): khối lượng quy đổi, cước theo vùng, phụ phí, lịch COD, hạn khiếu nại.                               | Đổi tham số hãng mà không sửa code.             |
| **B3**  | Engine             | compute_expected(order, line, rule) trả về Breakdown theo đúng công thức đối soát, liệt kê từng khoản cộng/trừ. Dùng số nguyên VNĐ hoặc Decimal, không dùng float.        | Golden test khớp từng đồng.                     |
| **B4**  | Đối soát           | reconcile_statement: ghép dòng bảng kê với đơn, tính diff, phân loại diff_type, tính claim_deadline_at, ghi reconciliations. Idempotent theo (statement_id, order_code).  | Nạp lại cùng bảng kê không sinh bản ghi trùng.  |
| **B5**  | Chênh lệch cài sẵn | Generator cài 5 loại chênh lệch (cước lệch, phí hoàn trừ hai lần, thiếu đơn, thu hộ lệch, chuyển chậm) cộng ca hoàn/trả/hàng lỗi. Xuất 3 file bảng kê thô và labels.json. | Có đáp án để đối chiếu.                         |
| **B6**  | MongoDB            | Aggregation Pipeline (\$lookup, \$facet, \$setWindowFields), index, chụp explain().                                                                                       | Mỗi pipeline có test trên dữ liệu seed.         |
| **B7**  | Claims             | create_draft, approve, trạng thái claim.                                                                                                                                  | Webhook của A gọi được.                         |
| **B8**  | Streamlit          | Đọc Mongo qua core.queries (không qua API của A): bảng chênh lệch, breakdown từng đơn, đếm ngược hạn, so sánh hãng, danh sách claim.                                      | Chạy độc lập khi A chưa xong.                   |
| **B9**  | Datadog nghiệp vụ  | Job định kỳ phát shipaudit.biz.\*, dashboard biz, monitor (chênh lệch vượt ngưỡng, sắp hết hạn), Anomaly Detection. Xuất JSON vào datadog/biz/.                           | Monitor kích hoạt thật bằng kịch bản nghiệp vụ. |
| **B10** | Kịch bản + test    | Seed và script lớp nghiệp vụ, golden test, test đối chiếu labels.json (phát hiện đủ 100% chênh lệch đã cài), test pipeline.                                               | Test xanh.                                      |

5\. Năm điểm tiếp xúc (khóa trong contracts/)

| **\#** | **Điểm tiếp xúc**                                                      | **Cung cấp → dùng** | **Stub trong lúc chờ**    |
|--------|------------------------------------------------------------------------|---------------------|---------------------------|
| **1**  | 3 file bảng kê mẫu + schema statement_lines                            | B → A               | A dùng file mẫu.          |
| **2**  | reconcile_statement(statement_id, db)                                  | B → A               | Stub trả kết quả cố định. |
| **3**  | claims.create_draft(reconciliation_id, source)                         | B → A               | Stub ghi log.             |
| **4**  | telemetry.metric(name, value, tags)                                    | A → B               | Fallback in ra console.   |
| **5**  | Enum dùng chung: diff_type, claim.status, tên tag (carrier, diff_type) | Cùng viết           | Không cần.                |

**Tên metric tách namespace:** A dùng shipaudit.ops.\* (ingest_lag_seconds, statement_rows, ingest_errors). B dùng shipaudit.biz.\* (diff_amount, diff_count, claim_hours_left).

6\. Quy tắc phối hợp và các lần ghép

- **Git:** main luôn chạy được. Mỗi người một nhánh theo mốc ghép, PR nhỏ, người kia duyệt trong vòng 12 giờ. Chi tiết ở mục Quy ước nhánh Git bên dưới.

- **Đổi contract:** sửa contracts/ qua nhánh contract/ riêng, cả hai cùng duyệt, tăng số trong contracts/VERSION, báo người kia ngay. Không đổi âm thầm.

- **Họp tối 15 phút:** hôm nay xong gì, đang chặn gì, mai làm gì.

- **Khi bị chặn:** dùng stub và làm tiếp phần mình. Chỉ hẹn nhau khi cần ghép thật.

- **Nhật ký:** mỗi người ghi công cụ AI đã dùng và thành phần tái sử dụng vào docs/ ngay khi dùng, để cuối kỳ khai báo không phải nhớ lại.

Bốn lần ghép

| **Lần** | **Ngày**  | **Việc**                                                                    |
|---------|-----------|-----------------------------------------------------------------------------|
| **I1**  | Tối 18/10 | Lát cắt mỏng: nạp 1 bảng kê của 1 hãng, thấy chênh lệch trên UI.            |
| **I2**  | 21/10     | Engine thật thay stub, chạy cả 3 hãng.                                      |
| **I3**  | 24/10     | Metric ops và biz đều lên Datadog, bắt đầu dựng dashboard.                  |
| **I4**  | 27/10     | Chạy kịch bản hai lớp từ trạng thái sạch (docker compose up, seed, script). |

Quy ước nhánh Git

Cả dự án có một nhánh cố định (main) và ba nhánh làm việc chạy song song. Mỗi mốc ghép mỗi người mở một nhánh mới, merge xong thì xóa. Vì vậy không lúc nào có quá 3-4 nhánh sống cùng lúc.

| **Mốc** | **A (vận hành / platform)** | **B (nghiệp vụ / data)**   | **Hạn merge vào main** |
|---------|-----------------------------|----------------------------|------------------------|
| **I1**  | a/m1-ingest-skeleton        | b/m1-rules-and-data        | Tối 18/10              |
| **I2**  | a/m2-api-telemetry          | b/m2-engine-pipelines      | 21/10                  |
| **I3**  | a/m3-datadog-ops-webhook    | b/m3-streamlit-datadog-biz | 24/10                  |
| **I4**  | a/m4-incident-ops           | b/m4-incident-biz          | 27/10                  |

- **main:** nhánh duy nhất sống suốt dự án, luôn chạy được và demo được. Không commit thẳng, chỉ nhận PR. Không dùng nhánh develop vì thời gian build chỉ 2 tuần.

- **docs/submission:** nhánh chung cho README, sơ đồ kiến trúc, mô tả sự cố, nhật ký công cụ AI, khai báo thành phần tái sử dụng, kịch bản video. Mở sớm, cập nhật dần, không để dồn đến cuối.

- **contract/\<mô tả\>:** mọi thay đổi trong contracts/ đi qua nhánh riêng, ví dụ contract/v0.2-add-field-x. PR cần cả A và B đồng ý, tăng số trong contracts/VERSION, merge trước khi hai bên dùng trường mới. Không sửa contracts/ trong nhánh a/ hoặc b/.

- **Đặt tên:** a/\<mốc\>-\<việc\> cho A, b/\<mốc\>-\<việc\> cho B. Mỗi nhánh sống tối đa 2-3 ngày, PR nhỏ, người kia duyệt trong 12 giờ. Mỗi sáng kéo main về nhánh của mình (rebase hoặc merge) để không lệch quá một ngày.

- **Bảo vệ main:** trên GitHub vào Settings, Branches, Add rule cho main. Bật Require a pull request before merging và Require approvals (1 người). Người tạo PR không tự duyệt được PR của mình, nên A phải được mời vào repo và CODEOWNERS phải thay @A-GITHUB-USERNAME bằng tài khoản thật trước khi bật rule.

- **Mốc chốt:** 23/10 là checkpoint hết tính năng chính. 29/10 đóng băng code, chỉ nhận PR sửa lỗi. Gắn tag v1.0-submission ngay trước khi nộp (mục tiêu 30/10).

- **Bí mật:** không commit .env, khóa Datadog hay chuỗi kết nối Atlas. Chỉ commit .env.example. Lỡ commit thì phải xoay khóa, xóa khỏi lịch sử là chưa đủ.

**Lệnh mở nhánh đầu tiên (B):**

> git checkout main && git pull origin main
>
> git checkout -b b/m1-rules-and-data
>
> git push -u origin b/m1-rules-and-data
>
> git checkout -b docs/submission main
>
> git push -u origin docs/submission

Lịch build theo ngày

| **Ngày**     | **A (chạy trên stub của B)**                                                          | **B (không cần API của A)**                                                          |
|--------------|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| **16/10**    | Chọn người đăng ký Datadog trial. Tạo repo, Atlas, thử Time Series và Change Streams. | Đặc tả 3 hãng. Viết contracts/ và gửi A.                                             |
| **17-18/10** | Compose, API nạp, parser đọc 3 file mẫu, log JSON.                                    | Generator 1 hãng, compute_expected ca thường, seed thẳng vào Mongo.                  |
| **19-21/10** | Luồng nạp hoàn chỉnh, ingest_events, ddtrace, metric ops.                             | 3 hãng, hoàn/trả/hàng lỗi, 5 loại chênh lệch, golden test, reconcile_statement thật. |
| **22-23/10** | Change-stream worker, endpoint bật/tắt lỗi.                                           | Streamlit, job metric biz, claims. Checkpoint 23/10: hết tính năng chính.            |
| **24-26/10** | Dashboard + monitor vận hành, export JSON.                                            | Dashboard + monitor nghiệp vụ, Anomaly Detection, export JSON.                       |
| **27-28/10** | Webhook tạo claim nháp, script lớp vận hành.                                          | Seed kịch bản nghiệp vụ, script lớp nghiệp vụ.                                       |
| **29/10**    | Đóng băng code: chỉ sửa lỗi. README, kiểm tra cài từ máy sạch.                        | Test cuối, hoàn thiện nhật ký AI và khai báo dữ liệu.                                |
| **30/10**    | Nộp bài (31/10 chỉ để dự phòng).                                                      |                                                                                      |

7\. Cấu trúc thư mục

Nhãn (A), (B), (chung) cho biết ai sửa thư mục đó. Thư mục chung sửa qua PR và người kia duyệt.

> shipaudit/
>
> ├─ README.md, Makefile, pyproject.toml, .gitignore (chung)
>
> ├─ docker-compose.yml, .env.example (A)
>
> ├─ .github/CODEOWNERS (chung)
>
> │
>
> ├─ contracts/ (chung)
>
> │ ├─ VERSION \# tăng số mỗi lần đổi contract
>
> │ ├─ schemas/ \# 6 file .json: carrier_rules, orders, statement_lines,
>
> │ │ \# reconciliations, claims, ingest_events
>
> │ ├─ samples/ \# statement_carrier_a/b/c.csv (B viết, A dùng làm parser)
>
> │ └─ interfaces.py \# Protocol + stub: reconcile_statement, claims, metric
>
> │
>
> ├─ common/ (chung)
>
> │ ├─ config.py \# đọc .env
>
> │ ├─ db.py \# get_db(), tên collection
>
> │ └─ enums.py \# diff_type, claim_status, tên tag
>
> │
>
> ├─ app/ \# đường ống và quan sát (A)
>
> │ ├─ main.py \# khởi tạo FastAPI
>
> │ ├─ api/ \# statements, reconciliations, webhooks, admin, health
>
> │ ├─ ingest/
>
> │ │ ├─ parsers/ \# base.py, carrier_a.py, carrier_b.py, carrier_c.py
>
> │ │ └─ pipeline.py \# lưu file \> parse \> ghi \> reconcile \> ingest_events
>
> │ ├─ workers/change_stream.py \# nghe reconciliations, log + metric khi diff khác 0
>
> │ ├─ telemetry/ \# logging.py, metrics.py (fallback console), tracing.py
>
> │ └─ Dockerfile
>
> │
>
> ├─ core/ \# đúng sai của con số (B)
>
> │ │ \# KHÔNG import từ app/
>
> │ ├─ rules.py \# đọc carrier_rules thành đối tượng
>
> │ ├─ engine.py \# compute_expected() -\> Breakdown
>
> │ ├─ money.py \# tiền dạng số nguyên VNĐ / Decimal
>
> │ ├─ reconcile.py \# reconcile_statement(), idempotent
>
> │ ├─ claims.py \# create_draft, approve, trạng thái
>
> │ ├─ queries.py \# hàm đọc cho UI và job metric
>
> │ ├─ indexes.py \# tạo index
>
> │ └─ metrics_job.py \# job phát shipaudit.biz.\*
>
> │
>
> ├─ pipelines/ \# Aggregation Pipeline (B)
>
> │ ├─ diff_by_carrier.py \# \$group, \$facet
>
> │ ├─ missing_orders.py \# \$lookup
>
> │ ├─ diff_trend.py \# \$setWindowFields
>
> │ └─ claims_expiring.py
>
> │
>
> ├─ generator/ \# dữ liệu tổng hợp / công khai (B)
>
> │ ├─ seed.py \# --source olist \| synthetic
>
> │ ├─ olist_loader.py \# lấy mẫu, đổi VNĐ, gán COD
>
> │ ├─ synthetic.py \# 100% tổng hợp (phương án dự phòng)
>
> │ ├─ carriers/ \# tham số Carrier A/B/C
>
> │ ├─ inject.py \# cài 5 loại chênh lệch + hoàn/trả/hàng lỗi
>
> │ ├─ statements.py \# xuất 3 file bảng kê thô
>
> │ └─ out/ \# (gitignore) bảng kê + labels.json
>
> │
>
> ├─ ui/ \# Streamlit, đọc qua core.queries (B)
>
> │ ├─ app.py
>
> │ └─ pages/ \# Chenh_lech, Chi_tiet_don, Han_khieu_nai,
>
> │ \# So_sanh_hang, Claims
>
> │
>
> ├─ datadog/ops/ \# dashboard + monitors vận hành (A)
>
> ├─ datadog/biz/ \# dashboard + monitors nghiệp vụ (B)
>
> ├─ scenarios/ops/ \# kịch bản lớp vận hành (A)
>
> ├─ scenarios/biz/ \# kịch bản lớp nghiệp vụ (B)
>
> │
>
> ├─ tests/
>
> │ ├─ core/, pipelines/ \# golden test, đối chiếu labels.json (B)
>
> │ └─ ingest/, api/, smoke/ \# parser, API + webhook, chạy từ máy sạch (A)
>
> │
>
> ├─ data/raw/olist/ \# (gitignore) CSV tải từ Kaggle (B)
>
> └─ docs/ \# decisions.md, ai-usage-log.md, reuse-and-data.md (chung)

Quy tắc import (giữ cho hai bên độc lập)

- app/ gọi core chỉ qua hàm khai báo trong contracts/interfaces.py. core/ không bao giờ import từ app/.

- ui/ chỉ đọc qua core/queries.py, không đi qua API của A. Streamlit chạy được khi A chưa xong.

- core/metrics_job.py phát metric chỉ qua Protocol metric(). Khi chưa có Datadog thì rơi về console.

- Trong lúc chờ nhau: A dùng stub của reconcile_statement và claims.create_draft; B dùng fixture trong contracts/samples.

CODEOWNERS

> /app/ /datadog/ops/ /scenarios/ops/ @ban-A
>
> /tests/ingest/ /tests/api/ /tests/smoke/ @ban-A
>
> /docker-compose.yml /.env.example @ban-A
>
> /core/ /pipelines/ /generator/ /ui/ @ban-B
>
> /datadog/biz/ /scenarios/biz/ @ban-B
>
> /tests/core/ /tests/pipelines/ @ban-B
>
> /contracts/ /common/ /docs/ /README.md @ban-A @ban-B

8\. Dữ liệu (B phụ trách)

Không có dataset công khai nào chứa bảng kê đối soát hoặc quy tắc phí của hãng vận chuyển (đây là dữ liệu nội bộ). Hướng chốt: lấy dataset công khai làm nền đơn hàng, tự sinh phần hãng, bảng kê và chênh lệch.

| **ShipAudit cần**                               | **Lấy từ Olist (Kaggle)**                                  | **Phải tự sinh**                                         |
|-------------------------------------------------|------------------------------------------------------------|----------------------------------------------------------|
| **Đơn, mặt hàng, giá**                          | orders, order_items                                        | Không                                                    |
| **Khối lượng, kích thước (khối lượng quy đổi)** | products (cần kiểm tra cột khi tải)                        | Bù nếu thiếu                                             |
| **Vùng giao, mốc thời gian giao**               | Bang khách/người bán, geolocation, timestamp trong orders  | Bảng cước theo vùng                                      |
| **COD**                                         | Không có (chỉ có thẻ, boleto, voucher)                     | Gán ngẫu nhiên có seed, tiền thu hộ lấy từ payment_value |
| **Hoàn, trả hàng, hàng lỗi**                    | Trạng thái hủy/không giao, điểm đánh giá thấp làm ứng viên | Phần còn lại sinh theo xác suất                          |
| **Hãng, quy tắc phí, bảng kê, chênh lệch**      | Không có                                                   | Sinh hoàn toàn (Carrier A/B/C)                           |

- Lấy mẫu 5-20 nghìn đơn là đủ. Dữ liệu từ Brazil nên khai báo là dataset ngoài và đổi tiền sang VNĐ bằng một hệ số cố định.

- Giấy phép Olist chưa xác minh được. Đọc mục License trên trang Kaggle trước khi dùng và ghi vào docs/reuse-and-data.md.

- Dự phòng: generator có hai chế độ cùng một đầu ra. Nếu Olist lỗi thì chạy --source synthetic (100% tổng hợp), A không bị ảnh hưởng.

- Kết quả trên dữ liệu tổng hợp chỉ chứng minh tích hợp và khả năng chạy lại, không chứng minh số liệu thực tế.

9\. Rủi ro kỹ thuật

- **Trial Datadog chưa có:** A xử lý email công việc ngay. Code telemetry phải chạy được ở chế độ no-op/console để không bị chặn.

- **Monitor có độ trễ đánh giá vài phút:** đặt ngưỡng và cửa sổ thời gian ngắn cho môi trường demo, kịch bản phải chạy đủ lâu.

- **Quy tắc hãng đổi liên tục:** B khóa đặc tả 3 hãng trước 18/10; thay đổi sau đó đi qua carrier_rules (dữ liệu) chứ không sửa code.

- **Gói Atlas có thể không hỗ trợ đủ:** thử tạo thật Time Series và Change Streams ngay trong ngày 16/10.

- **Phạm vi phình ra:** mọi ý tưởng mới sau checkpoint 23/10 ghi vào danh sách "sau hackathon".

10\. Theo dõi tiến độ

**Trạng thái:** Chưa bắt đầu · Đang làm · Xong · Bị chặn. Cập nhật mỗi tối trước buổi họp. Mục Ghi chú ghi vướng mắc, link PR hoặc điều cần người kia làm.

Chuẩn bị chung

| **Mã** | **Việc**                                                          | **Hạn** | **Trạng thái** | **Ghi chú** |
|--------|-------------------------------------------------------------------|---------|----------------|-------------|
| **C1** | Chọn người đăng ký Datadog trial (email công việc), mời người kia | 16/10   | Chưa bắt đầu   |             |
| **C2** | Tạo repo + CODEOWNERS + khung thư mục                             | 16/10   | Chưa bắt đầu   |             |
| **C3** | Viết contracts/ (schema, 3 bảng kê mẫu, interfaces.py) và gửi A   | 16/10   | Chưa bắt đầu   |             |
| **C4** | Thử tạo Time Series + Change Streams trên gói Atlas đang dùng     | 16/10   | Chưa bắt đầu   |             |

A: vận hành / platform

| **Mã**  | **Việc**                              | **Hạn**                    | **Trạng thái** | **Ghi chú** |
|---------|---------------------------------------|----------------------------|----------------|-------------|
| **A1**  | Hạ tầng (compose, Atlas, healthcheck) | 17/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m1-ingest-skeleton |
| **A2**  | API FastAPI                           | 18/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m2-api-telemetry |
| **A3**  | Parser 3 định dạng bảng kê            | 18/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m1-ingest-skeleton |
| **A4**  | Luồng nạp + ingest_events             | 19/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m1-ingest-skeleton |
| **A5**  | Change Streams worker                 | 22/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m2-api-telemetry |
| **A6**  | Telemetry (log JSON, ddtrace, metric) | 18/10 (cơ bản), 24/10 (đủ) | Đang làm (cơ bản xong) | 22/10, B làm thay, nhánh a/m2-api-telemetry |
| **A7**  | Công tắc lỗi nạp                      | 22/10                      | Xong (chờ A duyệt) | 22/10, B làm thay, nhánh a/m2-api-telemetry |
| **A8**  | Datadog vận hành (dashboard, monitor) | 26/10                      | Chưa bắt đầu   |             |
| **A9**  | Webhook tạo claim nháp                | 27/10                      | Chưa bắt đầu   |             |
| **A10** | Kịch bản ops + smoke test + README    | 28/10                      | Chưa bắt đầu   |             |

B: nghiệp vụ / data

| **Mã**  | **Việc**                                                | **Hạn**                      | **Trạng thái** | **Ghi chú** |
|---------|---------------------------------------------------------|------------------------------|----------------|-------------|
| **B1**  | Dữ liệu nền (Olist + synthetic)                         | 17/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B2**  | Đặc tả quy tắc 3 hãng vào carrier_rules                 | 16/10 (đặc tả), 18/10 (khóa) | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B3**  | Engine compute_expected + golden test                   | 18/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B4**  | reconcile_statement (idempotent)                        | 21/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B5**  | Cài chênh lệch + labels.json                            | 21/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B6**  | Aggregation Pipeline + index + explain()                | 23/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B7**  | Claims (create_draft, approve)                          | 23/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B8**  | Streamlit                                               | 23/10                        | Đang làm (thiết kế lại giao diện, 1/3 màn) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B9**  | Datadog nghiệp vụ (metric, dashboard, monitor, Anomaly) | 26/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |
| **B10** | Kịch bản biz + test đối chiếu                           | 28/10                        | Xong (chờ duyệt) | 22/10, nhánh b/m1-rules-and-data, chưa commit |

Các lần ghép và mốc

| **Mã** | **Việc**                                             | **Hạn** | **Trạng thái** | **Ghi chú** |
|--------|------------------------------------------------------|---------|----------------|-------------|
| **I1** | Lát cắt mỏng: nạp 1 bảng kê, thấy chênh lệch trên UI | 18/10   | Chưa bắt đầu   |             |
| **I2** | Engine thật thay stub, chạy 3 hãng                   | 21/10   | Chưa bắt đầu   |             |
| **M1** | Checkpoint: hết tính năng chính                      | 23/10   | Chưa bắt đầu   |             |
| **I3** | Metric ops + biz lên Datadog                         | 24/10   | Chưa bắt đầu   |             |
| **I4** | Kịch bản hai lớp chạy từ trạng thái sạch             | 27/10   | Chưa bắt đầu   |             |
| **M2** | Đóng băng code                                       | 29/10   | Chưa bắt đầu   |             |
| **M3** | Nộp bài                                              | 30/10   | Chưa bắt đầu   |             |

Nhật ký cập nhật

| **Ngày** | **Người** | **Đã làm / thay đổi**                                 | **Đang chặn / cần người kia** |
|----------|-----------|-------------------------------------------------------|-------------------------------|
| 15/10    | B         | Chốt phân việc A/B và cấu trúc thư mục. Chưa có code. |                               |
|          |           |                                                       |                               |
|          |           |                                                       |                               |
|          |           |                                                       |                               |
|          |           |                                                       |                               |
|          |           |                                                       |                               |
