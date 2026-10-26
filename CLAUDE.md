# ShipAudit: hướng dẫn cho Claude Code

ShipAudit là hệ thống đối soát cước vận tải 3PL cho **doanh nghiệp bán hàng**: tính **số tiền phải nhận** của từng đơn theo quy tắc từng hãng, so với **số tiền thực nhận**, cảnh báo chênh lệch theo **hạn khiếu nại**. Dự án dự thi MUGVN Hackathon 2026, đề Real-time Operations (MongoDB × Datadog). Hạn nộp 23:59 31/10/2026; mục tiêu tự đặt là nộp 30/10, đóng băng code 29/10.

Trả lời người dùng bằng tiếng Việt.

## Người dùng là B

Người dùng là **B** (nghiệp vụ / data), nhóm 2 người. **A** (IT / platform) là bạn của người dùng, làm phần khác. Mặc định chỉ sửa phần của B:

- Thư mục của B: `core/`, `pipelines/`, `generator/`, `ui/`, `datadog/biz/`, `scenarios/biz/`, `tests/core/`, `tests/pipelines/`.
- Thư mục của A (không sửa nếu người dùng không yêu cầu): `app/`, `datadog/ops/`, `scenarios/ops/`, `tests/ingest/`, `tests/api/`, `tests/smoke/`, `docker-compose.yml`, `.env.example`.
- Thư mục chung (`contracts/`, `common/`, `docs/`, `README.md`): cả hai duyệt. **`contracts/` chỉ đổi qua nhánh `contract/<mô tả>`**, tăng `contracts/VERSION`, và nói rõ với người dùng để báo A.

## Đọc trước khi code

Đọc theo thứ tự, đọc đủ phần liên quan tới việc đang làm:

1. `docs/context/04-quyet-dinh-da-chot.md`: mọi quyết định đã chốt (đọc đầu tiên).
2. `docs/context/05-ke-hoach-ky-thuat-AB.md`: việc A1–A10, B1–B10, 5 điểm tiếp xúc, cấu trúc thư mục, dữ liệu, rủi ro.
3. `contracts/README.md`, `contracts/interfaces.py`, `contracts/schemas/*.json`, `contracts/samples/*.csv`, `common/enums.py`: hợp đồng giữa A và B.
4. `docs/context/02-boi-canh-van-de-bai-toan-muc-tieu.md` và `03-giai-phap-da-chot.md`: nghiệp vụ và thiết kế đã chốt.
5. `docs/context/01-brief-hackathon-mugvn-2026.md`: đề, yêu cầu bắt buộc, bài nộp, tiêu chí chấm 30/30/30/10, lịch.
6. `docs/context/06-viec-con-mo-va-canh-bao.md`: việc còn mở và chỗ tài liệu lệch nhau.

Các stub trong code có docstring nêu việc cần làm (`TODO(B)`). Docs "Hồ sơ dự án" trên claude.ai ở phần Giải pháp là bản cũ; khi mâu thuẫn thì theo `contracts/` và `docs/context/`.

## Công thức đối soát (bắt buộc)

Tiền đối soát = Tiền thu hộ + Shop trả trước (nếu có) + Shop trả phí khi trả hàng (nếu có) − Phí giao hàng − Phí bảo hiểm (nếu có) − Phí chuyển hoàn (nếu có) − Phí lưu kho (nếu có) − Phí thay đổi địa chỉ (nếu có) − Phí đồng kiểm (nếu có) + Khuyến mãi (nếu có) − Phí chuyển khoản.

Cài tại `contracts/interfaces.py` (`Breakdown.expected_amount`), có test ở `tests/core/test_breakdown_formula.py`. Phải phủ ca hoàn hàng, trả hàng, hàng lỗi. Chênh lệch = phải nhận − thực nhận. Năm loại: `FEE_MISMATCH`, `RETURN_FEE_DOUBLE`, `MISSING_IN_STATEMENT`, `COD_MISMATCH`, `LATE_PAYOUT`.

## Quy tắc code

- Tiền là số nguyên VNĐ hoặc `Decimal`, không dùng float (`core/money.py`).
- Quy tắc hãng là dữ liệu trong `carrier_rules`, không hard-code. Đổi tham số hãng không được phải sửa code.
- `core/` không import từ `app/`. `ui/` chỉ đọc Mongo qua `core/queries.py`, không gọi API của A. Chờ A thì dùng `stub_*` trong `contracts/interfaces.py`.
- `reconcile_statement` idempotent theo `(statement_id, order_code)`. `create_draft` idempotent theo `alert_id`.
- Dữ liệu chỉ tổng hợp hoặc công khai. Hãng trong demo là hãng giả Carrier A/B/C. Không dùng dữ liệu thật của công ty. Seed cố định để chạy lại ra đúng cùng dữ liệu. Sinh kèm `labels.json` làm đáp án kiểm thử.
- Metric của B: namespace `shipaudit.biz.*` (`diff_amount`, `diff_count`, `claim_hours_left`), phát qua `Metrics` trong `contracts/interfaces.py`, có fallback in ra console khi chưa có Datadog.
- Dashboard và monitor Datadog xuất JSON vào `datadog/biz/` để tái tạo được.
- Không dùng AI/LLM để tính tiền. Con người duyệt claim trước khi gửi hãng.
- Không commit `.env`, khóa Datadog, chuỗi kết nối Atlas.
- Mỗi pipeline và mỗi hàm tính tiền có test trên dữ liệu seed. Golden test khớp từng đồng.
- Python ≥ 3.11. Chạy: `make test`, `make seed`, `make scenario-biz`, `make up`.

