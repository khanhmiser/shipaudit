"""[B] Thời gian và kỳ đối soát.

- Kỳ đối soát là tuần ISO theo giờ Việt Nam, ghi dạng "2026-W42" (trường `period`).
- Đơn thuộc kỳ P nếu hạn trả tiền thu hộ (delivered_at + cod_payout_days) rơi vào tuần P.
  Đơn xuất hiện trong bảng kê của kỳ sau kỳ đó là chuyển chậm (LATE_PAYOUT).
- Trong Mongo lưu datetime UTC (pymongo đọc ra naive UTC); trong code dùng datetime có múi giờ.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))


def as_aware(value: datetime | str) -> datetime:
    """Chuỗi ISO hoặc datetime → datetime có múi giờ. Naive được coi là UTC (cách pymongo trả về)."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def to_db(value: datetime | str) -> datetime:
    """Datetime để ghi/truy vấn Mongo: naive UTC."""
    return as_aware(value).astimezone(timezone.utc).replace(tzinfo=None)


def to_iso(value: datetime | str) -> str:
    return as_aware(value).astimezone(VN_TZ).isoformat()


def period_of(value: datetime | str) -> str:
    y, w, _ = as_aware(value).astimezone(VN_TZ).isocalendar()
    return f"{y}-W{w:02d}"


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """[đầu tuần, đầu tuần sau) theo giờ Việt Nam."""
    y, w = period.split("-W")
    start = datetime.combine(date.fromisocalendar(int(y), int(w), 1), time(0), tzinfo=VN_TZ)
    return start, start + timedelta(days=7)


def shift_period(period: str, weeks: int) -> str:
    return period_of(period_bounds(period)[0] + timedelta(weeks=weeks))
