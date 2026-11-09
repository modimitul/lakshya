"""Trading Book: trades (upload or form), monthly capital, annual ROI vs benchmarks."""

import datetime as dt

import pandas as pd
import streamlit as st

from core import state
from core.formatting import inr
from core.metrics import capital_frame, monthly_summary, months_in
from core.parse import (
    COMMON_TRADE_TYPES,
    ParseResult,
    dedupe_trades,
    load_capital_frame,
    load_trades_workbook,
    looks_like_trade_header,
    template_bytes,
    trade_from_form,
)

owner = state.user_name()
st.title("Trading Book")
st.caption(f"Portfolio owner: **{owner}**. Everything on this screen is saved for {owner} as you go.")


def show_messages(result: ParseResult) -> None:
    for msg in result.errors:
        st.error(msg)
    for msg in result.warnings:
        st.warning(msg)
    for msg in result.notes:
        st.caption(msg)


def save_trades(trades: pd.DataFrame | None, excluded: pd.DataFrame | None, source: str) -> None:
    state.put_frame("trades", trades)
    state.put_frame("excluded", excluded)
    state.put_meta({"trades_source": source})
    state.bump("capital_version")


trades = state.get_frame("trades")

# ---------------------------------------------------------------- trades ----
st.subheader("1. Trades")
mode = st.radio("How do you want to provide trades?", ["Upload a file", "Add trades manually"],
                horizontal=True, label_visibility="collapsed")

