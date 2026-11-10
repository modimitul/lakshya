"""Monthly SIP plans that auto-post Investment Book purchase rows.

A plan says: fund, sector, amount (₹ per instalment), day of month, start month,
active. Each visit to the Investment Book or the Investments dashboard posts any
instalments that have fallen due since the last visit (one BUY row per month,
Cost = amount, Qty/price left blank because the NAV is not known here). The
`last_applied` month on the plan makes posting idempotent.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd

SIP_COLUMNS = ["fund", "sector", "amount", "day", "start_month", "active", "last_applied"]
SIP_SOURCE = "SIP"


def empty_sips() -> pd.DataFrame:
    return pd.DataFrame({
        "fund": pd.Series(dtype="string"),
        "sector": pd.Series(dtype="string"),
        "amount": pd.Series(dtype="float64"),
        "day": pd.Series(dtype="float64"),
        "start_month": pd.Series(dtype="datetime64[ns]"),
        "active": pd.Series(dtype="float64"),       # stored as 0/1 for SQL friendliness
        "last_applied": pd.Series(dtype="datetime64[ns]"),
    })


def normalise_sips(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Coerce a SIP grid (edited or loaded) to the canonical shape; drop rows without a fund."""
    if frame is None or frame.empty:
        return empty_sips()
    out = frame.copy()
    for col in SIP_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out["fund"] = out["fund"].astype("string").str.strip().str.upper().replace("", pd.NA)
    out = out.dropna(subset=["fund"])
    out["sector"] = out["sector"].astype("string").str.strip().str.upper().replace("", pd.NA).fillna("MUTUAL FUND")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out["day"] = pd.to_numeric(out["day"], errors="coerce").fillna(1).clip(1, 31)
    out["start_month"] = pd.to_datetime(out["start_month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    out["last_applied"] = pd.to_datetime(out["last_applied"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    active = out["active"]
    out["active"] = active.map(lambda v: 1.0 if str(v).strip().lower() in ("1", "1.0", "true", "yes", "active") else 0.0)
    return out[SIP_COLUMNS].reset_index(drop=True)


def _due_date(month_start: pd.Timestamp, day: int) -> dt.date:
    last = calendar.monthrange(month_start.year, month_start.month)[1]
    return dt.date(month_start.year, month_start.month, min(int(day), last))


def next_due(plan: pd.Series, today: dt.date | None = None) -> dt.date | None:
    """The next instalment date for an active plan (None for paused/invalid plans)."""
    today = today or dt.date.today()
    if not plan.get("active") or pd.isna(plan.get("amount")) or plan["amount"] <= 0:
        return None
    months = due_months(plan, today)
    if months:
        return _due_date(months[0], int(plan["day"]))
    cursor = pd.Timestamp(today.replace(day=1))
    start = plan.get("start_month")
    if pd.notna(start) and start > cursor:
        cursor = start
    due = _due_date(cursor, int(plan["day"]))
    if due <= today or (pd.notna(plan.get("last_applied")) and plan["last_applied"] >= cursor):
        cursor = (cursor + pd.offsets.MonthBegin(1)).normalize()
        due = _due_date(cursor, int(plan["day"]))
    return due


def due_months(plan: pd.Series, today: dt.date | None = None) -> list[pd.Timestamp]:
    """Month-starts whose instalment date has passed and is not yet applied."""
    today = today or dt.date.today()
    if not plan.get("active") or pd.isna(plan.get("amount")) or plan["amount"] <= 0:
        return []
    start = plan.get("start_month")
    if pd.isna(start):
        start = pd.Timestamp(today.replace(day=1))
    cursor = start
    if pd.notna(plan.get("last_applied")) and plan["last_applied"] >= cursor:
        cursor = (plan["last_applied"] + pd.offsets.MonthBegin(1)).normalize()
    months = []
    current = pd.Timestamp(today.replace(day=1))
    while cursor <= current:
        if _due_date(cursor, int(plan["day"])) <= today:
            months.append(cursor)
        cursor = (cursor + pd.offsets.MonthBegin(1)).normalize()
    return months


def apply_due(sips: pd.DataFrame, today: dt.date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Post every due instalment. Returns (new entry rows, updated sips, count)."""
    today = today or dt.date.today()
    sips = normalise_sips(sips)
    rows = []
    for idx, plan in sips.iterrows():
        months = due_months(plan, today)
        for m in months:
            rows.append({
                "month": m, "sector": plan["sector"], "stock": plan["fund"],
                "qty": pd.NA, "buy": pd.NA, "cost": float(plan["amount"]),
                "gift": 0.0, "charges": 0.0, "side": "buy", "source_sheet": SIP_SOURCE,
            })
        if months:
            sips.at[idx, "last_applied"] = months[-1]
    new_entries = pd.DataFrame(rows)
    if not new_entries.empty:
        new_entries["month"] = pd.to_datetime(new_entries["month"])
        for col in ("sector", "stock", "side", "source_sheet"):
            new_entries[col] = new_entries[col].astype("string")
    return new_entries, sips, len(rows)


def run_autopost() -> int:
    """Streamlit-side: post due instalments for the current owner; returns rows added."""
    from . import state

    sips = state.get_frame("sips")
    if sips is None or sips.empty:
        return 0
    new_entries, updated, n = apply_due(sips)
    if not n:
        return 0
    entries = state.get_frame("portfolio")
    combined = pd.concat([entries, new_entries], ignore_index=True) if entries is not None and not entries.empty else new_entries
    state.put_frame("portfolio", combined)
    state.put_frame("sips", updated)
    return n
