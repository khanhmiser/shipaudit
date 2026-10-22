"""[A] Log JSON, kèm trace_id khi có ddtrace (DD_LOGS_INJECTION=true).

Mọi trường truyền qua `extra=` (carrier, order_code, diff, statement_id...) đều được đưa vào dòng JSON,
để Datadog Log Management lọc và nhóm được theo trường.

Có Agent thì Agent đọc stdout. Không có Agent (chạy trên máy, không Docker): đặt DD_LOGS_AGENTLESS=true và
DD_API_KEY thì log được gom và gửi thẳng lên Datadog Logs API (http-intake.logs.<DD_SITE>) theo lô.
"""
import atexit
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable

# Thuộc tính sẵn có của LogRecord, không phải trường do người gọi truyền vào.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def payload(self, record: logging.LogRecord) -> dict:
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
        return payload

    def format(self, record: logging.LogRecord) -> str:
        # Chỉ ký tự ASCII (tiếng Việt thành mã \uXXXX): không lỗi khi console Windows dùng cp1252,
        # Datadog vẫn giải mã ra đúng tiếng Việt.
        return json.dumps(self.payload(record), default=str)


class DatadogLogHandler(logging.Handler):
    """Gom log JSON và gửi lên Datadog Logs API v2 theo lô (mỗi `every` giây hoặc khi đủ `batch` dòng)."""

    def __init__(self, api_key: str, site: str, every: float = 5, batch: int = 200,
                 opener: Callable = urllib.request.urlopen, start_thread: bool = True):
        super().__init__()
        self.url = f"https://http-intake.logs.{site}/api/v2/logs"
        self._api_key = api_key
        self._opener = opener
        self._batch = batch
        self._buf: list[dict] = []
        self._buf_lock = threading.Lock()
        self._tags = f"env:{os.getenv('DD_ENV', 'dev')}"
        self._host = socket.gethostname()
        self.setFormatter(JsonFormatter())
        if start_thread:
            threading.Thread(target=self._loop, args=(every,), name="dd-logs-flush", daemon=True).start()
            atexit.register(self.flush)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = json.loads(json.dumps(self.formatter.payload(record), default=str))
            item.update(ddsource="python", ddtags=self._tags, hostname=self._host, status=record.levelname.lower())
            with self._buf_lock:
                self._buf.append(item)
                full = len(self._buf) >= self._batch
            if full:
                self.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _loop(self, every: float) -> None:
        while True:
            time.sleep(every)
            self.flush()

    def flush(self) -> None:
        with self._buf_lock:
            items, self._buf = self._buf, []
        if not items:
            return
        req = urllib.request.Request(self.url, data=json.dumps(items).encode(), method="POST", headers={
            "Content-Type": "application/json", "DD-API-KEY": self._api_key})
        try:
            with self._opener(req, timeout=10):
                pass
        except (urllib.error.URLError, OSError) as e:
            # Không ghi log ở đây (sẽ quay lại chính handler này); không in khóa.
            print(f"[logs] không gửi được {len(items)} dòng log lên Datadog: {type(e).__name__}", file=sys.stderr)


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
