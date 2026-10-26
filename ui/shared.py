"""[B] Phần dùng chung của các trang Streamlit: kết nối Mongo, giờ hiện tại, bộ lọc, cột tiền, biểu đồ,
thông báo sau thao tác và log thao tác phía máy chủ.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

import altair as alt
import streamlit as st

from common.db import get_db
from core import queries
from core.claims import ClaimService
from core.periods import as_aware
from ui import view

log = logging.getLogger("shipaudit.ui")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def db():
    return get_db()


def now() -> datetime:
    """Giờ hiện tại. Đặt SHIPAUDIT_NOW (ISO) để xem dữ liệu seed tại một thời điểm cố định (demo, test)."""
    fixed = os.getenv("SHIPAUDIT_NOW")
    return as_aware(fixed) if fixed else datetime.now(timezone.utc)


def claim_service() -> ClaimService:
    return ClaimService(db(), now=now)


def carrier_names() -> dict[str, str]:
    return {c["carrier"]: c.get("display_name") or c["carrier"] for c in queries.carriers(db())}


# ── Log thao tác (phía máy chủ, không phải RUM) ──
def session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid.uuid4().hex[:12]
    return st.session_state["session_id"]


def track(event: str, **fields) -> None:
    """Một dòng log JSON cho thao tác chính trên giao diện, kèm mã phiên."""
    log.info(json.dumps({"service": "shipaudit-ui", "event": event, "session": session_id(), **fields},
                        ensure_ascii=False, default=str))


# ── Khung trang ──
def header(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)
    track("page_view", page=title)
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)


def topbar(title: str, sub: str = "", container=st, **kw) -> None:
    """Đầu trang theo bản thiết kế (view.topbar), kèm log xem trang và thông báo sau thao tác."""
    container.html(view.topbar(title, sub, **kw))
    track("page_view", page=title)
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)


def flash(msg: str) -> None:
    """Thông báo hiện ở lần chạy lại kế tiếp (sau st.rerun)."""
    st.session_state["flash"] = msg


def carrier_select(names: dict[str, str], key: str, container=st) -> str | None:
    return container.selectbox("Hãng", [None, *sorted(names)], key=key,
                               format_func=lambda c: "Tất cả các hãng" if c is None else names[c])


def money(label: str | None = None, help: str | None = None):
    return st.column_config.NumberColumn(label, format="localized", help=help)


def money_columns(*cols: str) -> dict:
    return {c: money(f"{c} (₫)") for c in cols}


def vnd_axis(title: str) -> alt.Axis:
    """Trục số tiền ghi dấu chấm ngăn hàng nghìn (12.000.000) như phần còn lại của giao diện."""
    return alt.Axis(title=title, format=",d", labelExpr="replace(datum.label, /,/g, '.')")


def carrier_scale(names: dict[str, str]) -> alt.Scale:
    domain, colors = view.carrier_colors(names)
    return alt.Scale(domain=domain, range=colors)
