"""[A] POST /webhooks/datadog: kiểm tra secret, tạo claim nháp, idempotent theo alert id.

- Secret: header X-ShipAudit-Secret phải bằng WEBHOOK_SECRET (cấu hình ở custom header của webhook Datadog).
- Payload: xem DatadogAlert và mẫu datadog/ops/webhook.json. `alert_id` nên là $ALERT_CYCLE_KEY.
- Thông báo hết báo động (Recovered) hoặc mất dữ liệu (No Data): bỏ qua, trả 200.
- Có `reconciliation_id`: tạo claim nháp cho đúng bản ghi đó. Không có: lấy hãng từ tag `carrier:` trong
  scope hoặc tags, tạo claim nháp cho mọi khoản doanh nghiệp nhận thiếu của hãng đó còn hạn khiếu nại và hết
  hạn trong `within_hours` giờ tới.
- Gọi B qua contracts.interfaces.ClaimService.create_draft(reconciliation_id, "datadog_webhook", alert_id):
  dùng core.claims.ClaimService của B.
  Idempotent: gửi lại cùng alert_id không tạo thêm claim (B bảo đảm bằng index unique).
- Chỉ tạo claim nháp. Con người duyệt trước khi gửi hãng.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.models import DatadogAlert, WebhookClaim, WebhookResult
from app.deps import get_db
from app.telemetry.metrics import increment
from common import config
from common.enums import Collections
from contracts.interfaces import ClaimService
from core import events

log = logging.getLogger("shipaudit.webhook")

router = APIRouter(tags=["webhooks"])

SOURCE = "datadog_webhook"
IGNORED_TRANSITIONS = ("recovered", "no data")
_CARRIER = re.compile(r"(?:^|[,\s{])carrier:([a-z0-9_]+)")


def require_secret(x_shipaudit_secret: Annotated[str | None, Header()] = None) -> None:
    secret = os.getenv("WEBHOOK_SECRET", config.WEBHOOK_SECRET)
    if not hmac.compare_digest(x_shipaudit_secret or "", secret):
        raise HTTPException(status_code=401, detail="sai hoặc thiếu X-ShipAudit-Secret")


def now() -> datetime:
    """Giờ hiện tại. Đặt SHIPAUDIT_NOW (ISO) để chạy demo ở giờ mô phỏng của dữ liệu seed (cùng cách ui/shared.py)."""
    fixed = os.getenv("SHIPAUDIT_NOW")
    if fixed:
        from core.periods import as_aware

        return as_aware(fixed)
    return datetime.now(timezone.utc)


def claim_service(db: Any) -> ClaimService:
    from core.claims import ClaimService as RealClaimService

    return RealClaimService(db, now=now)


def carrier_of(alert: DatadogAlert) -> str | None:
    tags = ",".join(alert.tags) if isinstance(alert.tags, list) else (alert.tags or "")
    for text in (alert.scope or "", tags):
        m = _CARRIER.search(text)
        if m:
            return m.group(1)
    return None


def expiring_reconciliations(db: Any, carrier: str, within_hours: float, now: datetime) -> list[str]:
    """Khoản nhận thiếu của hãng còn hạn khiếu nại và hết hạn trong `within_hours` giờ tới (gần hạn trước)."""
    now_db = now.astimezone(timezone.utc).replace(tzinfo=None)
    cur = db[Collections.RECONCILIATIONS].find(
        {"carrier": carrier, "diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"},
         "claim_deadline_at": {"$gt": now_db, "$lte": now_db + timedelta(hours=within_hours)}},
        {"reconciliation_id": 1, "statement_id": 1, "order_code": 1},
    ).sort([("claim_deadline_at", 1), ("reconciliation_id", 1)])
    # Khoản đã có kết quả từ hãng (hoàn tiền hoặc từ chối) không khiếu nại lại; từ chối thì doanh nghiệp tự liên hệ hãng.
    resolved = set(db[Collections.CLAIMS].distinct(
        "reconciliation_id", {"carrier": carrier, "status": {"$in": ["RECOVERED", "REJECTED"]}}))
    ids = [r.get("reconciliation_id") or f"{r['statement_id']}:{r['order_code']}" for r in cur]
    return [rid for rid in ids if rid not in resolved]


@router.post("/webhooks/datadog", response_model=WebhookResult, dependencies=[Depends(require_secret)])
def datadog_webhook(alert: DatadogAlert, db: Any = Depends(get_db)) -> WebhookResult:
    transition = (alert.alert_transition or "").strip().lower()
    if any(word in transition for word in IGNORED_TRANSITIONS):
        log.info("webhook Datadog: bỏ qua", extra={"alert_id": alert.alert_id, "transition": alert.alert_transition})
        return WebhookResult(alert_id=alert.alert_id, action="ignored", reason=alert.alert_transition)

    carrier = carrier_of(alert)
    if alert.reconciliation_id:
        targets = [alert.reconciliation_id]
    elif carrier:
        targets = expiring_reconciliations(db, carrier, alert.within_hours, now())
    else:
        raise HTTPException(status_code=422, detail="payload thiếu reconciliation_id hoặc tag carrier:<mã hãng>")

    svc = claim_service(db)
    seen = {c["claim_id"] for c in db[Collections.CLAIMS].find({"alert_id": alert.alert_id}, {"claim_id": 1})}
    claims, created, errors = [], [], []
    for rid in targets:
        try:
            c = svc.create_draft(rid, SOURCE, alert.alert_id)
            claims.append(WebhookClaim(claim_id=c.get("claim_id"), reconciliation_id=rid, status=c.get("status", "")))
            created.append(c)
        except ValueError as e:  # ClaimError của B: không còn gì để khiếu nại, quá hạn...
            errors.append(f"{rid}: {e}")
    # Sự kiện Datadog (vạch trên dashboard), gộp theo hãng, chỉ cho claim mới tạo ở lần gọi này (Datadog có thể gọi
    # lại cùng alert); chỉ gửi khi SHIPAUDIT_DD_EVENTS=true.
    new = [c for c in created if c.get("carrier") and c.get("alert_id") == alert.alert_id and c.get("claim_id") not in seen]
    events.publish("created", new, by=SOURCE, source=SOURCE)
    log.warning("webhook Datadog: tạo claim nháp", extra={
        "alert_id": alert.alert_id, "monitor_id": alert.monitor_id, "carrier": carrier, "count": len(claims),
        "errors": len(errors), "amount": sum(int(c.get("amount") or 0) for c in created)})
    increment("shipaudit.ops.webhook_calls", 1, {"carrier": carrier or "none", "result": "created"})
    return WebhookResult(alert_id=alert.alert_id, action="created", carrier=carrier, count=len(claims),
                         claims=claims, errors=errors)
