"""[A] Log JSON, kèm trace_id khi có ddtrace (DD_LOGS_INJECTION=true).

Mọi trường truyền qua `extra=` (carrier, order_code, diff, statement_id...) đều được đưa vào dòng JSON,
để Datadog Log Management lọc và nhóm được theo trường.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Thuộc tính sẵn có của LogRecord, không phải trường do người gọi truyền vào.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": os.getenv("DD_SERVICE", "shipaudit"),
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["error.stack"] = self.formatException(record.exc_info)
        # Chỉ ký tự ASCII (tiếng Việt thành mã \uXXXX): không lỗi khi console Windows dùng cp1252,
        # Datadog vẫn giải mã ra đúng tiếng Việt.
        return json.dumps(payload, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):  # log của uvicorn cũng ra JSON
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
