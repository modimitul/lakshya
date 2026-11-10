"""Investment Book: equity holdings by month and sector (upload or form)."""

import datetime as dt

import pandas as pd
import streamlit as st

from core import state
from core.formatting import inr
from core.parse import apply_grid_edits
from core.portfolio import (
    COMMON_SECTORS,
    PortfolioResult,
    dedupe_entries,
    entry_from_form,
    load_portfolio_workbook,
    looks_like_portfolio_header,
    match_sales,
    portfolio_template_bytes,
    sale_from_form,
)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

owner = state.user_name()
st.title("Investment Book")
st.caption(f"Portfolio owner: **{owner}**. One row per purchase: month, sector, stock, quantity, buy price. "
           "Cost and % Investment are calculated.")


def show_messages(result: PortfolioResult) -> None:
    for msg in result.errors:
        st.error(msg)
    for msg in result.warnings:
        st.warning(msg)
    for msg in result.notes:
        st.caption(msg)


def import_quality_warning(frame: pd.DataFrame) -> None:
    """Warn right after an import when purchase rows arrived without usable Qty or Cost."""
    buys = frame[frame["side"] != "sell"] if "side" in frame else frame
    if buys.empty:
        return
    qty_ok = (pd.to_numeric(buys["qty"], errors="coerce") > 0) if "qty" in buys.columns else pd.Series(False, index=buys.index)
    cost_ok = (pd.to_numeric(buys["cost"], errors="coerce") > 0) if "cost" in buys.columns else pd.Series(False, index=buys.index)
    no_qty, no_cost = int((~qty_ok).sum()), int((~cost_ok).sum())
    if no_qty or no_cost:
        st.warning(f"Heads up: {no_qty:,} imported purchase rows have no usable Qty and {no_cost:,} no usable Cost. "
                   "Check the column mapping below and the sheet's Qty / Buy / Cost values, then re-import.")


def save_portfolio(entries: pd.DataFrame | None, source: str) -> None:
    state.put_frame("portfolio", entries)
    state.put_meta({"portfolio_source": source})
    state.bump("portfolio_version")


entries = state.get_frame("portfolio")

mode = st.radio("How do you want to provide holdings?", ["Upload a file", "Add entries manually", "Record a sale"],
                horizontal=True, label_visibility="collapsed")

