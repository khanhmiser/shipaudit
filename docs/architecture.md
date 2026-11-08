# Kiến trúc ShipAudit

ShipAudit tính **số tiền phải nhận** của từng đơn theo quy tắc từng hãng, so với **số tiền thực nhận** trong bảng kê,
cảnh báo chênh lệch theo **hạn khiếu nại**. Tài liệu này gồm bốn sơ đồ (Mermaid, GitHub tự vẽ): kiến trúc tổng thể,
luồng dữ liệu, mô hình dữ liệu MongoDB và kiến trúc quan sát trên Datadog. Hãng trong demo là hãng giả Carrier A/B/C,
dữ liệu tổng hợp (seed cố định 42).

## 1. Kiến trúc tổng thể

```mermaid
flowchart LR
    subgraph IN["Đầu vào"]
        CSV["Bảng kê CSV của hãng"]
        GEN["generator/<br/>dữ liệu tổng hợp + labels.json"]
    end

    subgraph A["Phần A: đường ống và quan sát (app/)"]
        API["FastAPI<br/>POST /statements<br/>GET /reconciliations<br/>POST /webhooks/datadog"]
        ING["Luồng nạp<br/>parse theo hãng, ghi statement_lines"]
        CS["Worker Change Streams<br/>log chênh lệch mới"]
    end

    subgraph B["Phần B: đúng sai của con số (core/, pipelines/, ui/)"]
        RULES["core/rules.py<br/>quy tắc hãng (dữ liệu)"]
        ENG["core/engine.py<br/>compute_expected"]
        REC["core/reconcile.py<br/>reconcile_statement"]
        CLM["core/claims.py<br/>DRAFT → APPROVED → SUBMITTED<br/>→ RECOVERED / REJECTED / EXPIRED"]
        PIPE["pipelines/<br/>Aggregation Pipeline"]
        JOB["core/metrics_job.py<br/>shipaudit.biz.*"]
        UI["Streamlit ui/<br/>đọc qua core/queries.py"]
    end

    DB[("MongoDB Atlas<br/>carrier_rules · orders · statement_lines<br/>reconciliations · claims · ingest_events")]
    DD["Datadog (uk1)<br/>metric · log · APM · monitor · SLO · notebook"]
    HUMAN(["Con người duyệt claim"])

    CSV --> API --> ING --> DB
    GEN --> DB
    ING --> REC
    REC --> ENG --> RULES
    RULES --- DB
    REC --> DB
    DB --> CS --> DD
    DB --> PIPE --> UI
    DB --> JOB --> DD
    API --> DD
    DD -- "webhook khi sát hạn" --> API
    API -- "create_draft (idempotent theo alert_id)" --> CLM
    CLM --> DB
    UI --> HUMAN --> CLM
```

Hai phần chỉ chạm nhau qua `contracts/` (giao diện, schema, mẫu). `core/` không import từ `app/`; `ui/` chỉ đọc Mongo
qua `core/queries.py`, không gọi API của A. Không dùng AI hay LLM để tính tiền; con người duyệt claim trước khi gửi hãng.

## 2. Luồng dữ liệu: từ bảng kê đến claim

```mermaid
sequenceDiagram
    autonumber
    participant D as Doanh nghiệp
    participant API as FastAPI (A)
    participant ING as Luồng nạp (A)
    participant R as reconcile_statement (B)
    participant M as MongoDB
    participant DD as Datadog
    participant C as ClaimService (B)
    participant U as Streamlit (B)

    D->>API: POST /statements (carrier, file CSV)
    API->>ING: parse theo hãng
    ING->>M: upsert statement_lines (statement_id, order_code)
    ING->>R: reconcile_statement(statement_id)
    R->>M: đọc orders + carrier_rules
    R->>R: phải nhận = thu hộ + trả trước + ... − phí − chuyển khoản
    R->>M: upsert reconciliations (diff = phải nhận − thực nhận)
    ING->>M: ghi ingest_events (Time Series)
    M-->>DD: metric shipaudit.biz.* (diff_amount, diff_count, claim_hours_left)
    DD-->>API: webhook khi vượt ngưỡng hoặc sát hạn khiếu nại
    API->>C: create_draft(reconciliation_id, "datadog_webhook", alert_id)
    C->>M: claim DRAFT (unique theo alert_id)
    U->>M: xem chênh lệch, hạn khiếu nại
    U->>C: duyệt → gửi hãng → ghi nhận hãng hoàn tiền
```

Tính đúng một lần: `reconcile_statement` idempotent theo `(statement_id, order_code)`, `create_draft` idempotent theo
`alert_id`, nên nạp lại hoặc webhook gửi lại không tạo bản ghi trùng.

Công thức đối soát (cài ở `Breakdown.expected_amount` trong `contracts/interfaces.py`, có test
`tests/core/test_breakdown_formula.py`):

> Tiền đối soát = Tiền thu hộ + Doanh nghiệp trả trước + Doanh nghiệp trả phí khi trả hàng − Phí giao hàng − Phí bảo hiểm − Phí chuyển hoàn
> − Phí lưu kho − Phí thay đổi địa chỉ − Phí đồng kiểm + Khuyến mãi − Phí chuyển khoản. Chênh lệch = phải nhận − thực nhận.

