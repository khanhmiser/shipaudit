"""[B] create_draft, approve, trạng thái claim. Khớp contracts.interfaces.ClaimService.
Con người duyệt trước khi gửi hãng. create_draft idempotent theo alert_id.

Vòng đời (common.enums.ClaimStatus):
    DRAFT ──approve(người duyệt)──> APPROVED ──submit──> SUBMITTED ──> RECOVERED | REJECTED
      └───────────── quá hạn khiếu nại ─────────────> EXPIRED (chỉ DRAFT / APPROVED)
    REJECTED ──(doanh nghiệp tự liên hệ hãng, hãng đồng ý hoàn)──> RECOVERED
- Không duyệt, không gửi khi đã quá hạn khiếu nại. `submit` chỉ ghi nhận đã gửi; việc gửi hãng do người làm.
- Mỗi lần đổi trạng thái ghi vào `history` (ai, lúc nào) để truy vết.
- Idempotent: cùng `alert_id` + cùng đối soát chỉ ra một claim (index unique, an toàn khi webhook gửi trùng
  cùng lúc). Ngoài ra một đối soát chỉ có một claim đang mở (DRAFT / APPROVED / SUBMITTED), dù tạo tay
  hay từ webhook: gọi lại thì trả về claim đang mở đó.
- Số tiền claim = chênh lệch của bản ghi đối soát (phải nhận − thực nhận), phải > 0.
- Khoản đã có kết quả (hãng hoàn tiền hoặc từ chối) không khiếu nại lại trong hệ thống, kể cả từ webhook. Hãng từ
  chối thì doanh nghiệp tự liên hệ hãng; mỗi lần trao đổi ghi vào `followups` (add_followup) để theo dõi. Lý do từ
  chối bắt buộc ghi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from common.enums import ClaimStatus, Collections
from core.periods import as_aware, to_db

SOURCES = ("manual", "datadog_webhook")
OPEN_STATUSES = (ClaimStatus.DRAFT.value, ClaimStatus.APPROVED.value, ClaimStatus.SUBMITTED.value)
# Đã có kết quả từ hãng: không tạo claim mới cho cùng khoản
RESOLVED_STATUSES = (ClaimStatus.RECOVERED.value, ClaimStatus.REJECTED.value)
# Còn trao đổi với hãng: được ghi nhật ký theo dõi
FOLLOWUP_STATUSES = (ClaimStatus.SUBMITTED.value, ClaimStatus.REJECTED.value)
TRANSITIONS: dict[str, tuple[str, ...]] = {
    ClaimStatus.APPROVED.value: (ClaimStatus.DRAFT.value,),
    ClaimStatus.SUBMITTED.value: (ClaimStatus.APPROVED.value,),
    ClaimStatus.RECOVERED.value: (ClaimStatus.SUBMITTED.value, ClaimStatus.REJECTED.value),
    ClaimStatus.REJECTED.value: (ClaimStatus.SUBMITTED.value,),
    ClaimStatus.EXPIRED.value: (ClaimStatus.DRAFT.value, ClaimStatus.APPROVED.value),
}


class ClaimError(ValueError):
    """Thao tác claim không hợp lệ (sai trạng thái, quá hạn, không có chênh lệch để khiếu nại...)."""


def _clean(doc: dict | None) -> dict | None:
    if doc is not None:
        doc.pop("_id", None)
    return doc


class ClaimService:
    def __init__(self, db: Any, now: Callable[[], datetime] | None = None):
        self.db = db
        self.claims = db[Collections.CLAIMS]
        self._now = now or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        return as_aware(self._now())

    # ── Tạo ──
    def create_draft(self, reconciliation_id: str, source: str, alert_id: str | None = None) -> dict:
        if source not in SOURCES:
            raise ClaimError(f"source phải là một trong {SOURCES}, nhận {source!r}")
        if alert_id is not None:
            existing = self.claims.find_one({"alert_id": alert_id, "reconciliation_id": reconciliation_id})
            if existing:
                return _clean(existing)
        existing = self.claims.find_one({"reconciliation_id": reconciliation_id, "status": {"$in": OPEN_STATUSES}})
        if existing:
            return _clean(existing)
        resolved = self.claims.find_one({"reconciliation_id": reconciliation_id, "status": {"$in": RESOLVED_STATUSES}})
        if resolved and resolved["status"] == ClaimStatus.RECOVERED.value:  # hãng đã hoàn tiền: không khiếu nại lại
            raise ClaimError(f"{reconciliation_id}: hãng đã hoàn tiền (claim {resolved['claim_id']}), không khiếu nại lại")
        if resolved:  # hãng đã từ chối: doanh nghiệp tự liên hệ hãng, theo dõi trên claim cũ
            raise ClaimError(f"{reconciliation_id}: hãng đã từ chối (claim {resolved['claim_id']}); "
                             "liên hệ hãng và ghi nhật ký theo dõi trên claim đó, không tạo claim mới")

        rec = self.db[Collections.RECONCILIATIONS].find_one({"reconciliation_id": reconciliation_id})
        if rec is None:
            raise ClaimError(f"không có bản ghi đối soát {reconciliation_id!r}")
        if rec.get("diff_type") == "NONE" or rec.get("diff", 0) <= 0:
            raise ClaimError(f"{reconciliation_id}: không có khoản nhận thiếu để khiếu nại (diff={rec.get('diff')})")
        now = self.now()
        deadline = rec.get("claim_deadline_at")
        if deadline is not None and as_aware(deadline) <= now:
            raise ClaimError(f"{reconciliation_id}: đã quá hạn khiếu nại")

        doc = {
            "claim_id": f"CLM-{uuid4().hex[:12].upper()}",
            "reconciliation_id": reconciliation_id,
            "statement_id": rec["statement_id"],
            "order_code": rec["order_code"],
            "carrier": rec["carrier"],
            "diff_type": rec["diff_type"],
            "amount": int(rec["diff"]),
            "status": ClaimStatus.DRAFT.value,
            "source": source,
            "claim_deadline_at": deadline,
            "created_at": to_db(now),
            "history": [{"status": ClaimStatus.DRAFT.value, "at": to_db(now), "by": source}],
        }
        if alert_id is not None:
            doc["alert_id"] = alert_id
        try:
            self.claims.insert_one(doc)
        except DuplicateKeyError:
            # Webhook gửi trùng cùng lúc: bản kia đã ghi trước.
            return _clean(self.claims.find_one({"alert_id": alert_id, "reconciliation_id": reconciliation_id}))
        return _clean(doc)

    def create_drafts_for_carrier(
        self, carrier: str, source: str, alert_id: str | None = None, within_hours: float = 24,
    ) -> list[dict]:
        """Tạo claim nháp cho mọi chênh lệch nhận thiếu của một hãng sắp hết hạn trong `within_hours` giờ.

        Dùng khi alert Datadog chỉ cho biết hãng (tag carrier), không chỉ ra từng đơn.
        """
        now = self.now()
        resolved = set(self.claims.distinct("reconciliation_id",
                                            {"carrier": carrier, "status": {"$in": RESOLVED_STATUSES}}))
        recs = self.db[Collections.RECONCILIATIONS].find(
            {"carrier": carrier, "diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"},
             "claim_deadline_at": {"$gt": to_db(now), "$lte": to_db(now + timedelta(hours=within_hours))}},
            {"reconciliation_id": 1},
        ).sort("reconciliation_id", 1)
        return [self.create_draft(r["reconciliation_id"], source, alert_id) for r in recs
                if r["reconciliation_id"] not in resolved]

    # ── Đổi trạng thái ──
    def _move(self, claim_id: str, to: str, by: str, extra: dict | None = None, check_deadline: bool = False) -> dict:
        claim = self.get(claim_id)
        if claim is None:
            raise ClaimError(f"không có claim {claim_id!r}")
        allowed = TRANSITIONS[to]
        if claim["status"] not in allowed:
            raise ClaimError(f"{claim_id}: không chuyển được từ {claim['status']} sang {to}")
        now = self.now()
        if check_deadline and claim.get("claim_deadline_at") and as_aware(claim["claim_deadline_at"]) <= now:
            raise ClaimError(f"{claim_id}: đã quá hạn khiếu nại")
        updated = self.claims.find_one_and_update(
            {"claim_id": claim_id, "status": {"$in": list(allowed)}},
            {"$set": {"status": to, **(extra or {})}, "$push": {"history": {"status": to, "at": to_db(now), "by": by}}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:  # bị người khác đổi trạng thái trước
            raise ClaimError(f"{claim_id}: trạng thái vừa thay đổi, tải lại rồi thử lại")
        return _clean(updated)

    def approve(self, claim_id: str, approved_by: str) -> dict:
        if not approved_by or not approved_by.strip():
            raise ClaimError("phải ghi tên người duyệt")
        at = to_db(self.now())
        return self._move(claim_id, ClaimStatus.APPROVED.value, approved_by.strip(),
                          {"approved_by": approved_by.strip(), "approved_at": at}, check_deadline=True)

    def submit(self, claim_id: str, submitted_by: str) -> dict:
        return self._move(claim_id, ClaimStatus.SUBMITTED.value, submitted_by,
                          {"submitted_by": submitted_by, "submitted_at": to_db(self.now())}, check_deadline=True)

    def mark_recovered(self, claim_id: str, recovered_amount: int, by: str) -> dict:
        if type(recovered_amount) is not int or recovered_amount < 0:
            raise ClaimError("số tiền thu hồi phải là số nguyên VNĐ ≥ 0")
        return self._move(claim_id, ClaimStatus.RECOVERED.value, by,
                          {"recovered_amount": recovered_amount, "resolved_at": to_db(self.now())})

    def mark_rejected(self, claim_id: str, by: str, note: str) -> dict:
        """Hãng từ chối. Bắt buộc ghi lý do hãng đưa ra (để theo dõi và liên hệ lại)."""
        if not by or not by.strip():
            raise ClaimError("phải ghi tên người ghi nhận")
        if not note or not note.strip():
            raise ClaimError("phải ghi lý do hãng từ chối")
        return self._move(claim_id, ClaimStatus.REJECTED.value, by.strip(),
                          {"note": note.strip(), "resolved_at": to_db(self.now())})

    def add_followup(self, claim_id: str, by: str, note: str, next_contact_at: datetime | None = None) -> dict:
        """Ghi một lần trao đổi với hãng (claim đã gửi hãng hoặc bị từ chối): ai, lúc nào, nội dung, hẹn liên hệ lại."""
        if not by or not by.strip():
            raise ClaimError("phải ghi tên người theo dõi")
        if not note or not note.strip():
            raise ClaimError("phải ghi nội dung trao đổi với hãng")
        claim = self.get(claim_id)
        if claim is None:
            raise ClaimError(f"không có claim {claim_id!r}")
        if claim["status"] not in FOLLOWUP_STATUSES:
            raise ClaimError(f"{claim_id}: chỉ theo dõi claim đã gửi hãng hoặc bị từ chối (đang là {claim['status']})")
        now = to_db(self.now())
        entry = {"at": now, "by": by.strip(), "note": note.strip(),
                 "next_contact_at": to_db(next_contact_at) if next_contact_at else None}
        updated = self.claims.find_one_and_update(
            {"claim_id": claim_id, "status": {"$in": list(FOLLOWUP_STATUSES)}},
            {"$push": {"followups": entry},
             "$set": {"last_followup_at": now, "next_contact_at": entry["next_contact_at"]}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise ClaimError(f"{claim_id}: trạng thái vừa thay đổi, tải lại rồi thử lại")
        return _clean(updated)

    def expire_overdue(self) -> int:
        """Chuyển DRAFT / APPROVED đã quá hạn khiếu nại sang EXPIRED. Trả về số claim bị đổi."""
        now = to_db(self.now())
        res = self.claims.update_many(
            {"status": {"$in": list(TRANSITIONS[ClaimStatus.EXPIRED.value])}, "claim_deadline_at": {"$lte": now}},
            {"$set": {"status": ClaimStatus.EXPIRED.value},
             "$push": {"history": {"status": ClaimStatus.EXPIRED.value, "at": now, "by": "system"}}},
        )
        return res.modified_count

    # ── Đọc ──
    def get(self, claim_id: str) -> dict | None:
        return _clean(self.claims.find_one({"claim_id": claim_id}))

    def list(self, status: str | None = None, carrier: str | None = None, limit: int = 500) -> list[dict]:
        query: dict = {}
        if status:
            query["status"] = status
        if carrier:
            query["carrier"] = carrier
        return [_clean(c) for c in self.claims.find(query).sort("created_at", -1).limit(limit)]
