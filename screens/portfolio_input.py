"""Investment Book: equity holdings by month and sector (upload or form)."""

import datetime as dt

import pandas as pd
import streamlit as st

from core import state, store
from core.formatting import inr
from core.parse import apply_grid_edits, cell_changed
from core.sips import SIP_SOURCE, empty_sips, next_due, normalise_sips, run_autopost
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


posted = run_autopost()
if posted:
    st.success(f"SIP auto-post: added {posted} instalment(s) that fell due. See SIP plans below.")
for _flash in st.session_state.pop("investbook_flash", []):
    st.success(_flash)
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

        # ------------------------------------------------ sales recorded ----
        sells = entries[entries["side"] == "sell"] if "side" in entries.columns else entries.iloc[0:0]
        if not sells.empty:
            st.divider()
            st.markdown(f"**Sales recorded ({len(sells):,})**")
            st.caption("Tick **Remove** on a wrongly recorded sale and press **Remove selected sales** to undo it — "
                       "the sold quantity goes back into holdings (purchases re-match FIFO automatically) and the "
                       "Dashboard's profit booked updates.")
            s_order = sells.sort_values("month", ascending=False).index
            sgrid = pd.DataFrame({
                "Remove": False,
                "Sold in": pd.to_datetime(entries.loc[s_order, "month"]),
                "Stock": entries.loc[s_order, "stock"].astype(str),
                "Sector": entries.loc[s_order, "sector"].astype(str),
                "Qty": pd.to_numeric(entries.loc[s_order, "qty"], errors="coerce"),
                "Sell price": pd.to_numeric(entries.loc[s_order, "buy"], errors="coerce"),
                "Sale value": pd.to_numeric(entries.loc[s_order, "cost"], errors="coerce"),
            })
            sedited = st.data_editor(
                sgrid, hide_index=True, width="stretch", height=min(len(sgrid) + 1, 10) * 35 + 3,
                disabled=["Sold in", "Stock", "Sector", "Qty", "Sell price", "Sale value"],
                key=f"sales_list_{state.version('portfolio_version')}",
                column_config={
                    "Remove": st.column_config.CheckboxColumn(help="Tick sales to remove"),
                    "Sold in": st.column_config.DateColumn("Sold in", format="MMM YY"),
                    "Qty": st.column_config.NumberColumn(format="%.0f"),
                    "Sell price": st.column_config.NumberColumn(format="%.2f"),
                    "Sale value": st.column_config.NumberColumn("Sale value (₹)", format="%.0f"),
                },
            )
            if st.button("Remove selected sales", key="sales_remove"):
                rm = sedited["Remove"].fillna(False).astype(bool).to_numpy()
                if not rm.any():
                    st.info("Tick at least one sale first.")
                else:
                    removed_stocks = sorted(set(entries.loc[s_order[rm], "stock"].astype(str)))
                    remaining_entries = entries.drop(index=s_order[rm]).reset_index(drop=True)
                    save_portfolio(remaining_entries if not remaining_entries.empty else None,
                                   state.get_meta().get("portfolio_source", ""))
                    st.session_state["investbook_flash"] = [
                        f"Removed {int(rm.sum())} sale(s): {', '.join(removed_stocks)}. "
                        "The sold quantity is back in holdings and the Dashboard has updated."]
                    st.rerun()