## Git

- Không commit thẳng vào `main`. Nhánh của B theo mốc: `b/m1-rules-and-data`, `b/m2-engine-pipelines`, `b/m3-streamlit-datadog-biz`, `b/m4-incident-biz`. Nhánh chung `docs/submission`. Đổi contract: `contract/<mô tả>`.
- Nhánh sống tối đa 2–3 ngày, PR nhỏ, người kia duyệt. Chỉ commit hoặc push khi người dùng yêu cầu.

## Cách viết (tài liệu, giao diện, slide)

- Gọi khách hàng là "doanh nghiệp" (không gọi "shop"). Dùng đúng thuật ngữ: số tiền phải nhận, số tiền thực nhận, chênh lệch, hạn khiếu nại.
- Không quy kết hay xếp hạng độ "đáng tin" của hãng. Dùng "sai lệch", "chênh lệch", "thước đo chung", "so sánh các hãng".
- Không dùng số liệu thị trường. Con số minh họa phải ghi rõ là kịch bản giả định.
- File Word của dự án: phông Times New Roman, trình bày rõ ràng.

## Việc của B (chi tiết ở mục 4 của file kế hoạch)

B1 dữ liệu nền (Olist + synthetic, `generator/`) · B2 quy tắc 3 hãng (`generator/carriers/params.py`, `core/rules.py`) · B3 `compute_expected` (`core/engine.py`) · B4 `reconcile_statement` (`core/reconcile.py`) · B5 cài 5 loại chênh lệch + 3 file bảng kê + `labels.json` (`generator/inject.py`, `statements.py`) · B6 Aggregation Pipeline + index + `explain()` (`pipelines/`, `core/indexes.py`) · B7 claims (`core/claims.py`) · B8 Streamlit (`ui/`, `core/queries.py`) · B9 job metric + Datadog nghiệp vụ (`core/metrics_job.py`, `datadog/biz/`) · B10 kịch bản nghiệp vụ + test (`scenarios/biz/run.py`, `tests/`).

Thứ tự gợi ý khi thời gian gấp (làm lát cắt mỏng chạy được trước, mở rộng sau): tham số hãng và `core/rules.py`, rồi `core/engine.py` + golden test, rồi generator + `labels.json`, rồi `core/reconcile.py` + index, rồi pipelines, claims và queries, rồi Streamlit, rồi job metric + Datadog biz, cuối cùng kịch bản nghiệp vụ.

## Ghi nhớ quyết định (yêu cầu của người dùng)

Mỗi khi người dùng **chốt** hoặc **sửa** điều gì (thiết kế, tham số, cách viết, lịch, phân việc), ghi ngay một dòng vào `docs/decisions.md` theo mẫu: `ngày · người · quyết định · lý do ngắn`. Đầu mỗi phiên, đọc `docs/decisions.md` để biết những gì đã chốt sau lần cuối. Nếu thay đổi chạm `contracts/`, ghi thêm rằng cần báo A.

Ghi công cụ AI đã dùng vào `docs/ai-usage-log.md`, thư viện và dataset ngoài vào `docs/reuse-and-data.md` (đề bắt buộc khai báo).

## Bản Word

`docs/word/` có 5 file Word để xem nhanh (hồ sơ dự án, quyết định, kế hoạch A/B, theo dõi tiến độ, brief và checklist). Khi tiến độ hoặc quyết định đổi, sửa nguồn trong `docs/word/src/` (tiến độ: `theo-doi-tien-do.md`) rồi chạy `bash docs/word/build.sh`.

## Cập nhật tiến độ (yêu cầu của người dùng)

Mỗi khi xong hoặc đổi trạng thái một việc (A1–A10, B1–B10, mốc ghép), cập nhật **cả hai** nơi ngay trong phiên đó:

1. Bản Markdown: bảng trạng thái trong `docs/word/src/theo-doi-tien-do.md` (và mục tiến độ của `docs/context/05-ke-hoach-ky-thuat-AB.md`, nếu có).
2. Bản Word: chạy `bash docs/word/build.sh` để dựng lại `docs/word/ShipAudit_04_Theo-doi-tien-do.docx`. Nếu trạng thái chạm yêu cầu bắt buộc hoặc bài nộp, sửa thêm `docs/word/src/brief-va-checklist.md` rồi build lại.