if mode == "Upload a file":
    c1, c2 = st.columns([3, 1])
    with c2:
        st.download_button("Download blank template (.xlsx)", portfolio_template_bytes(), "portfolio_template.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with c1:
        upload = st.file_uploader(
            "Portfolio file (.xlsx, .xlsm, .xls, .csv). Several tabs are fine: pick them below.",
            type=["xlsx", "xlsm", "xls", "csv"], key="portfolio_upload",
            help="Columns: MONTH, SECTORS, STOCK, QTY, BUY, COST, GIFT AMOUNT. Months may be dates or text like Jul-23.",
        )
    wb = state.cached_workbook(upload, "portfolio_wb") if upload is not None else None
    if wb:
        sheets = wb.sheet_names
        chosen = sheets
        if len(sheets) > 1:
            detected = [sh for sh in sheets if looks_like_portfolio_header(wb.headers(sh))]
            chosen = st.multiselect("Tabs to import", sheets, default=detected or sheets, key="portfolio_tabs")
        how = st.radio("How to import",
                       ["Replace only the months covered by the file", "Add to existing holdings (duplicates skipped)", "Replace ALL of this owner's holdings"],
                       index=0 if entries is not None and not entries.empty else 2, key="portfolio_how",
                       help="Replace only the months covered: existing rows for the months present in the file are removed, the file's rows added, "
                            "other months untouched. Add: keeps everything, skips exact duplicates. Replace ALL: deletes every holding first.")
        if st.button("Import", type="primary", disabled=not chosen, key="portfolio_import"):
            with st.spinner("Importing …"):
                result = load_portfolio_workbook(wb, chosen)
            show_messages(result)
            if result.ok:
                incoming = result.entries
                if how.startswith("Replace only") and entries is not None and not entries.empty:
                    from core.parse import replace_covered_months
                    incoming, dropped = dedupe_entries(incoming)
                    merged, removed, months_replaced = replace_covered_months(entries, incoming)
                    save_portfolio(merged, f"{state.get_meta().get('portfolio_source', '')} + {upload.name}".strip(" +"))
                    entries = merged
                    st.success(f"Replaced {removed:,} existing rows for {len(months_replaced)} month(s) with {len(incoming):,} rows from {upload.name}; "
                               f"{len(entries):,} rows in total, other months untouched.")
                elif how.startswith("Add") and entries is not None and not entries.empty:
                    merged, dropped = dedupe_entries(pd.concat([entries, incoming], ignore_index=True))
                    added = len(merged) - len(entries)
                    save_portfolio(merged, f"{state.get_meta().get('portfolio_source', '')} + {upload.name}".strip(" +"))
                    entries = merged
                    st.success(f"Added {added:,} holdings from {upload.name} ({dropped:,} duplicates skipped); "
                               f"{len(entries):,} in total worth {inr(entries['cost'].sum(), prefix='₹')}.")
                else:
                    incoming, dropped = dedupe_entries(incoming)
                    save_portfolio(incoming, upload.name)
                    entries = incoming
                    st.success(f"Imported {len(entries):,} holdings worth {inr(entries['cost'].sum(), prefix='₹')} from {upload.name}.")
                import_quality_warning(incoming)
                with st.expander("Per-tab summary and column mapping"):
                    for note in result.notes:
                        st.write(note)
                    st.dataframe(pd.DataFrame({"Your header": list(result.mapping), "Used as": list(result.mapping.values())}),
                                 width="stretch", hide_index=True)
elif mode == "Record a sale":
    if entries is None or entries.empty:
        st.info("Add purchases first; then you can record a sale against them.")
    else:
        remaining, _ = match_sales(entries)
        held = remaining.groupby("stock").agg(qty=("qty", "sum"), cost=("cost", "sum"), sector=("sector", "first")) if not remaining.empty else pd.DataFrame()
        held = held[held["qty"] > 0] if not held.empty else held
        if held.empty:
            st.info("Nothing is currently held (everything has been sold).")
        else:
            st.caption("Sales are matched to purchases FIFO (oldest lots first). Profit booked, ROI and CAGR appear on the Dashboard Reports → Investments tab.")
            with st.form("record_sale", clear_on_submit=True, border=True):
                a, b, c = st.columns(3)
                today = dt.date.today()
                m1, m2 = a.columns([3, 2])
                month_name = m1.selectbox("Sale month", MONTH_NAMES, index=today.month - 1)
                year = m2.selectbox("Year", list(range(today.year, 1999, -1)), index=0, key="sale_year")
                sale_month = dt.date(year, MONTH_NAMES.index(month_name) + 1, 1)
                stock = b.selectbox("Stock", list(held.index), format_func=lambda s_: f"{s_}  (held {held.loc[s_, 'qty']:g})")
                qty = c.number_input("Qty to sell", min_value=0.0, step=1.0, value=0.0)
                a, b, c = st.columns(3)
                price = a.number_input("Sell price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
                charges = b.number_input("Charges (₹, optional)", min_value=0.0, step=1.0, value=0.0, format="%.2f")
                if qty and price:
                    c.caption(f"Sale value: {inr(qty * price - charges, prefix='₹')}")
                submitted = st.form_submit_button("Record sale", type="primary")
            if submitted:
                problems = []
                if qty <= 0 or price <= 0:
                    problems.append("Qty and sell price must be greater than 0.")
                elif qty > float(held.loc[stock, "qty"]) + 1e-9:
                    problems.append(f"You hold {held.loc[stock, 'qty']:g} {stock}; cannot sell {qty:g}.")
                if problems:
                    for p_ in problems:
                        st.error(p_)
                else:
                    result = sale_from_form(sale_month, str(held.loc[stock, "sector"]), stock, qty, price, charges)
                    show_messages(result)
                    if result.ok:
                        combined = pd.concat([entries, result.entries], ignore_index=True)
                        save_portfolio(combined, state.get_meta().get("portfolio_source", "manual entry"))
                        entries = combined
                        _, sales = match_sales(combined)
                        last = sales.iloc[-1]
                        st.success(f"Recorded sale of {qty:g} {stock}: profit booked {inr(last['profit'], prefix='₹')}"
                                   + (f", ROI {last['roi']:.1f}%, CAGR {last['cagr']:.1f}% over {last['years']:.1f} years" if pd.notna(last["cagr"]) else ""))
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
    n_sells = int((entries["side"] == "sell").sum()) if "side" in entries else 0
    n_buys = len(entries) - n_sells
    total = float(entries.loc[entries["side"] != "sell", "cost"].sum()) if "side" in entries else float(entries["cost"].sum())
    with st.expander(f"Entries saved for {owner} ({n_buys:,} buys"
                     + (f", {n_sells:,} sells" if n_sells else "") + f", {inr(total, prefix='₹')} purchased)",
                     expanded=(mode in ("Add entries manually", "Record a sale"))):
        view_mode = st.radio("View", ["All entries (editable)", "Remaining holdings (after sales)"],
                             horizontal=True, key="pf_entries_view", label_visibility="collapsed")
        if view_mode.startswith("Remaining"):
            remaining, _ = match_sales(entries)
            if remaining.empty:
                st.info("Nothing is currently held: every purchase has been sold.")
            else:
                shown = remaining.sort_values("month", ascending=False, na_position="last").copy()
                shown = pd.DataFrame({
                    "Bought": shown["month"].dt.strftime("%b-%y"),
                    "Sector": shown["sector"], "Stock": shown["stock"],
                    "Qty held": shown["qty"].map(lambda v: inr(v) if pd.notna(v) else "—"),
                    "Cost held": shown["cost"].map(lambda v: inr(v) if pd.notna(v) else "—"),
                })
                st.dataframe(shown, hide_index=True, width="stretch", height=min(len(shown) + 1, 14) * 35 + 3)
                st.caption("What is still held per purchase lot after FIFO-matching the sales. "
                           "A fully sold lot disappears from this view; edit or remove rows in the other view.")
        else:
            if n_sells:
                st.caption("A sale is kept as its own SELL row next to the original BUY rows — that is the audit trail, "
                           "not a duplicate. Switch to **Remaining holdings** to see what is left after sales.")
            st.caption("Cells are editable; press **Save changes** when done. For edited rows, Value is recalculated "
                       "as Qty × Price and the month is snapped to its first day.")
            order = entries.sort_values("month", ascending=False, na_position="last").index
            editable_cols = [c for c in ("month", "sector", "stock", "side", "qty", "buy", "charges", "gift") if c in entries.columns]
            grid = entries.loc[order, editable_cols].copy()
            if "side" in grid:
                grid["side"] = grid["side"].astype("string").str.upper()
            grid.insert(0, "Remove", False)
            sector_options = sorted(set(COMMON_SECTORS) | set(entries["sector"].dropna().astype(str))) if "sector" in entries.columns else COMMON_SECTORS
            edited = st.data_editor(
                grid, hide_index=True, width="stretch", height=min(len(grid) + 1, 14) * 35 + 3,
                key=f"portfolio_list_{state.version('portfolio_version')}",
                column_config={
                    "Remove": st.column_config.CheckboxColumn(help="Tick rows to remove"),
                    "month": st.column_config.DateColumn("Month", format="MMM YY"),
                    "sector": st.column_config.SelectboxColumn("Sector", options=sector_options),
                    "stock": st.column_config.TextColumn("Stock"),
                    "side": st.column_config.SelectboxColumn("Side", options=["BUY", "SELL"],
                                                             help="SELL rows are matched FIFO against earlier BUY rows of the same stock."),
                    "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                    "buy": st.column_config.NumberColumn("Price", format="%.2f"),
                    "charges": st.column_config.NumberColumn("Charges", format="%.2f"),
                    "gift": st.column_config.NumberColumn("Gift", format="%.0f"),
                },
            )
            r0, r1, r2 = st.columns([1, 1, 2])
            if r0.button("Save changes", type="primary", key="portfolio_save_edits"):
                normalised = edited.copy()
                if "side" in normalised:
                    normalised["side"] = normalised["side"].astype("string").str.lower()
                updated, changed = apply_grid_edits(entries, order, normalised, editable_cols)
                if not changed:
                    st.info("No cells were changed.")
                else:
                    for idx in changed:
                        if pd.notna(updated.at[idx, "month"]):
                            updated.at[idx, "month"] = pd.Timestamp(updated.at[idx, "month"]).to_period("M").to_timestamp()
                        qty_v = pd.to_numeric(pd.Series([updated.at[idx, "qty"]]), errors="coerce").iloc[0] if "qty" in updated.columns else None
                        price_v = pd.to_numeric(pd.Series([updated.at[idx, "buy"]]), errors="coerce").iloc[0] if "buy" in updated.columns else None
                        if pd.notna(qty_v) and pd.notna(price_v) and "cost" in updated.columns:
                            updated.at[idx, "cost"] = float(qty_v) * float(price_v)
                        if "sector" in updated.columns and pd.notna(updated.at[idx, "sector"]):
                            updated.at[idx, "sector"] = str(updated.at[idx, "sector"]).upper()
                        if "stock" in updated.columns and pd.notna(updated.at[idx, "stock"]):
                            updated.at[idx, "stock"] = str(updated.at[idx, "stock"]).strip().upper()
                    save_portfolio(updated, state.get_meta().get("portfolio_source", "manual entry"))
                    st.success(f"Saved edits to {len(changed)} row(s).")
                    st.rerun()
            if r1.button("Remove selected", key="portfolio_remove"):
                remove_mask = edited["Remove"].fillna(False).astype(bool).to_numpy()
                if not remove_mask.any():
                    st.info("Tick at least one row first.")
                else:
                    remaining = entries.drop(index=order[remove_mask]).reset_index(drop=True)
                    save_portfolio(remaining if not remaining.empty else None, state.get_meta().get("portfolio_source", ""))
                    st.rerun()
            confirm = r2.checkbox("I want to delete every holding for this owner", key="portfolio_confirm")
            if confirm and r2.button("Delete all holdings", key="portfolio_delete_all"):
                save_portfolio(None, "")
                st.rerun()
else:
    st.info("No holdings yet for this owner. Upload a file or add entries with the form.")

st.page_link("screens/reports.py", label="Go to Dashboard Reports", icon="📊")
