"""[B] Sự kiện nghiệp vụ lên Datadog Events: vạch đứng trên đồ thị dashboard và dòng thời gian trong notebook điều tra.

Mỗi thao tác trên claim (tạo nháp, duyệt, gửi hãng, hãng hoàn tiền, hãng từ chối, quá hạn) thành **một sự kiện cho mỗi
hãng**, kèm số claim và tổng tiền (ví dụ "Duyệt 181 claim · Carrier B"), không phải mỗi claim một sự kiện.

Bật bằng SHIPAUDIT_DD_EVENTS=true và DD_API_KEY (Events API v1, không cần Agent hay Application Key). Không bật thì không
gửi gì, nên test và lúc chạy thường không phát sự kiện. Lỗi mạng hoặc Datadog không làm hỏng thao tác nghiệp vụ: chỉ in
cảnh báo ra stderr, không in khóa.

Tag: project:shipaudit, layer:biz, service:shipaudit-biz, env, carrier, claim_action. Truy vấn trên dashboard:
`tags:project:shipaudit` (mọi thao tác) hoặc `tags:claim_action:recovered`.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable, Iterable

# hành động → (nhãn tiếng Việt, alert_type của Datadog)
ACTIONS: dict[str, tuple[str, str]] = {
    "created": ("Tạo claim nháp", "info"),
    "approved": ("Duyệt claim", "info"),
    "submitted": ("Gửi hãng", "info"),
    "recovered": ("Hãng hoàn tiền, đã thu hồi", "success"),
    "rejected": ("Hãng từ chối", "warning"),
    "followup": ("Trao đổi với hãng", "info"),
    "expired": ("Claim quá hạn khiếu nại", "warning"),
}
SOURCE_LABELS = {"manual": "tạo tay", "datadog_webhook": "cảnh báo Datadog (webhook)"}


def format_vnd(amount: int) -> str:
    return f"{amount:,}đ".replace(",", ".")


def enabled() -> bool:
    return os.getenv("SHIPAUDIT_DD_EVENTS", "").lower() == "true" and bool(os.getenv("DD_API_KEY"))


def claim_events(action: str, claims: Iterable[dict], by: str = "", source: str | None = None,
                 names: dict[str, str] | None = None) -> list[dict]:
    """Dựng thân sự kiện (Events API v1), một sự kiện cho mỗi hãng. `claims` là các claim sau thao tác."""
    if action not in ACTIONS:
        raise ValueError(f"action phải là một trong {sorted(ACTIONS)}, nhận {action!r}")
    label, alert_type = ACTIONS[action]
    per_carrier: dict[str, dict] = {}
    for c in claims:
        g = per_carrier.setdefault(c["carrier"], {"count": 0, "amount": 0, "recovered": 0, "alerts": set()})
        g["count"] += 1
        g["amount"] += int(c.get("amount") or 0)
        g["recovered"] += int(c.get("recovered_amount") or 0)
        if c.get("alert_id"):
            g["alerts"].add(str(c["alert_id"]))
    env = os.getenv("DD_ENV", "dev")
    out = []
    for carrier, g in sorted(per_carrier.items()):
        name = (names or {}).get(carrier, carrier)
        lines = [f"Số claim: {g['count']}", f"Số tiền khiếu nại: {format_vnd(g['amount'])}"]
        if action == "recovered":
            lines.append(f"Hãng đã hoàn: {format_vnd(g['recovered'])}")
        if by:
            lines.append(f"Người thao tác: {by}")
        if source:
            lines.append(f"Nguồn: {SOURCE_LABELS.get(source, source)}")
        if g["alerts"]:
            lines.append("Mã cảnh báo: " + ", ".join(sorted(g["alerts"])))
        lines.append("Dữ liệu tổng hợp, hãng giả định.")
        tags = ["project:shipaudit", "layer:biz", "service:shipaudit-biz", f"env:{env}",
                f"carrier:{carrier}", f"claim_action:{action}"]
        tags += [f"alert_id:{a}" for a in sorted(g["alerts"])]
        out.append({
            "title": f"ShipAudit: {label} {g['count']} claim · {name}",
            "text": "\n".join(lines),
            "tags": tags,
            "alert_type": alert_type,
            "aggregation_key": f"shipaudit-claims-{carrier}",
            "source_type_name": "my apps",
        })
    return out


class DatadogEvents:
    def __init__(self, api_key: str, site: str = "datadoghq.com", timeout: float = 5,
                 opener: Callable = urllib.request.urlopen):
        self.url = f"https://api.{site}/api/v1/events"
        self._api_key = api_key
        self.timeout = timeout
        self._opener = opener

    def send(self, event: dict) -> bool:
        req = urllib.request.Request(self.url, data=json.dumps(event).encode(), method="POST", headers={
            "Content-Type": "application/json", "DD-API-KEY": self._api_key})
        try:
            with self._opener(req, timeout=self.timeout):
                return True
        except (urllib.error.URLError, OSError) as e:
            print(f"[events] không gửi được sự kiện lên Datadog: {type(e).__name__}", file=sys.stderr)
            return False


def publish(action: str, claims: Iterable[dict], by: str = "", source: str | None = None,
            names: dict[str, str] | None = None, sender: DatadogEvents | None = None) -> int:
    """Gửi sự kiện của một thao tác. Trả về số sự kiện đã gửi (0 khi chưa bật hoặc không có claim nào)."""
    claims = [c for c in claims if c]
    if not claims or (sender is None and not enabled()):
        return 0
    sender = sender or DatadogEvents(os.environ["DD_API_KEY"], os.getenv("DD_SITE", "datadoghq.com"))
    return sum(sender.send(e) for e in claim_events(action, claims, by, source, names))
