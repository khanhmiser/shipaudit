"""[B] Đọc carrier_rules (dữ liệu trong Mongo) thành đối tượng dùng cho engine.

Mọi con số (cước, phụ phí, hạn) nằm trong document `carrier_rules`; file này chỉ có
cách đọc và cách áp dụng. Định dạng document mô tả ở generator/carriers/params.py.
Mỗi hãng có thể có nhiều `version`; mặc định dùng version lớn nhất.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from common.enums import Collections, OrderStatus
from core.money import ROUNDING_MODES, apply_bp
from core.periods import period_bounds, period_of

REQUIRED_FIELDS = ("carrier", "dim_weight_divisor", "rate_table", "cod_payout_days", "claim_window_hours")
SURCHARGE_FIELDS = {
    "insurance": ("rate_bp", "min_declared_value"),
    "return": ("rate_bp", "fixed"),
    "storage": ("per_day", "free_days"),
    "address_change": ("fixed",),
    "inspection": ("fixed",),
}
# Phụ phí tính theo tỷ lệ, có thể khai báo round_unit (bội số đồng) và round_mode (half_up | half_even).
ROUNDED_SURCHARGES = ("insurance", "return")
POLICY_FLAGS = ("collect_cod", "charge_shipping", "charge_return")
# Mốc tính hạn khiếu nại: lúc doanh nghiệp nhận bảng kê, hoặc lúc đơn được giao (như Luật Bưu chính 2010, Điều 38).
DEADLINE_ANCHORS = ("statement_received_at", "delivered_at")
DEFAULT_DEADLINE_ANCHOR = "statement_received_at"
# Cách xác định kỳ bảng kê chứa một đơn:
# - delivered_plus_days: kỳ chứa hạn trả tiền thu hộ (ngày giao + cod_payout_days). Mặc định.
# - period_end: bảng kê theo kỳ giao hàng; hãng trả tiền sau cuối kỳ giao cod_payout_days ngày.
PAYOUT_BASES = ("delivered_plus_days", "period_end")
DEFAULT_PAYOUT_BASIS = "delivered_plus_days"


def delivery_window(period: str, cod_payout_days: int, payout_basis: str = DEFAULT_PAYOUT_BASIS) -> tuple[datetime, datetime]:
    """[từ, đến) ngày giao của các đơn thuộc bảng kê kỳ `period` (dùng cho pipeline, không cần dựng CarrierRule)."""
    start, end = period_bounds(period)
    if payout_basis == "period_end":
        return start, end
    shift = timedelta(days=cod_payout_days)
    return start - shift, end - shift


@dataclass(frozen=True)
class StatusPolicy:
    """Khoản nào được tính cho một trạng thái đơn (xem status_policy trong params)."""

    collect_cod: bool
    charge_shipping: bool
    charge_return: bool


class RuleError(ValueError):
    """Document carrier_rules sai định dạng hoặc thiếu dữ liệu cần cho một phép tính."""


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    # bool là int trong Python, float thì cấm (tiền phải là số nguyên).
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuleError(f"{name} phải là số nguyên, nhận {value!r}")
    if value < minimum:
        raise RuleError(f"{name} phải ≥ {minimum}, nhận {value}")
    return value


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


@dataclass(frozen=True)
class Bracket:
    max_weight_g: int
    fee: int


@dataclass(frozen=True)
class RegionRate:
    region: str
    brackets: tuple[Bracket, ...]
    extra_step_g: int
    extra_fee: int

    def fee_for(self, weight_g: int) -> int:
        for b in self.brackets:
            if weight_g <= b.max_weight_g:
                return b.fee
        last = self.brackets[-1]
        steps = _ceil_div(weight_g - last.max_weight_g, self.extra_step_g)
        return last.fee + steps * self.extra_fee


@dataclass(frozen=True)
class CarrierRule:
    carrier: str
    version: int
    display_name: str
    dim_weight_divisor: int
    rates: dict[str, RegionRate]
    surcharges: dict[str, dict[str, int]]
    transfer_fee_amount: int
    transfer_fee_cod_only: bool
    cod_payout_days: int
    claim_window_hours: int
    status_policy: dict[str, StatusPolicy]
    claim_deadline_anchor: str = DEFAULT_DEADLINE_ANCHOR
    payout_basis: str = DEFAULT_PAYOUT_BASIS
    # Vùng tính phí hoàn cố định thay cho fixed + rate_bp (vd nội tỉnh của Carrier A).
    return_flat_by_region: dict[str, int] = field(default_factory=dict)
    # Làm tròn phí tính theo tỷ lệ, theo từng phụ phí (insurance, return): (bội số đồng, kiểu làm tròn).
    rounding: dict[str, tuple[int, str]] = field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: dict) -> CarrierRule:
        missing = [f for f in REQUIRED_FIELDS if f not in doc]
        if missing:
            raise RuleError(f"carrier_rules thiếu trường {missing}")
        carrier = doc["carrier"]
        if not isinstance(carrier, str) or not carrier:
            raise RuleError("carrier phải là chuỗi khác rỗng")

        rates: dict[str, RegionRate] = {}
        for entry in doc["rate_table"]:
            region = entry.get("region")
            if not region or region in rates:
                raise RuleError(f"{carrier}: vùng thiếu tên hoặc bị lặp ({region!r})")
            raw = entry.get("brackets") or []
            if not raw:
                raise RuleError(f"{carrier}/{region}: bảng mốc khối lượng rỗng")
            brackets = tuple(
                Bracket(_int(b["max_weight_g"], "max_weight_g", minimum=1), _int(b["fee"], "fee"))
                for b in raw
            )
            limits = [b.max_weight_g for b in brackets]
            if limits != sorted(set(limits)):
                raise RuleError(f"{carrier}/{region}: mốc khối lượng phải tăng dần, không trùng")
            rates[region] = RegionRate(
                region=region,
                brackets=brackets,
                extra_step_g=_int(entry.get("extra_step_g"), "extra_step_g", minimum=1),
                extra_fee=_int(entry.get("extra_fee"), "extra_fee"),
            )
        if not rates:
            raise RuleError(f"{carrier}: rate_table rỗng")

        surcharges: dict[str, dict[str, int]] = {}
        raw_surcharges = doc.get("surcharges") or {}
        for name, fields in SURCHARGE_FIELDS.items():
            item = raw_surcharges.get(name) or {}
            surcharges[name] = {f: _int(item.get(f, 0), f"surcharges.{name}.{f}") for f in fields}

        status_policy: dict[str, StatusPolicy] = {}
        valid_statuses = {s.value for s in OrderStatus}
        for status, flags in (doc.get("status_policy") or {}).items():
            if status not in valid_statuses:
                raise RuleError(f"{carrier}: status_policy có trạng thái lạ {status!r}")
            for f in POLICY_FLAGS:
                if not isinstance(flags.get(f), bool):
                    raise RuleError(f"{carrier}: status_policy.{status}.{f} phải là true/false")
            status_policy[status] = StatusPolicy(**{f: flags[f] for f in POLICY_FLAGS})

        anchor = doc.get("claim_deadline_anchor") or DEFAULT_DEADLINE_ANCHOR
        if anchor not in DEADLINE_ANCHORS:
            raise RuleError(f"{carrier}: claim_deadline_anchor phải là một trong {DEADLINE_ANCHORS}, nhận {anchor!r}")
        basis = doc.get("payout_basis") or DEFAULT_PAYOUT_BASIS
        if basis not in PAYOUT_BASES:
            raise RuleError(f"{carrier}: payout_basis phải là một trong {PAYOUT_BASES}, nhận {basis!r}")
        flat = {
            region: _int(fee, f"surcharges.return.flat_by_region.{region}")
            for region, fee in ((raw_surcharges.get("return") or {}).get("flat_by_region") or {}).items()
        }
        rounding: dict[str, tuple[int, str]] = {}
        for name in ROUNDED_SURCHARGES:
            item = raw_surcharges.get(name) or {}
            mode = item.get("round_mode", "half_up")
            if mode not in ROUNDING_MODES:
                raise RuleError(f"{carrier}: surcharges.{name}.round_mode phải là một trong {sorted(ROUNDING_MODES)}, nhận {mode!r}")
            rounding[name] = (_int(item.get("round_unit", 1), f"surcharges.{name}.round_unit", minimum=1), mode)
        unknown = set(flat) - set(rates)
        if unknown:
            raise RuleError(f"{carrier}: surcharges.return.flat_by_region có vùng lạ {sorted(unknown)}")

        return cls(
            carrier=carrier,
            version=_int(doc.get("version", 1), "version", minimum=1),
            display_name=doc.get("display_name") or carrier,
            dim_weight_divisor=_int(doc["dim_weight_divisor"], "dim_weight_divisor", minimum=1),
            rates=rates,
            surcharges=surcharges,
            transfer_fee_amount=_int(doc.get("transfer_fee", 0), "transfer_fee"),
            transfer_fee_cod_only=bool(doc.get("transfer_fee_cod_only", True)),
            cod_payout_days=_int(doc["cod_payout_days"], "cod_payout_days"),
            claim_window_hours=_int(doc["claim_window_hours"], "claim_window_hours", minimum=1),
            status_policy=status_policy,
            claim_deadline_anchor=anchor,
            payout_basis=basis,
            return_flat_by_region=flat,
            rounding=rounding,
        )

    def policy_for(self, status: str) -> StatusPolicy:
        status = getattr(status, "value", status)
        if status not in self.status_policy:
            raise RuleError(f"{self.carrier}: chưa có status_policy cho trạng thái {status!r}")
        return self.status_policy[status]

    # ── Khối lượng và cước ──
    def dim_weight_g(self, length_cm: int = 0, width_cm: int = 0, height_cm: int = 0) -> int:
        """Khối lượng quy đổi (gram), làm tròn lên."""
        return _ceil_div(length_cm * width_cm * height_cm * 1000, self.dim_weight_divisor)

    def chargeable_weight_g(self, weight_g: int, length_cm: int = 0, width_cm: int = 0, height_cm: int = 0) -> int:
        """Khối lượng tính cước = max(khối lượng thật, khối lượng quy đổi)."""
        return max(weight_g, self.dim_weight_g(length_cm, width_cm, height_cm))

    def shipping_fee(self, region: str, chargeable_weight_g: int) -> int:
        if region not in self.rates:
            raise RuleError(f"{self.carrier}: không có bảng cước cho vùng {region!r}")
        return self.rates[region].fee_for(chargeable_weight_g)

    # ── Phụ phí ──
    def insurance_fee(self, declared_value: int) -> int:
        s = self.surcharges["insurance"]
        if declared_value <= 0 or declared_value < s["min_declared_value"]:
            return 0
        return apply_bp(declared_value, s["rate_bp"], *self.rounding["insurance"])

    def return_shipping_fee(self, shipping_fee: int, region: str | None = None) -> int:
        if region in self.return_flat_by_region:
            return self.return_flat_by_region[region]
        s = self.surcharges["return"]
        return s["fixed"] + apply_bp(shipping_fee, s["rate_bp"], *self.rounding["return"])

    def storage_fee(self, storage_days: int) -> int:
        s = self.surcharges["storage"]
        return max(0, storage_days - s["free_days"]) * s["per_day"]

    def address_change_fee(self, times: int = 1) -> int:
        return times * self.surcharges["address_change"]["fixed"]

    def inspection_fee(self, times: int = 1) -> int:
        return times * self.surcharges["inspection"]["fixed"]

    def transfer_fee(self, cod_amount: int) -> int:
        if self.transfer_fee_cod_only and cod_amount <= 0:
            return 0
        return self.transfer_fee_amount

    # ── Hạn ──
    def payout_due(self, delivered_at: datetime) -> datetime:
        """Hạn hãng phải chuyển tiền thu hộ: giao + cod_payout_days, hoặc cuối kỳ giao + cod_payout_days."""
        if self.payout_basis == "period_end":
            return period_bounds(period_of(delivered_at))[1] + timedelta(days=self.cod_payout_days)
        return delivered_at + timedelta(days=self.cod_payout_days)

    def statement_period(self, delivered_at: datetime) -> str:
        """Kỳ của bảng kê đáng ra phải có đơn này. Xuất hiện ở kỳ sau kỳ này là chuyển chậm (LATE_PAYOUT)."""
        if self.payout_basis == "period_end":
            return period_of(delivered_at)
        return period_of(self.payout_due(delivered_at))

    def delivery_window(self, period: str) -> tuple[datetime, datetime]:
        """[từ, đến) ngày giao của các đơn thuộc bảng kê kỳ `period`."""
        return delivery_window(period, self.cod_payout_days, self.payout_basis)

    def claim_deadline(self, start: datetime) -> datetime:
        """Hạn khiếu nại tính từ `start` (mốc đã chọn theo claim_deadline_anchor)."""
        return start + timedelta(hours=self.claim_window_hours)

    def claim_deadline_for(self, received_at: datetime, delivered_at: datetime | None = None) -> datetime:
        """Hạn khiếu nại của một khoản theo mốc của hãng. Thiếu ngày giao thì tính từ lúc nhận bảng kê."""
        if self.claim_deadline_anchor == "delivered_at" and delivered_at is not None:
            return self.claim_deadline(delivered_at)
        return self.claim_deadline(received_at)

    def claim_hours_left(self, start: datetime, now: datetime) -> float:
        return (self.claim_deadline(start) - now).total_seconds() / 3600


# ── Đọc từ dữ liệu ──
def rules_from_documents(docs: Iterable[dict]) -> dict[str, CarrierRule]:
    """Dựng {carrier: CarrierRule}, mỗi hãng lấy version lớn nhất."""
    out: dict[str, CarrierRule] = {}
    for doc in docs:
        rule = CarrierRule.from_doc(doc)
        current = out.get(rule.carrier)
        if current is None or rule.version > current.version:
            out[rule.carrier] = rule
    return out


def load_rules(db: Any) -> dict[str, CarrierRule]:
    """Đọc toàn bộ carrier_rules trong Mongo."""
    return rules_from_documents(db[Collections.CARRIER_RULES].find({}, {"_id": 0}))


def load_rule(db: Any, carrier: str, version: int | None = None) -> CarrierRule:
    query: dict[str, Any] = {"carrier": carrier}
    if version is not None:
        query["version"] = version
    rules = rules_from_documents(db[Collections.CARRIER_RULES].find(query, {"_id": 0}))
    if carrier not in rules:
        raise RuleError(f"không có carrier_rules cho {carrier!r}" + (f" version {version}" if version else ""))
    return rules[carrier]


def upsert_rules(db: Any, docs: Iterable[dict]) -> int:
    """Ghi carrier_rules, idempotent theo (carrier, version). Kiểm tra định dạng trước khi ghi."""
    coll = db[Collections.CARRIER_RULES]
    n = 0
    for doc in docs:
        CarrierRule.from_doc(doc)
        coll.replace_one({"carrier": doc["carrier"], "version": doc.get("version", 1)}, doc, upsert=True)
        n += 1
    return n