Chỉ ghi trạng thái đã làm thật (có code chạy hoặc có file). Nói rõ với người dùng đã cập nhật những file nào.

## Datadog (đã kết nối 21/10)

Tổ chức Datadog của đội ở site **`uk1.datadoghq.com`**, không phải site mặc định. Trong `.env` đặt `DD_SITE=uk1.datadoghq.com`, và đổi dòng tương ứng trong `.env.example` (file chung, báo A). Key chỉ nằm trong `.env`, không commit. Tạo dashboard và monitor bằng API (cần `DD_API_KEY` và `DD_APP_KEY`), đặt tên có tiền tố `ShipAudit`, xuất JSON vào `datadog/biz/`. Tổ chức đã có sẵn 11 dashboard và các monitor mẫu của Datadog, không xóa hay sửa.

**Theo dõi frontend và thao tác người dùng (người dùng yêu cầu ghi nhớ, 22/10):** Datadog theo dõi được phía giao diện bằng RUM (Real User Monitoring): phiên người dùng, lượt xem trang, thao tác bấm, lỗi trình duyệt, độ trễ tải trang. Có thể là "năng lực Datadog bổ sung" cho đề (cạnh Log Management, APM, Anomaly Detection) và làm rõ bước điều tra (nối thao tác trên giao diện với trace và log của API). Hiện tổ chức chưa có ứng dụng RUM nào. Lưu ý kỹ thuật: giao diện của dự án là Streamlit (render phía máy chủ), nên chưa chắc gắn được RUM Browser SDK vào trang chính; chèn script bằng `st.components.v1.html` chỉ theo dõi trong khung iframe. Khi tới B8/B9, thử và báo người dùng khả năng thực tế. Phương án thay thế nếu không gắn được: ghi log hoặc metric phía máy chủ cho các thao tác chính trên UI (xem trang nào, duyệt claim) kèm mã phiên, đừng gọi đó là RUM.

## MongoDB (đã chốt 22/10)

- **Nơi chạy chính: MongoDB Atlas**, cluster miễn phí `Cluster0` (bản 8.0.34, replica set 3 nút, vùng AWS Hong Kong). Địa chỉ: `cluster0.59qk4zc.mongodb.net`. Người dùng database: `shipaudit` (quyền Read and write to any database). Không có container Mongo trong `docker-compose.yml`.
- **Biến môi trường** (tên theo `.env.example`): `MONGO_URI=mongodb+srv://shipaudit:<mật khẩu>@cluster0.59qk4zc.mongodb.net/` và `MONGO_DB=shipaudit_b_dev`. Người dùng đã tạo `.env` ở gốc repo (không commit, đã nằm trong `.gitignore`). Mật khẩu chỉ nằm trong `.env`; không in ra màn hình, không ghi vào log, không đưa vào tài liệu.
- **Tên database:** mỗi người một database riêng khi phát triển (B dùng `shipaudit_b_dev`, A dùng tên khác) để không ghi đè nhau. Bản demo chung và phần ghép (I3, I4) dùng một database chung do hai người thống nhất.
- **Đã kết nối được từ máy người dùng (22/10)** bằng pymongo (`ping` ok, đọc ghi `shipaudit_b_dev` được). Compass báo lỗi lúc thử trước đó, chưa biết nguyên văn. Nếu sau này lỗi kết nối, nguyên nhân thường gặp: chưa thêm IP máy vào **Network Access** trên Atlas, sai mật khẩu, cluster đang tạm dừng (bấm Resume), hoặc mạng/phần mềm diệt virus chặn.
- **Gói miễn phí:** tự tạm dừng khi lâu không dùng (nhớ Resume trước khi chạy hoặc quay demo). Chưa kiểm tra gói này hỗ trợ đủ Time Series (`ingest_events`) và Change Streams cho việc của A; nếu lỗi thì báo người dùng.
- **Sau khi mọi thứ chạy ổn:** người dùng nên đặt lại mật khẩu người dùng `shipaudit` (mật khẩu đã từng xuất hiện trong khung chat), rồi cập nhật `.env`. Người dùng Atlas cũ trên cluster nên xóa nếu không dùng.
- **Phương án dự phòng:** máy người dùng có MongoDB Server 8.0 cài sẵn (`C:\Program Files\MongoDB\Server\8.0`) nhưng không chạy và chưa bật replica set. Nếu dùng: chạy `mongod --dbpath <thư mục> --replSet rs0`, trong `mongosh` gõ `rs.initiate()`, rồi `MONGO_URI=mongodb://localhost:27017/?replicaSet=rs0`. `mongosh` chưa nằm trong PATH; file chạy ở `C:\Program Files\mongosh-2.5.0-win32-x64\mongosh-2.5.0-win32-x64\bin\mongosh.exe`.
