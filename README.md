# ShipAudit

Đối soát cước vận tải 3PL theo quy tắc từng hãng: tính **số tiền phải nhận** của từng đơn,
so với **số tiền thực nhận**, cảnh báo chênh lệch theo hạn khiếu nại.

MUGVN Hackathon 2026 · Real-time Operations (MongoDB x Datadog).
Chỉ dùng dữ liệu tổng hợp hoặc dataset công khai. Hãng vận chuyển trong demo là hãng giả (Carrier A/B/C).

## Phân công

| | Phạm vi | Thư mục chính |
|---|---|---|
| **A** | Đường ống và quan sát: nạp dữ liệu, API, Change Streams, telemetry, Datadog vận hành, webhook | `app/`, `datadog/ops/`, `scenarios/ops/` |
| **B** | Đúng sai của con số: dữ liệu, quy tắc hãng, engine, pipeline, Streamlit, Datadog nghiệp vụ | `core/`, `pipelines/`, `generator/`, `ui/`, `datadog/biz/`, `scenarios/biz/` |

Chi tiết: `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx`. Tiến độ cập nhật ở mục 10 của file đó.

## Quy tắc ngắn

- `main` luôn chạy được. Mỗi người một nhánh feature, PR nhỏ, người kia duyệt trong 12 giờ.
- Hai bên chỉ chạm nhau qua `contracts/`. Đổi contract thì sửa cùng PR và tăng `contracts/VERSION`.
- `core/` không import từ `app/`. `ui/` chỉ đọc qua `core/queries.py`.
- Tiền là số nguyên VNĐ (hoặc `Decimal`), không dùng float.
- Ghi công cụ AI đã dùng vào `docs/ai-usage-log.md`, thư viện và dataset ngoài vào `docs/reuse-and-data.md`.

## Chạy

Cần Python ≥ 3.11 và một MongoDB replica set (đội dùng MongoDB Atlas; Change Streams cần replica set).

```bash
cp .env.example .env        # điền MONGO_URI, MONGO_DB, DD_API_KEY, DD_SITE=uk1.datadoghq.com, WEBHOOK_SECRET
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q         # test; test cần Atlas tự bỏ qua khi không kết nối được (hoặc SHIPAUDIT_SKIP_ATLAS=1)
```

### Chạy trên máy, không Docker

Mỗi lệnh một cửa sổ terminal, tại thư mục gốc repo:

```bash
python -m generator.seed --load --reconcile               # B: sinh dữ liệu tổng hợp (seed 42) và nạp vào MONGO_DB
uvicorn app.main:app --port 8000                          # A: API (POST /statements, GET /reconciliations, /health, webhook)
python -m app.workers.change_stream                       # A: worker Change Streams, log chênh lệch mới
streamlit run ui/app.py                                   # B: giao diện
python -m core.metrics_job                                # B: metric shipaudit.biz.* mỗi 60 giây
```

Không có Datadog Agent: metric gửi thẳng Datadog API khi có `DD_API_KEY`; đặt `DD_LOGS_AGENTLESS=true` để log của API
và giao diện lên Log Management, `SHIPAUDIT_DD_EVENTS=true` để mỗi thao tác claim (tạo nháp, duyệt, gửi hãng, hãng hoàn
tiền) thành một sự kiện trên Datadog, hiện thành vạch đứng trên đồ thị. Ví dụ:

```bash
DD_LOGS_AGENTLESS=true SHIPAUDIT_DD_EVENTS=true uvicorn app.main:app --port 8000
DD_LOGS_AGENTLESS=true SHIPAUDIT_DD_EVENTS=true streamlit run ui/app.py
```

Trace (APM) cần Agent.

Thử API:

```bash
curl http://localhost:8000/health
curl -F carrier=carrier_b -F file=@contracts/samples/statement_carrier_b.csv http://localhost:8000/statements
curl "http://localhost:8000/reconciliations?carrier=carrier_b&limit=5"
```

Một lệnh cho cả bộ demo (Windows PowerShell, mở mỗi phần một cửa sổ):

```powershell
.\scripts\demo.ps1                 # bộ dữ liệu demo chat_v1, giờ mô phỏng 23/10 08:00
.\scripts\demo.ps1 -Tunnel         # thêm tunnel Cloudflare cho webhook Datadog và link giao diện công khai
.\scripts\demo.ps1 -ReadOnly       # giao diện chỉ xem (ẩn nút duyệt, gửi hãng, ghi nhận thu hồi)
```