else:
    known_sectors = sorted(set(COMMON_SECTORS) | (set(entries["sector"].dropna()) if entries is not None else set()))
    _stock_frame = store.load_frame("_shared", "stocks")
    _stock_names, _stock_sectors = [], {}
    if _stock_frame is not None and "stock" in _stock_frame.columns:
        for _, _sr in _stock_frame.iterrows():
            _nm = str(_sr.get("stock") or "").strip().upper()
            if _nm and _nm not in _stock_sectors:
                _stock_names.append(_nm)
                _stock_sectors[_nm] = str(_sr.get("sector") or "").strip().upper()
    AUTO_SECTOR = "Auto (from Stocks Management)"
    NEW_STOCK = "➕ New stock…"
    with st.form("add_entry", clear_on_submit=True, border=True):
        a, b, c = st.columns(3)
        today = dt.date.today()
        m1, m2 = a.columns([3, 2])
        month_name = m1.selectbox("Purchase month", MONTH_NAMES, index=today.month - 1)
        year = m2.selectbox("Year", list(range(today.year, 1999, -1)), index=0)
        month = dt.date(year, MONTH_NAMES.index(month_name) + 1, 1)
        sector_options = ([AUTO_SECTOR] if _stock_names else []) + known_sectors + ["Other"]
        sector = b.selectbox("Sector", sector_options,
                             index=0 if _stock_names else (known_sectors.index("OTHER") if "OTHER" in known_sectors else 0),
                             help="Auto takes the sector saved for the picked stock in Stocks Management.")
        other_sector = b.text_input("If Other, type the sector", placeholder="e.g. DEFENCE")
        if _stock_names:
            stock_pick = c.selectbox("Stock", sorted(_stock_names) + [NEW_STOCK],
                                     help="From Stocks Management; pick ➕ to type a new one.")
            stock_typed = c.text_input("If ➕ New stock…, type it", placeholder="e.g. DMART").strip().upper()
            stock = stock_typed if (stock_pick == NEW_STOCK or stock_typed) else stock_pick
        else:
            stock = c.text_input("Stock", placeholder="e.g. DMART",
                                 help="Tip: fill Stocks Management (menu) to get a dropdown here.").strip().upper()
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
        if chosen_sector == AUTO_SECTOR:
            chosen_sector = _stock_sectors.get(stock, "")
            if not chosen_sector:
                problems.append(f"Stocks Management has no sector for {stock or 'this stock'} — "
                                "pick a sector in the form (or fill it in Stocks Management first).")
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
                if stock and stock not in _stock_sectors:
                    addition = pd.DataFrame([{"stock": stock, "sector": chosen_sector, "marketcap": "", "note": ""}])
                    full = pd.concat([_stock_frame, addition], ignore_index=True) if _stock_frame is not None else addition
                    store.save_frame("_shared", "stocks", full)
                    state.bump("stocks_version")
                    st.caption(f"“{stock}” was added to the stock list (menu → Stocks Management).")

# ------------------------------------------------------------- SIP plans ----
sips = normalise_sips(state.get_frame("sips"))
n_active = int((sips["active"] > 0).sum()) if not sips.empty else 0
with st.expander(f"SIP plans — auto-post monthly instalments ({n_active} active)", expanded=False):
    st.caption("Each **active** plan posts one BUY row per month (Cost = amount, sector as set, Qty left blank since the "
               "NAV isn't known here) on its instalment day; months missed while the app was closed are posted on the next "
               "visit. Posted rows carry the marker `SIP` and can be edited like any entry. Add rows with the + below.")
    sip_grid = sips.copy()
    sip_grid["active"] = sip_grid["active"] > 0
    sip_grid["next_due"] = [str(next_due(r) or "—") for _, r in normalise_sips(sips).iterrows()] if not sips.empty else []
    sip_sector_options = sorted(set(COMMON_SECTORS) | set(sips["sector"].dropna().astype(str)))
    edited_sips = st.data_editor(
        sip_grid, hide_index=True, width="stretch", num_rows="dynamic",
        key=f"sip_grid_{state.version('sips_version')}",
        column_config={
            "fund": st.column_config.TextColumn("Fund", required=True, help="e.g. PARAG PARIKH FLEXI CAP FUND"),
            "sector": st.column_config.SelectboxColumn("Sector", options=sip_sector_options, default="MUTUAL FUND"),
            "amount": st.column_config.NumberColumn("Amount (₹/instalment)", min_value=0, step=500, format="%.0f"),
            "day": st.column_config.NumberColumn("Day of month", min_value=1, max_value=31, step=1, format="%.0f"),
            "start_month": st.column_config.DateColumn("Start month", format="MMM YY"),
            "active": st.column_config.CheckboxColumn("Active"),
            "last_applied": st.column_config.DateColumn("Last posted", format="MMM YY", disabled=True),
            "next_due": st.column_config.TextColumn("Next instalment", disabled=True),
        },
    )
    if st.button("Save SIP plans", type="primary", key="sips_save"):
        cleaned = normalise_sips(edited_sips.drop(columns=["next_due"], errors="ignore"))
        bad = cleaned[(cleaned["amount"].isna()) | (cleaned["amount"] <= 0)]
        if not bad.empty:
            st.error("Every plan needs an amount greater than 0.")
        else:
            state.put_frame("sips", cleaned if not cleaned.empty else None)
            state.bump("sips_version")
            st.success(f"Saved {len(cleaned)} SIP plan(s). Due instalments post automatically on the next page load.")
            st.rerun()