Năm loại chênh lệch: `FEE_MISMATCH`, `RETURN_FEE_DOUBLE`, `MISSING_IN_STATEMENT`, `COD_MISMATCH`, `LATE_PAYOUT`.

## 3. Mô hình dữ liệu MongoDB

Schema chính thức ở `contracts/schemas/*.json`; sơ đồ dưới đây chỉ nêu trường chính.

```mermaid
erDiagram
    carrier_rules ||--o{ orders : "áp quy tắc theo carrier"
    orders ||--o{ statement_lines : "order_code"
    statement_lines ||--o| reconciliations : "(statement_id, order_code)"
    reconciliations ||--o{ claims : "reconciliation_id"
    statement_lines }o--|| ingest_events : "meta.statement_id"

    carrier_rules {
        string carrier
        int version
        number dim_weight_divisor
        object rate_table
        object surcharges
        int cod_payout_days
        int claim_window_hours
        string claim_deadline_anchor
        object transfer_fee
    }
    orders {
        string order_code
        string carrier
        int weight_g
        int cod_amount
        string status
        date delivered_at
    }
    statement_lines {
        string statement_id
        string order_code
        int cod_collected
        int shipping_fee
        int net_paid
        date paid_at
    }
    reconciliations {
        string statement_id
        string order_code
        int expected_amount
        int actual_amount
        int diff
        string diff_type
        object breakdown
        date claim_deadline_at
        number claim_hours_left
    }
    claims {
        string reconciliation_id
        string status
        string source
        string alert_id
        int amount
        string approved_by
    }
    ingest_events {
        date ts
        object meta
        int rows
        int duration_ms
        number lag_seconds
        string status
    }
```

Quy tắc hãng là dữ liệu trong `carrier_rules`: đổi tham số hãng không phải sửa code. Tiền là số nguyên VNĐ, không dùng float
(`core/money.py`). `ingest_events` là Time Series (có TTL 14 ngày, tự chuyển sang collection thường nếu gói Atlas không hỗ trợ).

## 4. Kiến trúc quan sát trên Datadog

```mermaid
flowchart TB
    subgraph SRC["Nguồn tín hiệu"]
        M1["metric shipaudit.biz.*<br/>(core/metrics_job.py, mỗi 60 giây)"]
        M2["metric vận hành<br/>(app/telemetry: độ trễ nạp, lỗi, lag)"]
        L1["log JSON<br/>(API + giao diện, agentless hoặc Agent)"]
        E1["sự kiện claim<br/>(tạo nháp, duyệt, gửi hãng, hoàn tiền)"]
        T1["trace APM (cần Agent)"]
    end

    subgraph DDG["Datadog uk1.datadoghq.com"]
        DASH["Dashboard ShipAudit<br/>(datadog/ops, datadog/biz)"]
        MON["Monitor<br/>vượt ngưỡng · sắp hết hạn khiếu nại<br/>Anomaly · Forecast · Outlier giữa các hãng<br/>Composite mở case"]
        SLO["SLO: xử lý chênh lệch<br/>trước hạn khiếu nại"]
        NB["Notebook điều tra 5 bước"]
        LOGP["Pipeline log + log-based metric"]
    end

    M1 --> DASH
    M2 --> DASH
    L1 --> LOGP --> DASH
    E1 --> DASH
    T1 --> NB
    M1 --> MON
    M1 --> SLO
    MON -- "@webhook-shipaudit-claims" --> WH["POST /webhooks/datadog"]
    WH --> CL["claim nháp<br/>(con người duyệt)"]
    MON --> CASE["Case Management"]
```

Dashboard, monitor, SLO, notebook xuất JSON ở `datadog/ops/` và `datadog/biz/`; tạo lại bằng
`python datadog/ops/apply.py` và `python datadog/biz/apply.py`. Id đã tạo ghi ở `deployed.json`. Khi chưa có Datadog,
metric in ra console (fallback trong `Metrics`).

## 5. Bảng ánh xạ thư mục

| Thư mục | Vai trò | Phần |
|---|---|---|
| `contracts/`, `common/` | giao diện, schema, mẫu, enum dùng chung | A + B |
| `app/` | API, luồng nạp, worker Change Streams, telemetry, webhook | A |
| `core/` | quy tắc hãng, engine, đối soát, claims, index, truy vấn, job metric | B |
| `pipelines/` | Aggregation Pipeline (chênh lệch theo hãng, xu hướng, claim sắp hết hạn, đơn thiếu...) | B |
| `generator/` | dữ liệu tổng hợp, chèn 5 loại chênh lệch, `labels.json` làm đáp án kiểm thử | B |
| `ui/` | giao diện Streamlit (tổng quan, chênh lệch, chi tiết đơn, hạn khiếu nại, so sánh hãng, claims, thông tin hãng) | B |
| `datadog/ops/`, `datadog/biz/` | dashboard, monitor, SLO, notebook (JSON + `apply.py`) | A / B |
| `scenarios/ops/`, `scenarios/biz/` | kịch bản sự cố vận hành và nghiệp vụ | A / B |
| `tests/` | test theo từng phần; golden test khớp từng đồng trên dữ liệu seed | A + B |
