"""[A] Log JSON, kèm trace_id khi có ddtrace (DD_LOGS_INJECTION=true).

Mọi trường truyền qua `extra=` (carrier, order_code, diff, statement_id...) đều được đưa vào dòng JSON,
để Datadog Log Management lọc và nhóm được theo trường.

Có Agent thì Agent đọc stdout. Không có Agent (chạy trên máy, không Docker): đặt DD_LOGS_AGENTLESS=true và
DD_API_KEY thì log được gom và gửi thẳng lên Datadog Logs API (http-intake.logs.<DD_SITE>) theo lô.
"""
import logging
import os
import sys

from common.dd_logs import DatadogLogHandler, JsonFormatter  # noqa: F401  (dùng chung với ui/, giữ đường dẫn cũ)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    api_key = os.getenv("DD_API_KEY", "")
    if api_key and os.getenv("DD_LOGS_AGENTLESS", "false").lower() == "true":
        root.handlers.append(DatadogLogHandler(api_key, os.getenv("DD_SITE", "datadoghq.com")))
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):  # log của uvicorn cũng ra JSON
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