if entries is not None and not entries.empty:
    # ------------------------------------------------------ open positions ----
    open_remaining, _ = match_sales(entries)
    open_held = (open_remaining.groupby("stock")
                 .agg(sector=("sector", "first"), qty=("qty", "sum"), cost=("cost", "sum"))
                 .reset_index()) if not open_remaining.empty else pd.DataFrame()
    if not open_held.empty:
        open_held = open_held[pd.to_numeric(open_held["qty"], errors="coerce").fillna(0) > 0]
    if not open_held.empty:
        with st.expander(f"Open positions for {owner} ({len(open_held):,} holdings)", expanded=False):
            st.caption("Everything still held (purchases minus FIFO-matched sales), one row per stock. "
                       "To close or trim a position, fill **Sell qty** and **Sell price** (and charges if any) on its row and press "
                       "**Record sales** — a SELL row is added to Entries saved below and the profit booked flows into "
                       "Dashboard Reports → Investments.")
            today = dt.date.today()
            ogrid = pd.DataFrame({
                "stock": open_held["stock"].astype(str),
                "sector": open_held["sector"].astype(str),
                "qty": pd.to_numeric(open_held["qty"], errors="coerce"),
                "cost": pd.to_numeric(open_held["cost"], errors="coerce"),
                "sell_qty": pd.Series([float("nan")] * len(open_held)),
                "sell_price": pd.Series([float("nan")] * len(open_held)),
                "sell_charges": pd.Series([float("nan")] * len(open_held)),
                "sale_month": pd.Series([pd.Timestamp(today.year, today.month, 1)] * len(open_held)),
            })
            ogrid["avg"] = ogrid["cost"] / ogrid["qty"].where(ogrid["qty"] > 0)
            ogrid = ogrid[["stock", "sector", "qty", "cost", "avg", "sell_qty", "sell_price", "sell_charges", "sale_month"]]
            oedited = st.data_editor(
                ogrid, hide_index=True, width="stretch", height=min(len(ogrid) + 1, 14) * 35 + 3,
                disabled=["stock", "sector", "qty", "cost", "avg"],
                key=f"open_holdings_{state.version('portfolio_version')}",
                column_config={
                    "stock": st.column_config.TextColumn("Stock"),
                    "sector": st.column_config.TextColumn("Sector"),
                    "qty": st.column_config.NumberColumn("Qty held", format="%.0f"),
                    "cost": st.column_config.NumberColumn("Cost held (₹)", format="%.0f"),
                    "avg": st.column_config.NumberColumn("Avg cost", format="%.2f"),
                    "sell_qty": st.column_config.NumberColumn("Sell qty", min_value=0, format="%.0f"),
                    "sell_price": st.column_config.NumberColumn("Sell price", min_value=0.0, format="%.2f"),
                    "sell_charges": st.column_config.NumberColumn("Charges (₹)", min_value=0.0, format="%.2f"),
                    "sale_month": st.column_config.DateColumn("Sale month", format="MMM YY"),
                },
            )
            if st.button("Record sales", type="primary", key="open_holdings_sell"):
                picked = oedited[(pd.to_numeric(oedited["sell_qty"], errors="coerce").fillna(0) > 0)
                                 | (pd.to_numeric(oedited["sell_price"], errors="coerce").fillna(0) > 0)]
                if picked.empty:
                    st.info("Fill Sell qty and Sell price on at least one row first.")
                else:
                    problems, pending = [], []
                    for _, prow in picked.iterrows():
                        s_qty = pd.to_numeric(pd.Series([prow["sell_qty"]]), errors="coerce").iloc[0]
                        s_price = pd.to_numeric(pd.Series([prow["sell_price"]]), errors="coerce").iloc[0]
                        s_charges = pd.to_numeric(pd.Series([prow["sell_charges"]]), errors="coerce").iloc[0]
                        s_charges = 0.0 if pd.isna(s_charges) else float(s_charges)
                        held_q = float(prow["qty"])
                        if pd.isna(s_qty) or s_qty <= 0 or pd.isna(s_price) or s_price <= 0:
                            problems.append(f"{prow['stock']}: both Sell qty and Sell price must be greater than 0.")
                        elif float(s_qty) > held_q + 1e-9:
                            problems.append(f"{prow['stock']}: you hold {held_q:g}; cannot sell {float(s_qty):g}.")
                        else:
                            s_month = pd.Timestamp(prow["sale_month"]).date() if pd.notna(prow["sale_month"]) else today
                            s_month = dt.date(s_month.year, s_month.month, 1)
                            pending.append((s_month, str(prow["sector"]), str(prow["stock"]), float(s_qty), float(s_price), s_charges))
                    if problems:
                        for p_ in problems:
                            st.error(p_)
                    else:
                        combined, booked = entries, []
                        for s_month, s_sector, s_stock, s_qty, s_price, s_charges in pending:
                            result = sale_from_form(s_month, s_sector, s_stock, s_qty, s_price, s_charges)
                            show_messages(result)
                            if result.ok:
                                combined = pd.concat([combined, result.entries], ignore_index=True)
                                booked.append(s_stock)
                        if booked:
                            save_portfolio(combined, state.get_meta().get("portfolio_source", "manual entry"))
                            st.success(f"Recorded {len(booked)} sale(s): {', '.join(booked)}. "
                                       "The SELL rows are in Entries saved below and profit booked is on the Dashboard.")
                            st.rerun()

    n_sells = int((entries["side"] == "sell").sum()) if "side" in entries else 0
    n_buys = len(entries) - n_sells
    total = float(entries.loc[entries["side"] != "sell", "cost"].sum()) if "side" in entries else float(entries["cost"].sum())
    with st.expander(f"Entries saved for {owner} ({n_buys:,} buys"
                     + (f", {n_sells:,} sells" if n_sells else "") + f", {inr(total, prefix='₹')} purchased)",
                     expanded=(mode in ("Add entries manually", "Record a sale"))):
        view_mode = st.radio("View", ["All entries (editable)", "Remaining holdings (after sales)"],
                             horizontal=True, key="pf_entries_view", label_visibility="collapsed")
        if view_mode.startswith("Remaining"):
            remaining, _ = match_sales(entries, with_lineage=True)
            if remaining.empty:
                st.info("Nothing is currently held: every purchase has been sold.")
            else:
                st.caption("**Qty held** and **Cost held** are editable: corrections are written back to the original "
                           "purchase lot, leaving the sold portion (and past profit booked) untouched. "
                           "Set Qty held to 0 to drop a wrongly-held lot.")
                rem = remaining.sort_values("month", ascending=False, na_position="last").reset_index(drop=True)
                rgrid = pd.DataFrame({
                    "month": rem["month"], "sector": rem["sector"], "stock": rem["stock"],
                    "qty": pd.to_numeric(rem["qty"], errors="coerce"),
                    "cost": pd.to_numeric(rem["cost"], errors="coerce"),
                })
                redited = st.data_editor(
                    rgrid, hide_index=True, width="stretch", height=min(len(rgrid) + 1, 14) * 35 + 3,
                    disabled=["month", "sector", "stock"],
                    key=f"remaining_grid_{state.version('portfolio_version')}",
                    column_config={
                        "month": st.column_config.DateColumn("Bought", format="MMM YY"),
                        "sector": st.column_config.TextColumn("Sector"),
                        "stock": st.column_config.TextColumn("Stock"),
                        "qty": st.column_config.NumberColumn("Qty held", min_value=0, format="%.0f"),
                        "cost": st.column_config.NumberColumn("Cost held (₹)", min_value=0, format="%.0f"),
                    },
                )
                if st.button("Save corrections", type="primary", key="remaining_save"):
                    updated = entries.copy()
                    fixed = 0
                    for pos in range(len(rem)):
                        src = rem.iloc[pos]["src_index"]
                        sold_q = float(rem.iloc[pos]["sold_qty"]) if pd.notna(rem.iloc[pos]["sold_qty"]) else 0.0
                        sold_c = float(rem.iloc[pos]["sold_cost"]) if pd.notna(rem.iloc[pos]["sold_cost"]) else 0.0
                        row_changed = False
                        for col in ("qty", "cost"):
                            if cell_changed(rgrid.iloc[pos][col], redited.iloc[pos][col]):
                                new_rem = redited.iloc[pos][col]
                                total = (sold_q if col == "qty" else sold_c) + (0.0 if pd.isna(new_rem) else float(new_rem))
                                updated.at[src, col] = total
                                row_changed = True
                        if row_changed:
                            q = pd.to_numeric(pd.Series([updated.at[src, "qty"]]), errors="coerce").iloc[0]
                            c = pd.to_numeric(pd.Series([updated.at[src, "cost"]]), errors="coerce").iloc[0]
                            if pd.notna(q) and q > 0 and pd.notna(c) and "buy" in updated.columns:
                                updated.at[src, "buy"] = float(c) / float(q)
                            fixed += 1
                    if not fixed:
                        st.info("No cells were changed.")
                    else:
                        save_portfolio(updated, state.get_meta().get("portfolio_source", "manual entry"))
                        st.success(f"Corrected {fixed} lot(s).")
                        st.rerun()
        else:
            if n_sells:
                st.caption("A sale is kept as its own SELL row next to the original BUY rows — that is the audit trail, "
                           "not a duplicate. Switch to **Remaining holdings** to see what is left after sales.")
            st.caption("Cells are editable; press **Save changes** when done. For edited rows, Value is recalculated "
                       "as Qty × Price and the month is snapped to its first day. "
                       "**Sale date / Sale price**: on a SELL row they are the sale's own month and price (edit to correct); "
                       "on a BUY row, fill both and press Save changes to **book a sale of that whole lot** "
                       "(a SELL row is added — partial sales go through Record a sale).")
            order = entries.sort_values("month", ascending=False, na_position="last").index
            editable_cols = [c for c in ("month", "sector", "stock", "side", "qty", "buy", "charges", "gift") if c in entries.columns]
            grid = entries.loc[order, editable_cols].copy()
            if "side" in grid:
                grid["side"] = grid["side"].astype("string").str.upper()
            sell_mask_order = (entries.loc[order, "side"].astype(str).str.lower() == "sell"
                               if "side" in entries.columns else pd.Series(False, index=order))
            grid["sale_date"] = pd.to_datetime(entries.loc[order, "month"], errors="coerce").where(sell_mask_order)
            grid["sale_price"] = pd.to_numeric(entries.loc[order, "buy"], errors="coerce").where(sell_mask_order)
            show_cols = [c for c in ("month", "sector", "stock", "side", "qty", "buy", "sale_date", "sale_price",
                                     "charges", "gift") if c in grid.columns]
            grid = grid[show_cols]
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
                    "sale_date": st.column_config.DateColumn("Sale date", format="MMM YY",
                                                             help="SELL row: the sale month. BUY row: fill with Sale price "
                                                                  "to book a sale of this whole lot."),
                    "sale_price": st.column_config.NumberColumn("Sale price", min_value=0.0, format="%.2f",
                                                                help="SELL row: the sale price. BUY row: fill with Sale date "
                                                                     "to book a sale of this whole lot."),
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
                changed = list(changed)
                # ---- the two virtual sale columns -------------------------------
                sale_requests, sale_errors = [], []
                for pos, idx in enumerate(order):
                    is_sell = bool(sell_mask_order.iloc[pos])
                    e_sd = edited.iloc[pos]["sale_date"]
                    e_sp = pd.to_numeric(pd.Series([edited.iloc[pos]["sale_price"]]), errors="coerce").iloc[0]
                    sd_changed = cell_changed(grid.iloc[pos]["sale_date"], edited.iloc[pos]["sale_date"])
                    sp_changed = cell_changed(grid.iloc[pos]["sale_price"], edited.iloc[pos]["sale_price"])
                    if not (sd_changed or sp_changed):
                        continue
                    stock_name = str(entries.at[idx, "stock"]) if "stock" in entries.columns else "?"
                    if is_sell:
                        if sd_changed and pd.notna(e_sd):
                            updated.at[idx, "month"] = pd.Timestamp(e_sd)
                            if idx not in changed:
                                changed.append(idx)
                        if sp_changed and pd.notna(e_sp):
                            updated.at[idx, "buy"] = float(e_sp)
                            if idx not in changed:
                                changed.append(idx)
                    else:
                        if pd.notna(e_sd) and pd.notna(e_sp) and float(e_sp) > 0:
                            sale_requests.append((idx, pd.Timestamp(e_sd), float(e_sp)))
                        else:
                            sale_errors.append(f"{stock_name}: fill **both** Sale date and Sale price to book the sale.")
                if sale_errors:
                    for e_ in sale_errors:
                        st.error(e_)
                    st.warning("Nothing was saved — fix (or clear) the sale cells above and press Save changes again.")
                elif not changed and not sale_requests:
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
                    booked, problems = [], []
                    if sale_requests:
                        held_now, _ = match_sales(updated)
                        held_by_stock = (held_now.groupby("stock")["qty"].sum().to_dict()
                                         if not held_now.empty else {})
                        pieces = []
                        for idx, sd, sp in sale_requests:
                            row = updated.loc[idx]
                            s_stock = str(row.get("stock") or "").strip().upper()
                            s_qty = pd.to_numeric(pd.Series([row.get("qty")]), errors="coerce").iloc[0]
                            if pd.isna(s_qty) or s_qty <= 0:
                                problems.append(f"{s_stock}: the lot has no Qty, so its sale cannot be booked.")
                                continue
                            avail = float(held_by_stock.get(s_stock, 0.0))
                            if float(s_qty) > avail + 1e-9:
                                problems.append(f"{s_stock}: only {avail:g} held across all lots; this lot's {float(s_qty):g} "
                                                "is already (partly) sold. Use Record a sale for a partial quantity.")
                                continue
                            held_by_stock[s_stock] = avail - float(s_qty)
                            s_month = dt.date(sd.year, sd.month, 1)
                            res = sale_from_form(s_month, str(row.get("sector") or ""), s_stock, float(s_qty), sp, 0.0)
                            show_messages(res)
                            if res.ok:
                                pieces.append(res.entries)
                                booked.append(s_stock)
                        if problems:
                            for p_ in problems:
                                st.error(p_)
                            st.warning("Nothing was saved — fix the rows above and press Save changes again.")
                            st.stop()
                        if pieces:
                            updated = pd.concat([updated] + pieces, ignore_index=True)
                    save_portfolio(updated, state.get_meta().get("portfolio_source", "manual entry"))
                    st.session_state["investbook_flash"] = (
                        ([f"Saved edits to {len(changed)} row(s)."] if changed else [])
                        + ([f"Booked {len(booked)} sale(s): {', '.join(booked)} — the SELL row(s) are in this list and "
                            "profit booked is on the Dashboard."] if booked else []))
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
