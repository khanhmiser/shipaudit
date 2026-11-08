"""[A] Phụ thuộc dùng chung cho các router. Test thay get_db bằng mongomock qua app.dependency_overrides."""
from typing import Any

from common.db import get_db as _get_db


def get_db() -> Any:
    return _get_db()
