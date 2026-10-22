"""Vá nhỏ cho mongomock khi chạy với pymongo mới (giống tests/api/conftest.py): pymongo ≥ 4.11 truyền
thêm `sort=` vào BulkOperationBuilder.add_update, mongomock 4.3 chưa nhận tham số này.
"""
import os

# Test không gửi metric / log thật lên Datadog, kể cả khi .env có DD_API_KEY.
os.environ["DD_METRICS_AGENTLESS"] = "false"
os.environ["DD_LOGS_AGENTLESS"] = "false"

import mongomock.collection

_orig_add_update = mongomock.collection.BulkOperationBuilder.add_update


def _add_update(self, *args, sort=None, **kwargs):
    return _orig_add_update(self, *args, **kwargs)


if not getattr(mongomock.collection.BulkOperationBuilder.add_update, "_shipaudit_patched", False):
    _add_update._shipaudit_patched = True
    mongomock.collection.BulkOperationBuilder.add_update = _add_update
