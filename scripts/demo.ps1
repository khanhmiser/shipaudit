<#
.SYNOPSIS
  Chạy bản demo ShipAudit trên máy (không Docker): job metric Datadog, API, giao diện Streamlit, mỗi phần một cửa sổ.

.EXAMPLE
  .\scripts\demo.ps1                                   # bộ dữ liệu demo chat_v1, giờ mô phỏng 23/10 08:00
  .\scripts\demo.ps1 -Tunnel                           # mở thêm tunnel Cloudflare cho API (webhook) và giao diện
  .\scripts\demo.ps1 -ReadOnly -Tunnel                 # chia sẻ link giao diện chỉ xem (ẩn nút duyệt, ghi nhận)
  .\scripts\demo.ps1 -Db shipaudit_scenario -Now 2026-10-22T13:00:00+07:00

.NOTES
  Cần .env có MONGO_URI và DD_API_KEY (DD_SITE). Log và sự kiện claim gửi thẳng Datadog (không cần Agent).
  Đóng một cửa sổ là dừng phần đó. Link trycloudflare đổi mỗi lần mở tunnel: webhook Datadog `shipaudit-claims`
  phải cập nhật theo địa chỉ mới của API.
#>
param(
    [string]$Db = "shipaudit_b_chat_v1",
    [string]$Now = "2026-10-23T08:00:00+07:00",
    [switch]$ReadOnly,
    [switch]$Tunnel,
    [switch]$NoMetrics
)

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Không thấy $Py. Tạo môi trường: python -m venv .venv; .venv\Scripts\pip install -e "".[dev]""" }
if (-not (Test-Path (Join-Path $Root ".env"))) { throw "Thiếu .env ở $Root (xem .env.example)." }

$ro = if ($ReadOnly) { "true" } else { "false" }
$EnvSetup = "`$env:MONGO_DB='$Db'; `$env:SHIPAUDIT_NOW='$Now'; `$env:SHIPAUDIT_READ_ONLY='$ro'; " +
            "`$env:DD_LOGS_AGENTLESS='true'; `$env:SHIPAUDIT_DD_EVENTS='true'; `$env:PYTHONIOENCODING='utf-8';"

function Start-Window([string]$Title, [string]$Command) {
    $full = "`$host.UI.RawUI.WindowTitle='ShipAudit - $Title'; Set-Location -LiteralPath '$Root'; $EnvSetup $Command"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $full) | Out-Null
    Write-Host "  mở cửa sổ: $Title"
}

Write-Host "ShipAudit demo: database $Db, giờ mô phỏng $Now, chỉ xem: $ro"
if (-not $NoMetrics) { Start-Window "metric Datadog" "& '$Py' -m core.metrics_job" }
Start-Window "API :8000" "& '$Py' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Window "giao diện :8501" "& '$Py' -m streamlit run ui/app.py --server.port 8501 --server.headless true"

if ($Tunnel) {
    $cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (-not (Test-Path $cf)) { $cf = "cloudflared" }
    Start-Window "tunnel API" "& '$cf' tunnel --url http://127.0.0.1:8000"
    Start-Window "tunnel giao diện" "& '$cf' tunnel --url http://127.0.0.1:8501"
    Write-Host "  Xem địa chỉ https://...trycloudflare.com trong hai cửa sổ tunnel."
    Write-Host "  Địa chỉ API dùng cho webhook Datadog; địa chỉ giao diện gửi người xem."
}
Write-Host "Giao diện trên máy: http://localhost:8501"
