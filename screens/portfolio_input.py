"""Long Term Portfolio input: equity holdings by month and sector (upload or form)."""

import datetime as dt

import pandas as pd
import streamlit as st

from core import state
from core.formatting import inr
from core.parse import EXCEL_EXTENSIONS, list_sheets
from core.portfolio import (
    COMMON_SECTORS,
    PortfolioResult,
    entry_from_form,
    load_portfolio,
    portfolio_template_bytes,
)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

owner = state.user_name()
st.title("Long Term Portfolio")
st.caption(f"Portfolio owner: **{owner}**. One row per purchase: month, sector, stock, quantity, buy price. "
           "Cost and % Investment are calculated.")


def show_messages(result: PortfolioResult) -> None:
    for msg in result.errors:
        st.error(msg)
    for msg in result.warnings:
        st.warning(msg)
    for msg in result.notes:
        st.caption(msg)


def save_portfolio(entries: pd.DataFrame | None, source: str) -> None:
    state.put_frame("portfolio", entries)
    state.put_meta({"portfolio_source": source})
    state.bump("portfolio_version")


entries = state.get_frame("portfolio")

mode = st.radio("How do you want to provide holdings?", ["Upload a file", "Add entries manually"],
                horizontal=True, label_visibility="collapsed")

if mode == "Upload a file":
    c1, c2 = st.columns([3, 1])
    with c2:
        st.download_button("Download blank template (.xlsx)", portfolio_template_bytes(), "portfolio_template.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with c1:
        upload = st.file_uploader(
            "Portfolio file (.xlsx, .xlsm, .xls, .csv). Uploading replaces this owner's current holdings.",
            type=["xlsx", "xlsm", "xls", "csv"], key="portfolio_upload",
            help="Columns: MONTH, SECTORS, STOCK, QTY, BUY, COST, GIFT AMOUNT. Months may be dates or text like Jul-23.",
        )
    if upload is not None:
        sheet = 0
        if upload.name.lower().endswith(EXCEL_EXTENSIONS):
            try:
                sheets = list_sheets(upload)
            except Exception as exc:
                sheets = []
                st.error(f"Could not open the workbook: {exc}")
            if len(sheets) > 1:
                sheet = st.selectbox("Sheet", sheets, index=0)
        result = load_portfolio(upload, upload.name, sheet)
        show_messages(result)
        if result.ok:
            fingerprint = f"{upload.name}:{upload.size}:{sheet}"
            if st.session_state.get("last_portfolio_upload") != fingerprint:
                save_portfolio(result.entries, upload.name)
                st.session_state["last_portfolio_upload"] = fingerprint
                entries = result.entries
            st.success(f"Loaded {len(result.entries):,} holdings worth {inr(result.entries['cost'].sum(), prefix='₹')} from {upload.name}.")
            with st.expander("Preview and column mapping"):
                st.dataframe(result.entries.head(20), width="stretch", hide_index=True)
                st.dataframe(pd.DataFrame({"Your header": list(result.mapping), "Used as": list(result.mapping.values())}),
                             width="stretch", hide_index=True)
else:
    known_sectors = sorted(set(COMMON_SECTORS) | (set(entries["sector"].dropna()) if entries is not None else set()))
    with st.form("add_entry", clear_on_submit=True, border=True):
        a, b, c = st.columns(3)
        today = dt.date.today()
        m1, m2 = a.columns([3, 2])
        month_name = m1.selectbox("Purchase month", MONTH_NAMES, index=today.month - 1)
        year = m2.selectbox("Year", list(range(today.year, 1999, -1)), index=0)
        month = dt.date(year, MONTH_NAMES.index(month_name) + 1, 1)
        sector = b.selectbox("Sector", known_sectors + ["Other"], index=known_sectors.index("OTHER") if "OTHER" in known_sectors else 0)
        other_sector = b.text_input("If Other, type the sector", placeholder="e.g. DEFENCE")
        stock = c.text_input("Stock", placeholder="e.g. DMART").strip().upper()
        a, b, c = st.columns(3)
        qty = a.number_input("Qty", min_value=0, step=1, value=0)
        buy = b.number_input("Buy price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
        gift = c.number_input("Gift amount (₹, optional)", min_value=0.0, step=1000.0, value=0.0,
                              help="Fill if these shares were gifted; usually the cost value.")
        if qty and buy:
            st.caption(f"Cost: {inr(qty * buy, prefix='₹')}")
        submitted = st.form_submit_button("Add entry", type="primary")

    if submitted:
        problems = []
        if not stock:
            problems.append("Stock is required.")
        if qty <= 0 or buy <= 0:
            problems.append("Qty and buy price must be greater than 0.")
        chosen_sector = other_sector.strip().upper() if sector == "Other" and other_sector.strip() else sector
        if chosen_sector == "Other":
            problems.append("Type the sector name next to 'Other'.")
        if problems:
            for p in problems:
                st.error(p)
        else:
            result = entry_from_form(month, chosen_sector, stock, qty, buy, gift)
            show_messages(result)
            if result.ok:
                combined = pd.concat([entries, result.entries], ignore_index=True) if entries is not None else result.entries
                save_portfolio(combined, "manual entry")
                entries = combined
                st.success(f"Added {stock}: {qty} × {buy:,.2f} = {inr(qty * buy, prefix='₹')}")

if entries is not None and not entries.empty:
    total = float(entries["cost"].sum())
    with st.expander(f"Holdings saved for {owner} ({len(entries):,} entries, {inr(total, prefix='₹')} invested)",
                     expanded=(mode == "Add entries manually")):
        view = entries.copy()
        view["month"] = view["month"].dt.strftime("%b-%y")
        view["% Investment"] = (view["cost"] / total * 100) if total else pd.NA
        view = view.rename(columns={"month": "Month", "sector": "Sector", "stock": "Stock", "qty": "Qty",
                                    "buy": "Buy", "cost": "Cost", "gift": "Gift"})
        view.insert(0, "Remove", False)
        edited = st.data_editor(
            view, hide_index=True, width="stretch", height=min(len(view) + 1, 12) * 35 + 3,
            disabled=[c for c in view.columns if c != "Remove"],
            key=f"portfolio_list_{state.version('portfolio_version')}",
            column_config={"Remove": st.column_config.CheckboxColumn(help="Tick rows to remove"),
                           "Buy": st.column_config.NumberColumn(format="%.2f"),
                           "Cost": st.column_config.NumberColumn(format="%.0f"),
                           "Gift": st.column_config.NumberColumn(format="%.0f"),
                           "% Investment": st.column_config.NumberColumn(format="%.2f")},
        )
        r1, r2 = st.columns([1, 3])
        if r1.button("Remove selected", key="portfolio_remove"):
            keep = ~edited["Remove"].fillna(False).astype(bool).to_numpy()
            if keep.all():
                st.info("Tick at least one row first.")
            else:
                remaining = entries[keep].reset_index(drop=True)
                save_portfolio(remaining if not remaining.empty else None, state.get_meta().get("portfolio_source", ""))
                st.rerun()
        confirm = r2.checkbox("I want to delete every holding for this owner", key="portfolio_confirm")
        if confirm and r2.button("Delete all holdings", key="portfolio_delete_all"):
            save_portfolio(None, "")
            st.rerun()
else:
    st.info("No holdings yet for this owner. Upload a file or add entries with the form.")

st.page_link("screens/reports.py", label="Go to Reports", icon="📊")