if mode == "Upload a file":
    c1, c2 = st.columns([3, 1])
    with c2:
        st.download_button("Download blank template (.xlsx)", template_bytes(), "trades_template.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with c1:
        upload = st.file_uploader(
            "Trade log (.xlsx, .xlsm, .xls, .csv). A workbook with one tab per year is fine: pick the tabs below.",
            type=["xlsx", "xlsm", "xls", "csv"],
            help="Headers are matched by name, so extra columns are fine. Needed per tab: Month or Buy Date, "
                 "and Gross Profit (or Profit/Loss, or Qty + Buy + Sell).",
        )
    wb = state.cached_workbook(upload, "trade_wb") if upload is not None else None
    if wb:
        sheets = wb.sheet_names
        chosen = sheets
        if len(sheets) > 1:
            detected = [sh for sh in sheets if looks_like_trade_header(wb.headers(sh))]
            chosen = st.multiselect("Tabs to import", sheets, default=detected or sheets,
                                    help="Tabs that look like trade logs are pre-selected. Untick summary or pivot tabs.")
        how = st.radio("How to import", ["Replace this owner's trades", "Add to existing trades (duplicates skipped)"],
                       horizontal=True, index=0 if trades is None or trades.empty else 1)
        if st.button("Import", type="primary", disabled=not chosen):
            with st.spinner("Importing …"):
                result = load_trades_workbook(wb, chosen)
            show_messages(result)
            if result.ok:
                incoming = result.trades
                dropped = 0
                if how.startswith("Add") and trades is not None and not trades.empty:
                    merged, dropped = dedupe_trades(pd.concat([trades, incoming], ignore_index=True))
                    added = len(merged) - len(trades)
                    old_excluded = state.get_frame("excluded")
                    excluded = pd.concat([x for x in (old_excluded, result.excluded) if x is not None and not x.empty], ignore_index=True) if (old_excluded is not None and not old_excluded.empty) or not result.excluded.empty else result.excluded
                    save_trades(merged, excluded, f"{state.get_meta().get('trades_source', '')} + {upload.name}".strip(" +"))
                    trades = merged
                    st.success(f"Added {added:,} new trades from {upload.name} ({dropped:,} duplicates skipped). "
                               f"{len(trades):,} trades across {len(months_in(trades))} months in total.")
                else:
                    incoming, dropped = dedupe_trades(incoming)
                    save_trades(incoming, result.excluded, upload.name)
                    trades = incoming
                    st.success(f"Imported {len(trades):,} trades across {len(months_in(trades))} months from {upload.name}"
                               + (f" ({dropped:,} duplicates within the file skipped)." if dropped else "."))
                with st.expander("Per-tab summary and column mapping"):
                    for note in result.notes:
                        st.write(note)
                    st.dataframe(pd.DataFrame({"Your header": list(result.mapping), "Used as": list(result.mapping.values())}),
                                 width="stretch", hide_index=True)
                if not result.excluded.empty:
                    with st.expander(f"Excluded rows ({len(result.excluded)})"):
                        st.dataframe(result.excluded, width="stretch", hide_index=True)
else:
    st.caption("Fill in one trade and press **Add trade**. P&L, gross profit, investment and ROI are calculated for you.")
    with st.form("add_trade", clear_on_submit=True, border=True):
        a, b, c = st.columns(3)
        buy_date = a.date_input("Buy date", value=dt.date.today(), format="DD-MM-YYYY")
        stock = b.text_input("Stock", placeholder="e.g. TCS").strip().upper()
        trade_type = c.selectbox("Type", COMMON_TRADE_TYPES + ["Other"])
        other_type = c.text_input("If Other, type it here", placeholder="e.g. Iron Condor")
        a, b, c = st.columns(3)
        qty = a.number_input("Qty", min_value=0, step=1, value=0)
        buy = b.number_input("Buy price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
        sell = c.number_input("Sell price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
        a, b, c, d = st.columns(4)
        sale_date = a.date_input("Sale date (optional)", value=None, format="DD-MM-YYYY")
        brokerage = b.number_input("Brokerage & charges", min_value=0.0, step=1.0, value=0.0, format="%.2f")
        margin = c.number_input("Margin per lot", min_value=0, step=1000, value=0)
        lot = d.number_input("Lots", min_value=0, step=1, value=1)
        strike = st.number_input("Strike price (optional)", min_value=0.0, step=50.0, value=0.0)
        submitted = st.form_submit_button("Add trade", type="primary")

    if submitted:
        problems = []
        if not stock:
            problems.append("Stock is required.")
        if qty <= 0:
            problems.append("Qty must be greater than 0.")
        if buy <= 0 and sell <= 0:
            problems.append("Enter a buy and a sell price.")
        if problems:
            for p in problems:
                st.error(p)
        else:
            result = trade_from_form(
                buy_date=buy_date, stock=stock,
                type=other_type.strip() if trade_type == "Other" and other_type.strip() else trade_type,
                strike=strike or None, qty=qty, buy=buy, sale_date=sale_date, sell=sell,
                brokerage=brokerage, margin=margin or None, lot=lot or None,
            )
            show_messages(result)
            if result.ok:
                combined = pd.concat([trades, result.trades], ignore_index=True) if trades is not None else result.trades
                save_trades(combined, state.get_frame("excluded"), "manual entry")
                trades = combined
                row = result.trades.iloc[0]
                st.success(f"Added {stock}: gross profit {inr(row['gross_profit'], prefix='₹')}"
                           + (f", ROI {row['roi']:.2f}%" if pd.notna(row.get("roi")) else ""))

# Review / delete list
if trades is not None and not trades.empty:
    with st.expander(f"Trades saved for {owner} ({len(trades):,})", expanded=(mode == "Add trades manually")):
        show_cols = [c for c in ("buy_date", "month", "stock", "type", "qty", "buy", "sell", "brokerage", "gross_profit", "roi") if c in trades]
        view = trades[show_cols].copy()
        for col in ("buy_date", "month"):
            if col in view:
                view[col] = view[col].dt.strftime("%d-%b-%y" if col == "buy_date" else "%b-%y")
        view.insert(0, "Remove", False)
        edited = st.data_editor(
            view, hide_index=True, width="stretch", height=min(len(view) + 1, 12) * 35 + 3,
            disabled=show_cols, key=f"trade_list_{state.version('capital_version')}",
            column_config={"Remove": st.column_config.CheckboxColumn(help="Tick rows to remove"),
                           "buy_date": "Buy date", "month": "Month", "stock": "Stock", "type": "Type", "qty": "Qty",
                           "buy": st.column_config.NumberColumn("Buy", format="%.2f"),
                           "sell": st.column_config.NumberColumn("Sell", format="%.2f"),
                           "brokerage": st.column_config.NumberColumn("Brokerage", format="%.2f"),
                           "gross_profit": st.column_config.NumberColumn("Gross profit", format="%.0f"),
                           "roi": st.column_config.NumberColumn("ROI %", format="%.2f")},
        )
        r1, r2 = st.columns([1, 3])
        if r1.button("Remove selected"):
            keep = ~edited["Remove"].fillna(False).astype(bool).to_numpy()
            if keep.all():
                st.info("Tick at least one row first.")
            else:
                remaining = trades[keep].reset_index(drop=True)
                save_trades(remaining if not remaining.empty else None, state.get_frame("excluded"), state.get_meta().get("trades_source", ""))
                st.rerun()
        confirm = r2.checkbox("I want to delete every trade for this owner")
        if confirm and r2.button("Delete all trades", type="secondary"):
            save_trades(None, None, "")
            st.rerun()

# --------------------------------------------------------------- capital ----
st.divider()
st.subheader("2. Monthly capital")

trades = state.get_frame("trades")
if trades is None or trades.empty:
    st.info("Load trades first. The months found in your data will appear here.")
    st.stop()

months = months_in(trades)
existing = state.get_frame("capital")
if existing is not None and not existing.empty and set(existing["month"]) != set(months):
    existing = existing[existing["month"].isin(months)]
cap = capital_frame(months, existing, trades)
if "capital" in trades:
    st.caption("Your file has a Capital column; its per-month average is pre-filled. You can overwrite it.")

with st.expander("Upload a monthly capital sheet (Month + Capital columns; the 'Average of Capital' pivot works as-is)",
                 expanded=st.session_state.get("capital_upload") is not None):
    cap_upload = st.file_uploader("Capital sheet", type=["xlsx", "xlsm", "xls", "csv"], key="capital_upload")
    cap_wb = state.cached_workbook(cap_upload, "capital_wb") if cap_upload is not None else None
    if cap_wb:
        cap_sheets = cap_wb.sheet_names
        cap_sheet = cap_sheets[0]
        if len(cap_sheets) > 1:
            cap_sheet = st.selectbox("Tab with the capital table", cap_sheets, key="capital_sheet")
        parsed, cap_errors = load_capital_frame(cap_wb.frame(cap_sheet))
        for e in cap_errors:
            st.error(e)
        if parsed is not None:
            matched = parsed[parsed["month"].isin(months)]
            st.caption(f"{len(parsed)} months in the sheet; {len(matched)} match months in your trades.")
            if st.button("Use these capital figures", disabled=matched.empty):
                lookup = matched.set_index("month")["Capital"]
                cap["Capital"] = cap["month"].map(lookup).astype("Float64").fillna(cap["Capital"])
                state.put_frame("capital", cap)
                state.bump("capital_version")
                st.rerun()

bulk_col, grid_col = st.columns([1, 2])
with bulk_col:
    same = st.number_input("Same capital for every month (₹)", min_value=0, step=100_000, value=0)
    if st.button("Apply to all months", disabled=same <= 0):
        cap["Capital"] = pd.Series([float(same)] * len(cap), dtype="Float64")
        state.put_frame("capital", cap)
        state.bump("capital_version")
        st.rerun()
    st.caption("Or type a value per month in the table: the month-average of capital deployed. "
               "Used for Monthly ROI = Net Profit ÷ Capital × 100.")
with grid_col:
    edited = st.data_editor(
        cap[["Month", "Capital"]], disabled=["Month"], hide_index=True, width="stretch",
        key=f"capital_grid_{state.version('capital_version')}",
        column_config={"Capital": st.column_config.NumberColumn("Capital (₹)", min_value=0, step=10_000, format="%d")},
    )
    new_values = pd.to_numeric(edited["Capital"], errors="coerce").astype("Float64")
    if not new_values.equals(cap["Capital"]):
        cap["Capital"] = new_values.values
        state.put_frame("capital", cap)

missing = int((cap["Capital"].fillna(0) <= 0).sum())
if missing:
    st.warning(f"ROI needs a capital figure for {missing} more month(s). Months without capital show ROI as —.")
else:
    st.success(f"Capital entered for all {len(cap)} months (average {inr(float(cap['Capital'].astype(float).mean()), prefix='₹')}).")

st.divider()
st.caption("Market benchmarks (Nifty, NASDAQ, Gold BeES …) are entered once for everyone on the **Benchmarks** screen.")
st.page_link("screens/benchmarks.py", label="Go to Benchmarks", icon="📈")
st.page_link("screens/reports.py", label="Go to Dashboards", icon="📊")
