"""[A] ddtrace cho FastAPI và PyMongo. Chạy no-op nếu không bật DD_TRACE_ENABLED."""
import os


def setup_tracing() -> None:
    if os.getenv("DD_TRACE_ENABLED", "false").lower() != "true":
        return
    try:
        from ddtrace import patch

        patch(fastapi=True, pymongo=True, logging=True)
    except Exception:
        pass
