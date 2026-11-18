"""A reusable per-column filter control for dashboard tables.

filter_table(df, key) renders a "Filter" popover with one control per column
(multiselect of that column's values; a contains-box for high-cardinality text)
and returns the filtered frame plus a caption of what is active.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

_MAX_CHOICES = 300


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return "(blank)"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%b-%y")
    text = str(value).strip()
    return text if text and text.lower() not in ("nan", "none", "nat", "<na>") else "(blank)"


def filter_table(df: pd.DataFrame | None, key: str, label: str = "Filter",
                 columns: list[str] | None = None) -> pd.DataFrame | None:
    """Render a filter popover for df's columns; return the rows that match."""
    if df is None or df.empty:
        return df
    cols = [c for c in (columns or list(df.columns)) if c in df.columns]
    active: dict[str, object] = {}
    with st.popover(f"🔎 {label}", width="content"):
        st.caption("Pick values per column (empty = everything); text boxes match 'contains'.")
        for col in cols:
            formatted = df[col].map(_fmt)
            uniques = sorted(formatted.unique())
            widget_key = f"{key}_{col}"
            if len(uniques) <= 1:
                continue
            if len(uniques) > _MAX_CHOICES:
                text = st.text_input(f"{col} contains", key=widget_key)
                if text.strip():
                    active[col] = ("contains", text.strip().lower(), formatted)
            else:
                picked = st.multiselect(col, uniques, key=widget_key)
                if picked:
                    active[col] = ("isin", set(picked), formatted)
    if not active:
        return df
    mask = pd.Series(True, index=df.index)
    for col, (kind, needle, formatted) in active.items():
        if kind == "contains":
            mask &= formatted.str.lower().str.contains(needle, regex=False)
        else:
            mask &= formatted.isin(needle)
    shown = df[mask]
    st.caption(f"Filter active on {', '.join(f'**{c}**' for c in active)} — "
               f"{len(shown):,} of {len(df):,} rows shown.")
    return shown


def stock_month_filter(df: pd.DataFrame | None, key: str, stock_col: str = "stock",
                       month_col: str = "month") -> pd.DataFrame | None:
    """Two dropdowns — Filter by stock, Filter by month — above a table; returns the rows
    that match. Months come from month_col formatted as Jan-26, newest first."""
    if df is None or df.empty:
        return df
    c1, c2, _ = st.columns([1.2, 1, 1.8])
    out = df
    if stock_col in df.columns:
        stocks = sorted(df[stock_col].dropna().astype(str).str.strip().str.upper().unique())
        pick = c1.selectbox("Filter by stock", ["All stocks"] + stocks, key=f"{key}_stock")
        if pick != "All stocks":
            out = out[out[stock_col].astype(str).str.strip().str.upper() == pick]
    if month_col in df.columns:
        periods = pd.to_datetime(df[month_col], errors="coerce").dropna().dt.to_period("M").unique()
        labels = [p.strftime("%b-%y") for p in sorted(periods, reverse=True)]
        pick_m = c2.selectbox("Filter by month", ["All months"] + labels, key=f"{key}_month")
        if pick_m != "All months":
            out = out[pd.to_datetime(out[month_col], errors="coerce").dt.strftime("%b-%y") == pick_m]
    return out


def plain_table(df: pd.DataFrame | None, key: str | None = None, height: int | None = None,
                full_height: bool = False) -> None:
    """Read-only table without filters. full_height=True sizes it to show every row
    (no scroll bar); otherwise it caps at ~20 rows and scrolls.

    Rows whose first column says "Grand Total" (or "Total") are pinned: they render as a
    separate strip right below the table, so sorting any column never moves them."""
    if df is None or df.empty:
        st.caption("No rows.")
        return
    first = df.iloc[:, 0].astype(str).str.strip()
    total_mask = first.isin(("Grand Total", "Total"))
    totals = df[total_mask]
    body = df[~total_mask] if (total_mask.any() and not total_mask.all()) else df
    if height is None:
        rows = len(body) + 1 if full_height else min(len(body) + 1, 20)
        height = rows * 35 + 3
    st.dataframe(body, hide_index=True, width="stretch", height=height)
    if not totals.empty and not total_mask.all():
        st.dataframe(totals, hide_index=True, width="stretch",
                     height=len(totals) * 35 + 38,
                     column_config={c: st.column_config.Column(label=" ") for c in totals.columns})


# ------------------------------------------------- Excel-style header filters --
def excel_table(df: pd.DataFrame | None, key: str, height: int | None = None) -> None:
    """Read-only table with Excel-like per-column filters: every column header has a
    filter dropdown (funnel) plus a quick filter box under it; sorting and resizing work too.

    Falls back to a plain table in headless test runs (LAKSHYA_PLAIN_TABLES=1), where the
    AgGrid component cannot render.
    """
    if df is None or df.empty:
        st.caption("No rows.")
        return
    if os.environ.get("LAKSHYA_PLAIN_TABLES"):
        st.dataframe(df, hide_index=True, width="stretch",
                     height=height or min(len(df) + 1, 20) * 35 + 3)
        return
    from st_aggrid import AgGrid, GridOptionsBuilder

    frame = df.reset_index(drop=True).copy()
    for col in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[col]):
            frame[col] = frame[col].dt.strftime("%d-%b-%y")
        elif frame[col].dtype == object:
            # mixed cells (e.g. a Total row's '' inside a numeric column) break Arrow; send text
            frame[col] = frame[col].map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    gob = GridOptionsBuilder.from_dataframe(frame)
    gob.configure_default_column(filter=True, sortable=True, resizable=True,
                                 floatingFilter=True, wrapHeaderText=True, autoHeaderHeight=True)
    gob.configure_grid_options(suppressMenuHide=True)   # keep the funnel menu icon always visible
    for col in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[col]):
            gob.configure_column(col, filter="agNumberColumnFilter")
    grid_height = height or min(len(frame) + 3, 20) * 33 + 40
    AgGrid(frame, gridOptions=gob.build(), height=grid_height, theme="balham",
           fit_columns_on_grid_load=(len(frame.columns) <= 8),
           update_mode="NO_UPDATE", allow_unsafe_jscode=False, key=key)
