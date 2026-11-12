"""Trading Book: trades (upload or form), monthly capital, annual ROI vs benchmarks."""

import datetime as dt

import pandas as pd
import streamlit as st

from core import state, store
from core.formatting import inr
from core.portfolio import entry_from_form, sale_from_form
from core.metrics import capital_frame, monthly_summary, months_in
from core.strategies import (
    CHARGE_TYPE,
    OTHER_TYPE,
    bias,
    definition,
    opening_side,
    requires_strike,
    strategy_names,
)
from core.parse import (
    ParseResult,
    apply_grid_edits,
    open_positions_mask,
    recompute_trades,
    dedupe_trades,
    load_capital_frame,
    replace_covered_months,
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
for _flash in st.session_state.pop("tradebook_flash", []):
    st.success(_flash)
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
            help="Headers are matched by name, so extra columns are fine. Needed per tab: Month or Buy Date, Stock, "
                 "Strike Price for option trades, Type, and Gross Profit (or Profit/Loss, or Qty + Buy + Sell). "
                 "Rows with BROKERAGE / …CHARGES in Strike Price become Type = Brokerages.",
        )
    wb = state.cached_workbook(upload, "trade_wb") if upload is not None else None
    if wb:
        sheets = wb.sheet_names
        chosen = sheets
        if len(sheets) > 1:
            detected = [sh for sh in sheets if looks_like_trade_header(wb.headers(sh))]
            chosen = st.multiselect("Tabs to import", sheets, default=detected or sheets,
                                    help="Tabs that look like trade logs are pre-selected. Untick summary or pivot tabs.")
        how = st.radio("How to import",
                       ["Replace only the months covered by the file", "Add to existing trades (duplicates skipped)", "Replace ALL of this owner's trades"],
                       index=0 if trades is not None and not trades.empty else 2,
                       help="Replace only the months covered: existing rows for the months present in the file are removed and the file's rows "
                            "added; other months are untouched (use this to re-upload a corrected year). Add: keeps everything, skips exact duplicates. "
                            "Replace ALL: deletes every trade for this owner first.")
        if st.button("Import", type="primary", disabled=not chosen):
            with st.spinner("Importing …"):
                result = load_trades_workbook(wb, chosen)
            show_messages(result)
            if result.ok:
                incoming = result.trades
                dropped = 0
                if how.startswith("Replace only") and trades is not None and not trades.empty:
                    incoming, dropped = dedupe_trades(incoming)
                    merged, removed, months_replaced = replace_covered_months(trades, incoming)
                    old_excluded = state.get_frame("excluded")
                    excluded = pd.concat([x for x in (old_excluded, result.excluded) if x is not None and not x.empty], ignore_index=True) if (old_excluded is not None and not old_excluded.empty) or not result.excluded.empty else result.excluded
                    save_trades(merged, excluded, f"{state.get_meta().get('trades_source', '')} + {upload.name}".strip(" +"))
                    trades = merged
                    span = (f"{pd.Timestamp(months_replaced[0]):%b-%y} to {pd.Timestamp(months_replaced[-1]):%b-%y}" if months_replaced else "no months")
                    st.success(f"Replaced {removed:,} existing rows for {len(months_replaced)} month(s) ({span}) with {len(incoming):,} rows from {upload.name}. "
                               f"{len(trades):,} trades across {len(months_in(trades))} months in total; other months untouched.")
                elif how.startswith("Add") and trades is not None and not trades.empty:
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
    st.caption("Pick the type first; the form adapts. P&L, gross profit, investment and ROI are calculated for you.")
    t1, t2 = st.columns([1, 2])
    trade_type = t1.selectbox("Type", strategy_names() + [OTHER_TYPE], key="manual_type")
    other_type = ""
    if trade_type == OTHER_TYPE:
        other_type = t1.text_input("Type name", placeholder="e.g. Jade Lizard", key="manual_other_type")
    desc = definition(trade_type)
    bias_txt = bias(trade_type)
    if desc or bias_txt:
        t2.markdown(f"**{trade_type}**  \n{desc}" + (f"  \nBias: {bias_txt}" if bias_txt else ""))
    is_charge = trade_type == CHARGE_TYPE
    needs_strike = requires_strike(trade_type) if trade_type != OTHER_TYPE else False
    sells_first = (not is_charge) and trade_type != OTHER_TYPE and opening_side(trade_type) == "sell"

    with st.form("add_trade", clear_on_submit=True, border=True):
        if is_charge:
            a, b, c = st.columns(3)
            buy_date = a.date_input("Date", value=dt.date.today(), format="DD-MM-YYYY")
            stock = b.text_input("Description", value="BROKERAGE", help="e.g. BROKERAGE, DP CHARGES, AMC CHARGES").strip().upper()
            brokerage = c.number_input("Brokerage & other charges (₹)", min_value=0.0, step=1.0, value=0.0, format="%.2f")
            qty, buy, sell, sale_date, margin, lot, strike = 1, 0.0, 0.0, None, 0, 1, 0.0
        else:
            a, b, c = st.columns(3)
            if sells_first:
                sale_date = a.date_input("Sale date *", value=dt.date.today(), format="DD-MM-YYYY",
                                         help=f"{trade_type} opens with a sale, so the sale date is required.")
            else:
                buy_date = a.date_input("Buy date *", value=dt.date.today(), format="DD-MM-YYYY",
                                        help="This type opens with a buy, so the buy date is required.")
            _stock_frame = store.load_frame("_shared", "stocks")
            _stock_options = ([x for x in _stock_frame["stock"].astype(str).str.strip().str.upper().unique() if x]
                              if _stock_frame is not None and "stock" in _stock_frame.columns else [])
            NEW_STOCK = "➕ New stock…"
            if _stock_options:
                stock_pick = b.selectbox("Stock", sorted(_stock_options) + [NEW_STOCK],
                                         help="Manage this list in the Stocks page of the menu.")
                stock_typed = b.text_input("If ➕ New stock…, type it", placeholder="e.g. TCS").strip().upper()
                stock = stock_typed if (stock_pick == NEW_STOCK or stock_typed) else stock_pick
            else:
                stock = b.text_input("Stock", placeholder="e.g. TCS",
                                     help="Tip: fill the Stocks page (menu) to get a dropdown here.").strip().upper()
            strike = c.number_input("Strike price" + (" *" if needs_strike else " (optional)"), min_value=0, step=50, value=0,
                                    help=("Required for option strategies. Whole numbers only — strikes have no decimals."
                                          if needs_strike else "Not applicable to this type; leave 0."))
            a, b, c = st.columns(3)
            qty = a.number_input("Qty", min_value=0, step=1, value=0)
            buy = b.number_input("Buy price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
            sell = c.number_input("Sell price", min_value=0.0, step=0.05, value=0.0, format="%.2f")
            a, b, c, d = st.columns(4)
            if sells_first:
                buy_date = a.date_input("Buy date (optional)", value=None, format="DD-MM-YYYY",
                                        help="Fill when the position is bought back / squared off — or later, from Open positions.")
            else:
                sale_date = a.date_input("Sale date (optional)", value=None, format="DD-MM-YYYY",
                                         help="Fill when the position is sold / squared off — or later, from Open positions.")
            brokerage = b.number_input("Brokerage & charges", min_value=0.0, step=1.0, value=0.0, format="%.2f")
            margin = c.number_input("Margin per lot", min_value=0, step=1000, value=0)
            lot = d.number_input("Lots", min_value=0, step=1, value=1)
        submitted = st.form_submit_button("Add charge entry" if is_charge else "Add trade", type="primary")

    if submitted:
        problems = []
        if is_charge:
            if brokerage <= 0:
                problems.append("Enter the charge amount.")
        else:
            if not stock:
                problems.append("Stock is required.")
            if qty <= 0:
                problems.append("Qty must be greater than 0.")
            if buy <= 0 and sell <= 0:
                problems.append("Enter a buy and a sell price.")
            if sells_first and sale_date is None:
                problems.append(f"Sale date is required: {trade_type} opens with a sale.")
            if not sells_first and buy_date is None:
                problems.append("Buy date is required for this type.")
            if sells_first and sell <= 0 < buy:
                problems.append(f"Enter the sell price: {trade_type} opens with a sale.")
            if not sells_first and buy <= 0 < sell:
                problems.append("Enter the buy price: this type opens with a buy.")
            if needs_strike and strike <= 0:
                problems.append(f"Strike price is required for {trade_type}.")
            if trade_type == OTHER_TYPE and not other_type.strip():
                problems.append("Type the strategy name next to 'Other'.")
        if problems:
            for p_ in problems:
                st.error(p_)
        else:
            result = trade_from_form(
                buy_date=buy_date, stock=stock or "BROKERAGE",
                type=other_type.strip() if trade_type == OTHER_TYPE else trade_type,
                strike=strike or None, qty=qty, buy=buy, sale_date=sale_date, sell=sell,
                brokerage=brokerage, margin=margin or None, lot=lot or None,
            )
            show_messages(result)
            if result.ok:
                combined = pd.concat([trades, result.trades], ignore_index=True) if trades is not None else result.trades
                save_trades(combined, state.get_frame("excluded"), "manual entry")
                trades = combined
                row = result.trades.iloc[0]
                if is_charge:
                    st.success(f"Added charge entry {stock or 'BROKERAGE'}: {inr(brokerage, prefix='₹')} (counts against net profit, not as a trade).")
                else:
                    st.success(f"Added {stock}: gross profit {inr(row['gross_profit'], prefix='₹')}"
                               + (f", ROI {row['roi']:.2f}%" if pd.notna(row.get("roi")) else ""))
                    # remember a newly typed stock in the shared Stocks list
                    stock_frame = store.load_frame("_shared", "stocks")
                    known = (set(stock_frame["stock"].astype(str).str.upper())
                             if stock_frame is not None and "stock" in stock_frame.columns else set())
                    if stock and stock not in known:
                        addition = pd.DataFrame([{"stock": stock, "note": ""}])
                        updated_list = pd.concat([stock_frame, addition], ignore_index=True) if stock_frame is not None else addition
                        store.save_frame("_shared", "stocks", updated_list)
                        state.bump("stocks_version")
                        st.caption(f"“{stock}” was added to the Stocks list (menu → Stocks).")

    st.page_link("screens/strategy_guide.py", label="Open the Strategy Guide (definitions and bias)", icon="📖")

# Open positions / review / delete lists
if trades is not None and not trades.empty:
    open_mask = open_positions_mask(trades)
    editable_cols = [c for c in ("month", "buy_date", "stock", "type", "strike", "qty", "buy", "sale_date", "sell",
                                 "brokerage", "margin", "lot") if c in trades.columns]
    computed_cols = [c for c in ("gross_profit", "roi") if c in trades.columns]
    type_options = sorted(set(strategy_names()) | set(trades["type"].dropna().astype(str))) if "type" in trades.columns else strategy_names()

    def trade_column_config() -> dict:
        return {
            "Remove": st.column_config.CheckboxColumn(help="Tick rows to remove"),
            "buy_date": st.column_config.DateColumn("Buy date", format="DD-MMM-YY"),
            "sale_date": st.column_config.DateColumn("Sale date", format="DD-MMM-YY"),
            "month": st.column_config.DateColumn("Month", format="MMM YY",
                                                 help="Which month this trade counts under. Pick any date in the "
                                                      "right month to move the trade there (saved as that month)."),
            "stock": st.column_config.TextColumn("Stock"),
            "type": st.column_config.SelectboxColumn("Type", options=type_options),
            "strike": st.column_config.NumberColumn("Strike", format="%.0f", step=1),
            "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
            "buy": st.column_config.NumberColumn("Buy", format="%.2f"),
            "sell": st.column_config.NumberColumn("Sell", format="%.2f"),
            "brokerage": st.column_config.NumberColumn("Brokerage", format="%.2f"),
            "margin": st.column_config.NumberColumn("Margin/lot", format="%.0f"),
            "lot": st.column_config.NumberColumn("Lots", format="%.0f"),
            "gross_profit": st.column_config.NumberColumn("Gross profit", format="%.0f"),
            "roi": st.column_config.NumberColumn("ROI %", format="%.2f"),
        }

    if open_mask.any():
        n_open = int(open_mask.sum())
        with st.expander(f"Open positions for {owner} ({n_open})", expanded=True):
            st.caption("Trades with one leg still missing — they stay out of the dashboards until closed. "
                       "To close a position, fill the missing **Sell** (or **Buy**) price, its **date** and any **Brokerage**, "
                       "then press **Close / save** — the row moves to Trades saved below and starts counting in the Dashboard. "
                       "For an option that expired worthless, enter price **0** with the expiry date.")
            open_order = trades[open_mask].sort_values(["month", "buy_date"], ascending=[False, False], na_position="last").index
            open_grid = trades.loc[open_order, editable_cols + computed_cols].copy()
            open_grid.insert(0, "Remove", False)
            open_edited = st.data_editor(
                open_grid, hide_index=True, width="stretch", height=min(len(open_grid) + 1, 10) * 35 + 3,
                disabled=["gross_profit", "roi"], key=f"open_positions_{state.version('capital_version')}",
                column_config=trade_column_config(),
            )
            o0, o1, _ = st.columns([1, 1, 2])
            if o0.button("Close / save", type="primary", key="open_positions_save"):
                updated, changed = apply_grid_edits(trades, open_order, open_edited, editable_cols)
                if not changed:
                    st.info("No cells were changed.")
                else:
                    updated = recompute_trades(updated, changed)
                    save_trades(updated, state.get_frame("excluded"), state.get_meta().get("trades_source", "manual entry"))
                    closed = int((~open_positions_mask(updated).reindex(changed).fillna(False)).sum())
                    st.success(f"Saved {len(changed)} row(s); {closed} position(s) are now closed and moved to Trades saved.")
                    st.rerun()
            if o1.button("Remove selected", key="open_positions_remove"):
                remove_mask = open_edited["Remove"].fillna(False).astype(bool).to_numpy()
                if not remove_mask.any():
                    st.info("Tick at least one row first.")
                else:
                    remaining = trades.drop(index=open_order[remove_mask]).reset_index(drop=True)
                    save_trades(remaining if not remaining.empty else None, state.get_frame("excluded"), state.get_meta().get("trades_source", ""))
                    st.rerun()

    settled = trades[~open_mask]
    focus = st.session_state.get("tradebook_focus")
    focus_label, focus_mask = None, None
    if focus and not settled.empty:
        from core.benchmarks import period_label
        focus_mask = period_label(settled["month"], focus.get("basis", "calendar")) == focus.get("label")
        if focus_mask.any():
            focus_label = focus.get("label")
        else:
            st.session_state.pop("tradebook_focus", None)
    elif focus:
        st.session_state.pop("tradebook_focus", None)

    shown = settled[focus_mask] if focus_label else settled
    title = (f"Trades saved for {owner} — {focus_label} only ({len(shown):,})" if focus_label
             else f"Trades saved for {owner} ({len(settled):,})")
    with st.expander(title, expanded=bool(focus_label) or (mode == "Add trades manually")):
        if focus_label:
            fi, fb = st.columns([3, 1])
            fi.info(f"Showing the {len(shown):,} trade(s) behind the Dashboard's **{focus_label}** figure. "
                    "Fix any cell and press **Save changes**; the Dashboard recalculates.")
            if fb.button("Show all trades", width="stretch"):
                st.session_state.pop("tradebook_focus", None)
                st.rerun()
        st.caption("Closed trades and charges, most recent month first. Cells are editable: change a cell and "
                   "press **Save changes** — P&L, gross profit and ROI are recalculated for the rows you touched. "
                   "Tick **Remove** to delete rows, **To investment** to move a wrongly-entered trade to the "
                   "Investment Book. **Month** is editable too — pick any date in the right month to move a row there. "
                   "Only the computed columns are read-only.")
        order = shown.sort_values(["month", "buy_date"], ascending=[False, False], na_position="last").index
        grid = trades.loc[order, editable_cols + computed_cols].copy()
        grid.insert(0, "Remove", False)
        grid.insert(1, "To investment", False)
        cfg = trade_column_config()
        cfg["To investment"] = st.column_config.CheckboxColumn(
            "To investment", help="Tick rows that are really long-term investments (entered here by mistake), "
                                  "then press 'Move to Investment Book'.")
        edited = st.data_editor(
            grid, hide_index=True, width="stretch", height=min(len(grid) + 1, 14) * 35 + 3,
            disabled=["gross_profit", "roi"], key=f"trade_list_{state.version('capital_version')}_{focus_label or 'all'}",
            column_config=cfg,
        )
        r0, r1, rM, r2 = st.columns([1, 1, 1.4, 1.6])
        if r0.button("Save changes", type="primary", key="trades_save_edits"):
            updated, changed = apply_grid_edits(trades, order, edited, editable_cols)
            if not changed:
                st.info("No cells were changed.")
            else:
                updated = recompute_trades(updated, changed)
                save_trades(updated, state.get_frame("excluded"), state.get_meta().get("trades_source", "manual entry"))
                st.success(f"Saved edits to {len(changed)} row(s); profit and ROI recalculated.")
                st.rerun()
        if r1.button("Remove selected"):
            remove_mask = edited["Remove"].fillna(False).astype(bool).to_numpy()
            if not remove_mask.any():
                st.info("Tick at least one row first.")
            else:
                drop_idx = order[remove_mask]
                remaining = trades.drop(index=drop_idx).reset_index(drop=True)
                save_trades(remaining if not remaining.empty else None, state.get_frame("excluded"), state.get_meta().get("trades_source", ""))
                st.rerun()
        if rM.button("Move to Investment Book"):
            move_mask = edited["To investment"].fillna(False).astype(bool).to_numpy()
            if not move_mask.any():
                st.info("Tick **To investment** on at least one row first.")
            else:
                move_idx = order[move_mask]
                problems, new_entries, moved, notes = [], [], [], []
                for idx in move_idx:
                    row = trades.loc[idx]
                    stock = str(row.get("stock") or "").strip() or "UNKNOWN"
                    kind = str(row.get("entry_kind") or "trade")
                    qty = pd.to_numeric(pd.Series([row.get("qty")]), errors="coerce").iloc[0]
                    buy = pd.to_numeric(pd.Series([row.get("buy")]), errors="coerce").iloc[0]
                    sell = pd.to_numeric(pd.Series([row.get("sell")]), errors="coerce").iloc[0]
                    brokerage = pd.to_numeric(pd.Series([row.get("brokerage")]), errors="coerce").iloc[0]
                    brokerage = 0.0 if pd.isna(brokerage) else float(brokerage)
                    if kind == "charge":
                        problems.append(f"{stock}: a charge entry is not an investment — remove it instead.")
                        continue
                    if pd.isna(qty) or qty <= 0 or pd.isna(buy) or buy <= 0:
                        problems.append(f"{stock}: needs a Qty and a Buy price to become an investment lot.")
                        continue
                    buy_month = row.get("buy_date") if pd.notna(row.get("buy_date")) else row.get("month")
                    if pd.isna(buy_month):
                        problems.append(f"{stock}: has no Buy date or Month to place the purchase in.")
                        continue
                    buy_month = pd.Timestamp(buy_month).to_period("M").to_timestamp().date()
                    res = entry_from_form(buy_month, "EQUITY", stock, float(qty), float(buy))
                    if res.errors or res.entries is None or res.entries.empty:
                        problems.append(f"{stock}: {'; '.join(res.errors) or 'could not convert this row.'}")
                        continue
                    pieces = [res.entries]
                    has_sale = pd.notna(sell) and float(sell) > 0
                    if has_sale:
                        sale_month = row.get("sale_date") if pd.notna(row.get("sale_date")) else row.get("month")
                        sale_month = pd.Timestamp(sale_month).to_period("M").to_timestamp().date()
                        sres = sale_from_form(sale_month, "EQUITY", stock, float(qty), float(sell), brokerage)
                        if sres.errors or sres.entries is None:
                            problems.append(f"{stock}: purchase converts, but its sale leg failed: {'; '.join(sres.errors)}")
                            continue
                        pieces.append(sres.entries)
                        notes.append(f"{stock}: moved as a purchase **and** its sale (profit booked lands in the Investments dashboard).")
                    elif brokerage > 0:
                        notes.append(f"{stock}: brokerage ₹{brokerage:,.2f} was not carried over (investment lots store qty × price only).")
                    new_entries.append((idx, pd.concat(pieces, ignore_index=True)))
                    moved.append(stock)
                if problems:
                    for p_ in problems:
                        st.error(p_)
                    st.warning("Nothing was moved — fix the rows above (or untick them) and try again.")
                else:
                    portfolio = state.get_frame("portfolio")
                    frames = [portfolio] if portfolio is not None and not portfolio.empty else []
                    frames += [e for _, e in new_entries]
                    combined = pd.concat(frames, ignore_index=True)
                    state.put_frame("portfolio", combined)
                    state.put_meta({"portfolio_source": state.get_meta().get("portfolio_source", "") or "moved from Trading Book"})
                    state.bump("portfolio_version")
                    remaining = trades.drop(index=[i for i, _ in new_entries]).reset_index(drop=True)
                    save_trades(remaining if not remaining.empty else None, state.get_frame("excluded"),
                                state.get_meta().get("trades_source", ""))
                    st.session_state["tradebook_flash"] = (
                        [f"Moved {len(moved)} row(s) to the Investment Book: {', '.join(moved)}. "
                         "They are out of the Trading Book and its dashboard, and now sit under Entries saved."]
                        + notes)
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
st.page_link("screens/reports.py", label="Go to Dashboard Reports", icon="📊")