### Bản demo cho giám khảo

Giao diện chỉ xem trên Streamlit Community Cloud (`requirements.txt`, mẫu secrets `.streamlit/secrets.toml.example`,
`SHIPAUDIT_READ_ONLY=true`), người dùng Atlas chỉ đọc, Datadog bằng tài khoản Read Only hoặc ảnh chụp và video.
Hướng dẫn từng bước: [`docs/demo-cho-giam-khao.md`](docs/demo-cho-giam-khao.md).

### Kịch bản sự cố

```bash
python -m scenarios.ops.run --api http://localhost:8000          # A: bật công tắc lỗi nạp → monitor vận hành
python -m scenarios.biz.run --db shipaudit_b_scenario --reset    # B: bảng kê Carrier B bị trừ lệch → monitor nghiệp vụ
```

Mỗi pha giữ vài phút để monitor Datadog (cửa sổ 5 phút) kịp đánh giá. Báo cáo ghi vào `generator/out/scenario/`.

Kịch bản nghiệp vụ có 5 pha: bình thường → sự cố (tiền nhận thiếu vượt ngưỡng) → sát hạn khiếu nại (webhook tạo claim
nháp) → duyệt và gửi hãng → hãng hoàn tiền (claim Đã thu hồi). Tùy chọn:

- `--webhook real`: chờ Datadog gọi webhook thật (cần API chạy cùng `MONGO_DB`, `SHIPAUDIT_NOW=2026-10-22T13:00:00+07:00`
  và địa chỉ công khai, ví dụ `cloudflared tunnel --url http://127.0.0.1:8000`); không thấy thì giả lập dự phòng.
- `--approve-by "Tên"`, `--recover-by "Tên"`: tự duyệt và ghi nhận hãng hoàn tiền; không đặt thì chờ người làm trên giao diện.

### Dashboard và monitor Datadog

JSON nằm ở `datadog/ops/` và `datadog/biz/`; tạo hoặc cập nhật bằng `python datadog/ops/apply.py` và
`python datadog/biz/apply.py` (cần `DD_APP_KEY`), hoặc nhập JSON trên giao diện Datadog. Id đã tạo ở `deployed.json`.

Lớp nghiệp vụ (`datadog/biz/`) gồm: dashboard, 6 monitor (vượt ngưỡng, sắp hết hạn khiếu nại, Anomaly Detection,
Forecast, Outlier so sánh các hãng, Composite mở case), SLO "xử lý chênh lệch trước khi sát hạn khiếu nại", notebook điều
tra 5 bước, pipeline log và log-based metric. Một lệnh tạo tất cả, đúng thứ tự phụ thuộc:

```bash
python datadog/biz/apply.py --notify @webhook-shipaudit-claims --case-handle @case-<handle>
```

Chi tiết và cách lấy handle Case Management: `datadog/biz/README.md`.

### Docker

`docker compose up --build` (hoặc `make up`) chạy 5 container dùng chung một ảnh `app/Dockerfile`:

| Service | Việc | Cổng |
|---|---|---|
| api | FastAPI: nạp bảng kê, xem đối soát, webhook Datadog | 8000 |
| worker | change stream của `reconciliations` | |
| metrics-job | phát `shipaudit.biz.*` mỗi 60 giây (B9) | |
| ui | Streamlit | 8501 |
| datadog-agent | nhận trace (APM), log container, DogStatsD | 8125/udp, 8126 |

Cần `.env` có `MONGO_URI`, `MONGO_DB`, `DD_API_KEY` (site `uk1.datadoghq.com`). Có Agent nên compose tắt chế độ agentless
(`DD_METRICS_AGENTLESS=false`, `DD_LOGS_AGENTLESS=false`): metric, log và trace đều đi qua Agent, log nối được với trace
nhờ `DD_LOGS_INJECTION`. Trên Windows cần bật Docker Desktop trước. Kiểm tra cú pháp không cần bật Docker:
`docker compose config --services`.

## Cấu trúc

Xem `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx` mục 7. Mỗi thư mục có docstring ở file chính nêu việc của nó.
