"""Reports: Trading dashboard and Long Term Investment dashboard for the selected owner."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import state
from core.benchmarks import Z_COLUMN, cagr_table, comparison_table, get_monthly, period_label
from core.filters import plain_table, stock_month_filter
from core.formatting import inr, pct
from core.metrics import (breakdown, brokerage_table, cagr_from_monthly, capital_table, kpis, monthly_summary,
                          to_excel_bytes, yearly_summary, yearly_with_total)
from core.strategies import CHARGE_TYPE, NON_OPTION_TYPES, OTHER_TYPE, canonical
from core.portfolio import (ASSET_CLASSES, asset_class_summary, filter_entries, holdings, match_sales,
                            sales_summary, sector_allocation, sector_class_map, with_asset_class,
                            yearly_sales_summary)

owner = state.user_name()
st.title("Dashboard Reports")
st.caption(f"Portfolio owner: **{owner}**")

GREEN, RED, BLUE = "#2E7D32", "#C62828", "#1F4E79"
MARGIN = dict(t=50, b=20, l=10, r=10)

for _msg in st.session_state.pop("reports_flash", []):
    st.success(_msg)
trading_tab, monthly_tab, invest_tab = st.tabs(
    ["Yearly Trading Performance", "Trading Monthly performance", "Investments"])
_monthly_ready = False


def bar_signed(x, y, title, text=None, height=360, yaxis="₹"):
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=[GREEN if v >= 0 else RED for v in y],
                           text=text, textposition="outside" if text is not None else None,
                           hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>"))
    fig.update_layout(title=title, yaxis_title=yaxis, margin=MARGIN, height=height)
    return fig


EQUITY_TRADE_TYPES = {"Equity", "Equity Intraday", "Equity Delivery"}


def trade_category(row) -> str:
    """Equity / ETF / MF / Debt / Futures & Options / Charges, from the trade's type and
    (for cash trades) the stock's sector out of Stocks Management."""
    t = canonical(row.get("type"))
    if t == CHARGE_TYPE:
        return "Charges"
    if t == "Debt":
        return "Debt"
    if t in EQUITY_TRADE_TYPES or t == OTHER_TYPE or not t:
        blob = f"{row.get('sector', '')} {row.get('stock', '')}".upper()
        if "ETF" in blob or "BEES" in blob:
            return "ETF"
        if "MUTUAL" in blob or " MF" in f" {blob}":
            return "MF"
        return "Equity"
    return "Futures & Options"


CATEGORY_ORDER = ["Equity", "ETF", "MF", "Debt", "Futures & Options"]


def invest_sales_for_owner():
    """The current owner's Investment Book sales, matched with their LIFO/FIFO setting."""
    entries_ = state.get_frame("portfolio")
    meta_ = state.get_meta()
    method_ = str(meta_.get("sale_match_method", "lifo")).lower()
    if entries_ is None or entries_.empty:
        return pd.DataFrame(), method_
    _, inv_sales_ = match_sales(with_asset_class(entries_, meta_.get("asset_class_overrides", {})), method=method_)
    return inv_sales_, method_


# =================================================================== TRADING ==
DEFAULT_BENCH_SERIES = ["GOLD BEES", "SILVER BEES", "Nifty ROI", "BANK NIFTY ROI", "NIFTY IT ROI", "NASDAQ ROI", "DJI ROI"]


def monthly_table_frame(summary: pd.DataFrame, k: dict) -> pd.DataFrame:
    table = pd.DataFrame({
        "Month": summary["Month"],
        "Average of Capital": summary["Average of Capital"].map(inr),
        "Net Profit": summary["Net Profit"].map(inr),
        "Brokerage": summary["Brokerage"].map(inr),
        "Monthly ROI": summary["Monthly ROI"].map(pct),
        "Trades": summary["Trades"],
        "Win rate %": summary["Win rate"].map(lambda v: pct(v, 1)),
    })
    cap_mean = pd.to_numeric(summary["Average of Capital"], errors="coerce").mean()
    gp = summary["Net Profit"]
    total_row = pd.DataFrame([{
        "Month": "Grand Total",
        "Average of Capital": inr(cap_mean) if pd.notna(cap_mean) else "—",
        "Net Profit": inr(gp.sum()),
        "Brokerage": inr(pd.to_numeric(summary["Brokerage"], errors="coerce").sum()),
        "Monthly ROI": pct(summary["Monthly ROI"].sum(min_count=1)) if summary["Monthly ROI"].notna().any() else "—",
        "Trades": int(summary["Trades"].sum()),
        "Win rate %": pct(k["win_rate"], 1) if k.get("win_rate") is not None else "—",
    }])
    return pd.concat([table, total_row], ignore_index=True)


with trading_tab:
    _real = state.get_frame("trades")
    # Every sale recorded in the Investment Book books here as a settled Equity Delivery row,
    # so it flows into the yearly table, KPIs, monthly figures and the Delivery pivot.
    inv_sales_all, inv_method = invest_sales_for_owner()
    inv_method_label = inv_method.upper()
    if inv_sales_all is not None and not inv_sales_all.empty:
        _profit = pd.to_numeric(inv_sales_all["profit"], errors="coerce").fillna(0.0)
        _qty_s = pd.to_numeric(inv_sales_all["qty"], errors="coerce")
        _cost_s = pd.to_numeric(inv_sales_all["cost"], errors="coerce")
        _synth = pd.DataFrame({
            "month": pd.to_datetime(inv_sales_all["month"], errors="coerce").dt.to_period("M").dt.to_timestamp(),
            "buy_date": pd.to_datetime(inv_sales_all.get("first_buy"), errors="coerce"),
            "sale_date": pd.to_datetime(inv_sales_all["month"], errors="coerce"),
            "stock": inv_sales_all["stock"].astype(str),
            "type": "Equity Delivery",
            "qty": _qty_s,
            "buy": (_cost_s / _qty_s.where(_qty_s > 0)).round(2),
            "sell": pd.to_numeric(inv_sales_all["price"], errors="coerce"),
            "brokerage": 0.0,
            "gross_profit": _profit,
            "pl": _profit,
            "entry_kind": "trade",
            "source_sheet": "Investment Book",
            "_store_idx": -1,
        })
    else:
        _synth = pd.DataFrame()

    n_open = 0
    if _real is not None and not _real.empty:
        # Open positions never reach the dashboard: every figure, table, trade log and
        # download below is built from settled trades only.
        from core.parse import open_positions_mask
        _open_mask = open_positions_mask(_real)
        n_open = int(_open_mask.sum())
        _real = _real[~_open_mask].copy()
        _real["_store_idx"] = _real.index          # position in the stored trades frame, for removal
    else:
        _real = pd.DataFrame()
    trades = pd.concat([f for f in (_real, _synth) if not f.empty], ignore_index=True) if (not _real.empty or not _synth.empty) else _real

    if trades is None or trades.empty:
        if n_open:
            st.info(f"All {n_open:,} saved trade(s) are still open positions, so there is nothing settled to report yet. "
                    "They move into the Dashboard the moment they are squared off.")
            st.page_link("screens/trading_input.py", label="Go to Trading Book → Open positions", icon="📒")
        else:
            st.info("No trades loaded for this owner yet. Trades come from the Trading Book; "
                    "sales recorded in the Investment Book also book here as Equity Delivery rows.")
            st.page_link("screens/trading_input.py", label="Go to Trading Book", icon="📥")
    else:
        if True:
            if n_open:
                st.caption(f"{n_open} open position(s) are excluded from every figure here — including the trade log and "
                           "the Excel download — until squared off (Trading Book → Open positions).")
            if not _synth.empty:
                st.caption(f"{len(_synth):,} Investment Book sale(s) are booked here as Equity Delivery rows "
                           f"({inv_method_label}-matched cost basis) — they count in every figure below.")
            capital = state.get_frame("capital")
            excluded = state.get_frame("excluded")
            meta = state.get_meta()
            all_trades = trades

            yf, bf, _ = st.columns([1, 1.4, 1.6])
            basis_label = bf.radio("Year basis", ["Calendar (Jan–Dec)", "Financial (Apr–Mar)"], horizontal=True,
                                   key="year_basis", help="Applies to the Year filter, the yearly table and the benchmark comparison.")
            basis = "financial" if basis_label.startswith("Financial") else "calendar"
            trade_periods = period_label(all_trades["month"], basis)
            periods_available = list(pd.Series(trade_periods.values, index=all_trades["month"].values).dropna()
                                     .groupby(level=0).first().sort_index().unique())
            year_pick = yf.multiselect("Year", periods_available, placeholder="All years",
                                       help="Narrows the KPIs, monthly sections and breakdown. The yearly table always shows every year.")
            if year_pick:
                trades = all_trades[trade_periods.isin(year_pick).values]
            summary = monthly_summary(trades, capital)
            full_summary = summary if not year_pick else monthly_summary(all_trades, capital)
            k = kpis(summary, trades)

            st.caption(f"Source: {meta.get('trades_source', 'manual entry')} · {k['trades']:,} trades"
                       + (f" + {k['charges']:,} charge entries" if k.get("charges") else "") + f" · {k['months']} months"
                       + (f" · {', '.join(str(y) for y in year_pick)}" if year_pick else ""))

            _monthly_ready = True
            kpi_yearly = yearly_summary(summary, basis)
            avg_yearly_roi = pd.to_numeric(kpi_yearly["Yearly ROI"], errors="coerce").mean() if not kpi_yearly.empty else None
            if avg_yearly_roi is not None and pd.isna(avg_yearly_roi):
                avg_yearly_roi = None
            _ycagrs = []
            if not summary.empty:
                for _, grp in summary.groupby(period_label(summary["month"], basis), sort=False):
                    c = cagr_from_monthly(grp["Monthly ROI"])
                    if c is not None:
                        _ycagrs.append(c)
            avg_yearly_cagr = (sum(_ycagrs) / len(_ycagrs)) if _ycagrs else None

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Net profit", inr(k["net_profit"], prefix="₹"))
            c2.metric("Avg monthly ROI", f"{pct(k['avg_roi'])}%" if k["avg_roi"] is not None else "—",
                      delta=(f"CAGR {pct(k['cagr'])}%" if k.get("cagr") is not None else None), delta_color="off",
                      help=f"Simple average over the {k['months_with_roi']} month(s) that have a capital figure. "
                           "CAGR = the same monthly ROIs compounded and annualised: (∏(1 + ROI))^(12 ÷ months) − 1.")
            c3.metric("Avg yearly ROI", f"{pct(avg_yearly_roi)}%" if avg_yearly_roi is not None else "—",
                      delta=(f"CAGR {pct(avg_yearly_cagr)}%" if avg_yearly_cagr is not None else None), delta_color="off",
                      help=f"Average of the Yearly ROI figures below ({'FY Apr–Mar' if basis != 'calendar' else 'calendar'} years; "
                           "Yearly ROI = year's net profit ÷ its average monthly capital). "
                           "Avg yearly CAGR = each year's monthly ROIs compounded and annualised, averaged across years.")
            c4.metric("Win rate", f"{pct(k['win_rate'], 1)}%" if k["win_rate"] is not None else "—",
                      help="Share of trades with positive gross profit. Charge entries (brokerage, DP/AMC charges …) are not trades and are excluded.")
            c5.metric("Best month", k["best_month"][0], inr(k["best_month"][1]))
            c6.metric("Worst month", k["worst_month"][0], inr(k["worst_month"][1]))

            if summary["Monthly ROI"].isna().any():
                n = int(summary["Monthly ROI"].isna().sum())
                st.warning(f"{n} month(s) have no capital figure, so their ROI is blank. Add it on the Trading Book screen.")

            # ---------------------------------------------------- yearly (chart, then table)
            st.subheader("Yearly performance")
            yearly = yearly_summary(full_summary, basis)
            if yearly.empty or yearly["Yearly ROI"].isna().all():
                st.info("Yearly ROI needs monthly capital. Enter it on the Trading Book screen.")
            fig = go.Figure()
            fig.add_bar(name="Net profit (₹)", x=yearly["Year"].astype(str), y=yearly["Net Profit"],
                        marker_color=[GREEN if v >= 0 else RED for v in yearly["Net Profit"]],
                        text=yearly["Net Profit"].map(inr), textposition="outside",
                        hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>")
            fig.add_scatter(name="Yearly ROI (%)", x=yearly["Year"].astype(str), y=yearly["Yearly ROI"], yaxis="y2",
                            mode="lines+markers+text", text=yearly["Yearly ROI"].map(lambda v: pct(v, 0)),
                            textposition="top center", line=dict(color=BLUE, width=2),
                            hovertemplate="%{x}<br>ROI %{y:.1f}%<extra></extra>")
            fig.update_layout(title="Net profit and ROI by year", margin=MARGIN, height=380,
                              xaxis=dict(type="category"), yaxis=dict(title="₹"),
                              yaxis2=dict(title="%", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
                              legend=dict(orientation="h", y=-0.2))
            st.caption("**Click a year's bar** to open that year's trades in the Trading Book and check or fix the rows behind the figure.")
            yearly_event = st.plotly_chart(fig, width="stretch", key="yearly_chart",
                                           on_select="rerun", selection_mode="points")
            try:
                _pts = list(yearly_event.selection.points)
            except Exception:
                _pts = []
            if _pts:
                _label = str(_pts[0].get("x"))
                if "yearly_chart" in st.session_state:
                    del st.session_state["yearly_chart"]      # forget the click so the dashboard doesn't bounce back
                st.session_state["tradebook_focus"] = {"label": _label, "basis": basis}
                st.switch_page("screens/trading_input.py")
            yt = yearly_with_total(yearly)
            shown_y = pd.DataFrame({
                "Year": yt["Year"], "Investments": yt["Investments"].map(inr), "Net Profit": yt["Net Profit"].map(inr),
                "Yearly ROI": yt["Yearly ROI"].map(lambda v: pct(v, 0)), "Brokerage": yt["Brokerage"].map(inr), "Trades": yt["Trades"],
            })
            plain_table(shown_y, key="tbl_yearly")
            st.caption(("Financial years run April to March. " if basis == "financial" else "")
                       + "Investments = average of the year's monthly capital; Yearly ROI = Net Profit ÷ Investments × 100. "
                       "Grand Total averages Investments and ROI across years and sums the rest.")

            # ----------------------------------------- vs benchmarks (table, then one simple chart)
            def overall_bar(frame: pd.DataFrame, label_col: str, total_label: str, title: str, key: str) -> None:
                """One horizontal bar per series for the total/overall row; the owner's bar highlighted."""
                row = frame[frame[label_col] == total_label]
                if row.empty:
                    return
                values = row.drop(columns=[c for c in (label_col, "Months") if c in row]).iloc[0]
                values = pd.to_numeric(values, errors="coerce").dropna().sort_values()
                colors = [BLUE if name == Z_COLUMN else "#9FB3C8" for name in values.index]
                fig = go.Figure(go.Bar(x=values.values, y=[("My returns" if n == Z_COLUMN else n) for n in values.index],
                                       orientation="h", marker_color=colors, text=[pct(v) + "%" for v in values.values],
                                       textposition="outside", hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
                fig.update_layout(title=title, xaxis_title="%", margin=MARGIN, height=60 + 32 * len(values), showlegend=False)
                st.plotly_chart(fig, width="stretch", key=key)

            st.subheader("My returns vs benchmarks")
            bench_monthly = get_monthly()
            series_options = [c for c in bench_monthly.columns if c != "month"]
            default_series = [c for c in DEFAULT_BENCH_SERIES if c in series_options] or series_options[:3]
            picked = st.multiselect("Benchmarks to compare", series_options, default=default_series, key="cmp_series")
            cmp = comparison_table(full_summary, bench_monthly, basis, picked or series_options)
            if cmp.empty or cmp[Z_COLUMN].isna().all():
                st.info("Monthly ROI needs capital figures (Trading Book → Monthly capital) before it can be compared.")
            else:
                st.markdown("**Total return (sum of monthly %)**")
                display = cmp.copy()
                for col in display.columns[1:]:
                    display[col] = display[col].map(lambda v: pct(v) if pd.notna(v) else "")
                plain_table(display, key="tbl_benchmarks")
                overall_bar(cmp, "Period", "Grand Total", "Grand Total return, all listed periods (%)", "cmp_total_bar")

                st.markdown("**CAGR (compounded, annualised)**")
                cg = cagr_table(full_summary, bench_monthly, basis, picked or series_options)
                display_cg = cg.copy()
                for col in display_cg.columns:
                    if col not in ("Period", "Months"):
                        display_cg[col] = display_cg[col].map(lambda v: pct(v) if pd.notna(v) else "")
                plain_table(display_cg, key="tbl_benchmarks_cagr")
                overall_bar(cg, "Period", "Overall", "Overall CAGR, all listed months (%)", "cmp_cagr_bar")
                st.caption(f"{Z_COLUMN} and every benchmark use monthly % returns over the same months you have ROI, grouped by "
                           + ("financial year (Apr–Mar). " if basis == "financial" else "calendar year. ")
                           + "Total return sums the months; CAGR compounds them and annualises by 12 ÷ months (so a part-year is scaled to a full year). "
                           "Benchmark months are maintained on the Benchmarks screen.")

            # ------------------------------------------------------ breakdown (chart, then table)
            dimensions = [c for c in ("stock", "type") if c in trades]
            if dimensions:
                st.subheader("Breakdown")
                by = st.selectbox("Group by", dimensions, format_func=str.title)
                bd = breakdown(trades, by)
                top = bd.head(12)
                st.plotly_chart(bar_signed(top[by.title()].astype(str), top["Net Profit"], f"Net profit by {by} (top 12)", height=340),
                                width="stretch", key="breakdown_chart")
                shown_bd = bd.copy()
                shown_bd["Net Profit"] = shown_bd["Net Profit"].map(inr)
                shown_bd["Win rate"] = shown_bd["Win rate"].map(lambda v: pct(v, 1))
                if "Avg trade ROI" in shown_bd:
                    shown_bd["Avg trade ROI"] = shown_bd["Avg trade ROI"].map(pct)
                plain_table(shown_bd, key="tbl_breakdown")

            if st.radio("Trade log", ["Hide", "Show"], horizontal=True, key="radio_tradelog") == "Show":
                log = stock_month_filter(trades.copy(), key="rep_tradelog_filter")
                _tf1, _ = st.columns([1.2, 2.8])
                _type_opts = (sorted(log["type"].map(canonical).dropna().astype(str).replace("", pd.NA).dropna().unique())
                              if "type" in log.columns else [])
                type_pick = _tf1.selectbox("Filter by trade type", ["All types"] + list(_type_opts),
                                           key="rep_tradelog_type",
                                           help="E.g. Equity Delivery or Equity Intraday.")
                if type_pick != "All types" and "type" in log.columns:
                    log = log[log["type"].map(canonical) == type_pick]
                log["Month"] = log["month"].dt.strftime("%b-%y")
                lead = [c for c in ("Month", "stock", "type", "strike", "qty", "buy", "buy_date", "sell",
                                    "sale_date", "brokerage", "margin", "lot", "gross_profit", "roi",
                                    "entry_kind", "source_sheet") if c in log.columns or c == "Month"]
                keep = [c for c in lead if c in log.columns]
                if "stock" in log.columns:
                    log = log.sort_values(["stock", "Month"], na_position="last")
                _store_pos = log["_store_idx"].tolist() if "_store_idx" in log.columns else [-1] * len(log)
                disp = log[keep].reset_index(drop=True)
                for dcol in ("buy_date", "sale_date"):
                    if dcol in disp.columns:
                        disp[dcol] = pd.to_datetime(disp[dcol], errors="coerce").dt.strftime("%d-%b-%y")
                disp.insert(0, "Remove", False)
                log_edited = st.data_editor(
                    disp, hide_index=True, width="stretch",
                    height=min(len(disp) + 1, 20) * 35 + 3,
                    disabled=[c for c in disp.columns if c != "Remove"],
                    key=f"tradelog_grid_{len(disp)}_{hash(tuple(_store_pos)) & 0xffff}",
                    column_config={"Remove": st.column_config.CheckboxColumn(
                        "Remove", help="Tick and press 'Remove selected' — the trade is deleted from the "
                                       "Trading Book, so it leaves every figure here (yearly, monthly, pivots).")},
                )
                _gp_sum = float(pd.to_numeric(disp.get("gross_profit"), errors="coerce").fillna(0).sum())
                _bk_sum = float(pd.to_numeric(disp.get("brokerage"), errors="coerce").fillna(0).sum())
                st.markdown(f"**Total** — {len(disp):,} row(s) · Gross profit {inr(_gp_sum, prefix='₹')} · "
                            f"Brokerage {inr(_bk_sum, prefix='₹')}")
                if st.button("Remove selected", key="tradelog_remove"):
                    _rm = log_edited["Remove"].fillna(False).astype(bool).to_numpy()
                    if not _rm.any():
                        st.info("Tick **Remove** on at least one row first.")
                    else:
                        _picked = [_store_pos[i] for i in range(len(_store_pos)) if _rm[i]]
                        _synth_picked = [i for i in _picked if i == -1]
                        _real_picked = [i for i in _picked if i != -1]
                        if _synth_picked:
                            st.error(f"{len(_synth_picked)} ticked row(s) are Investment Book sales — remove the "
                                     "sale itself in **Investment Book → Record a sale → Sales recorded** and it "
                                     "leaves this dashboard too.")
                        if _real_picked:
                            _stored = state.get_frame("trades")
                            _remaining = _stored.drop(index=_real_picked).reset_index(drop=True)
                            state.put_frame("trades", _remaining if not _remaining.empty else None)
                            st.session_state["reports_flash"] = [
                                f"Removed {len(_real_picked)} trade(s) from the Trading Book — they are out of "
                                "every figure here (Yearly and Monthly performance, pivots, downloads)."]
                            st.rerun()
            if excluded is not None and not excluded.empty:
                if st.toggle(f"Show the {len(excluded)} rows excluded from monthly totals", key="tgl_excluded"):
                    exc = excluded.copy()
                    exc_total = {c: "" for c in exc.columns}
                    first_col = exc.columns[0]
                    exc_total[first_col] = "Total"
                    for num_col in ("gross_profit", "brokerage", "pl"):
                        if num_col in exc.columns:
                            exc_total[num_col] = round(float(pd.to_numeric(exc[num_col], errors="coerce").sum()), 2)
                    plain_table(pd.concat([exc, pd.DataFrame([exc_total])], ignore_index=True), key="tbl_excluded")

            st.subheader("Download")
            sheets = {"Yearly": yearly_with_total(yearly_summary(full_summary, basis)), "Monthly Summary": summary,
                      "Capital": capital_table(summary), "Brokerage": brokerage_table(summary)}
            if not cmp.empty:
                sheets["Vs benchmarks"] = cmp
                sheets["Vs benchmarks CAGR"] = cagr_table(full_summary, bench_monthly, basis, picked or series_options)
            for dim in dimensions:
                sheets[f"By {dim.title()}"] = breakdown(trades, dim)
            sheets["Trades"] = (trades.drop(columns=["_store_idx"], errors="ignore")
                                .assign(Month=trades["month"].dt.strftime("%b-%y")))
            if excluded is not None and not excluded.empty:
                sheets["Excluded"] = excluded
            d1, d2 = st.columns(2)
            d1.download_button("Download trading report (Excel)", to_excel_bytes(sheets), f"trading_report_{state.current_user()}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
            d2.download_button("Download monthly summary (CSV)", summary.drop(columns=["month"]).to_csv(index=False).encode(),
                               "monthly_summary.csv", "text/csv")


            # ================= collapsible analysis sections (bottom of the page) =================
            st.divider()
            _types = (trades["type"].map(canonical) if "type" in trades.columns
                      else pd.Series("", index=trades.index, dtype=str))
            _cats = (trades.apply(trade_category, axis=1) if not trades.empty
                     else pd.Series("", index=trades.index, dtype=str))

            with st.expander("Profit booked by stock", expanded=False):
                st.caption("Settled trades in the selected year(s), summed per stock — like the Excel pivots. "
                           "Intraday sums **Gross Profit**; Delivery sums **Profit/Loss** and includes the "
                           f"Investment Book sales booked above ({inv_method_label}-matched). "
                           "Each tab has its own stock/month filter.")

                def _stock_pivot(sub: pd.DataFrame, value_col: str, value_label: str, key: str) -> None:
                    sub = stock_month_filter(sub, key=f"{key}_filter")
                    if sub is None or sub.empty or "stock" not in sub.columns:
                        st.info("No trades of this type match the selection.")
                        return
                    vals = pd.to_numeric(sub[value_col], errors="coerce").fillna(0)
                    piv = (pd.DataFrame({"Stock": sub["stock"].astype(str), value_label: vals})
                           .groupby("Stock", as_index=False).sum()
                           .sort_values(value_label, ascending=False))
                    total = float(piv[value_label].sum())
                    shown = piv.copy()
                    shown[value_label] = shown[value_label].map(inr)
                    shown = pd.concat([shown, pd.DataFrame([{"Stock": "Grand Total", value_label: inr(total)}])],
                                      ignore_index=True)
                    plain_table(shown, key=key, full_height=len(shown) <= 35)

                tab_intra, tab_deliv = st.tabs(["Intraday", "Delivery"])
                with tab_intra:
                    _stock_pivot(trades[_types == "Equity Intraday"], "gross_profit",
                                 "Sum of Gross Profit (₹)", "tbl_pivot_intraday")
                with tab_deliv:
                    _sub = trades[_types == "Equity Delivery"].copy()
                    if not _sub.empty:
                        _plv = pd.to_numeric(_sub.get("pl"), errors="coerce")
                        _gpv = pd.to_numeric(_sub.get("gross_profit"), errors="coerce")
                        _sub["_deliv_profit"] = _plv.where(_plv.notna(), _gpv)
                    _stock_pivot(_sub, "_deliv_profit", "Sum of Profit/Loss (₹)", "tbl_pivot_delivery")

            with st.expander("Profit booked by year — Equity vs Futures & Options", expanded=False):
                _nc = trades[_cats != "Charges"] if not trades.empty else trades
                if _nc.empty:
                    st.info("No settled trades in the selected year(s).")
                else:
                    _cat_opts = [c for c in CATEGORY_ORDER if (_cats == c).any()]
                    comp_pick = st.multiselect("Categories", _cat_opts, placeholder="All categories",
                                               key="comp_cat_pick")
                    comp = pd.DataFrame({
                        "Year": period_label(_nc["month"], basis).astype(str),
                        "Category": _cats[_nc.index],
                        "profit": pd.to_numeric(_nc["gross_profit"], errors="coerce").fillna(0),
                    })
                    if comp_pick:
                        comp = comp[comp["Category"].isin(comp_pick)]
                    if comp.empty:
                        st.info("Nothing matches the category filter.")
                    else:
                        pivot = comp.pivot_table(index="Year", columns="Category", values="profit",
                                                 aggfunc="sum", fill_value=0.0)
                        col_order = [c for c in CATEGORY_ORDER if c in pivot.columns] + \
                                    [c for c in pivot.columns if c not in CATEGORY_ORDER]
                        pivot = pivot[col_order]
                        pivot["Total"] = pivot.sum(axis=1)
                        shown_c = pivot.reset_index()
                        gt = {"Year": "Grand Total", **{c: float(pivot[c].sum()) for c in pivot.columns}}
                        shown_c = pd.concat([shown_c, pd.DataFrame([gt])], ignore_index=True)
                        for c in shown_c.columns:
                            if c != "Year":
                                shown_c[c] = shown_c[c].map(inr)
                        plain_table(shown_c, key="tbl_year_composite", full_height=len(shown_c) <= 25)
                        st.caption("Gross profit summed per "
                                   + ("financial year. " if basis == "financial" else "calendar year. ")
                                   + "Cash-market trades split into Equity / ETF / MF / Debt by the stock's "
                                   "sector; option strategies and futures count as Futures & Options; "
                                   "Investment Book sales land under their stock's category. Standalone "
                                   "charge entries are not in this table.")

            with st.expander("KPIs by category", expanded=False):
                _kcat_opts = [c for c in CATEGORY_ORDER if (_cats == c).any()]
                kpi_pick = st.multiselect("Categories", _kcat_opts, placeholder="All categories",
                                          key="kpi_cat_pick")
                cat_rows = []
                for cat in (kpi_pick or _kcat_opts):
                    sub = trades[_cats == cat] if not trades.empty else trades
                    if sub.empty:
                        continue
                    s_sum = monthly_summary(sub, capital)
                    ck = kpis(s_sum, sub)
                    cys = yearly_summary(s_sum, basis)
                    c_avg_y = pd.to_numeric(cys["Yearly ROI"], errors="coerce").mean() if not cys.empty else None
                    c_avg_y = None if c_avg_y is None or pd.isna(c_avg_y) else float(c_avg_y)
                    c_cagrs = []
                    if not s_sum.empty:
                        for _, grp in s_sum.groupby(period_label(s_sum["month"], basis), sort=False):
                            c = cagr_from_monthly(grp["Monthly ROI"])
                            if c is not None:
                                c_cagrs.append(c)
                    c_avg_yc = sum(c_cagrs) / len(c_cagrs) if c_cagrs else None
                    cat_rows.append({
                        "Category": cat,
                        "Net profit": inr(ck["net_profit"], prefix="₹"),
                        "Avg monthly ROI": f"{pct(ck['avg_roi'])}%" if ck["avg_roi"] is not None else "—",
                        "CAGR": f"{pct(ck['cagr'])}%" if ck.get("cagr") is not None else "—",
                        "Avg yearly ROI": f"{pct(c_avg_y)}%" if c_avg_y is not None else "—",
                        "Avg yearly CAGR": f"{pct(c_avg_yc)}%" if c_avg_yc is not None else "—",
                        "Win rate": f"{pct(ck['win_rate'], 1)}%" if ck["win_rate"] is not None else "—",
                        "Best month": f"{ck['best_month'][0]} ({inr(ck['best_month'][1], prefix='₹')})",
                        "Worst month": f"{ck['worst_month'][0]} ({inr(ck['worst_month'][1], prefix='₹')})",
                    })
                if cat_rows:
                    plain_table(pd.DataFrame(cat_rows), key="tbl_kpis_by_category", full_height=True)
                    st.caption("Each row uses only that category's trades (Investment Book sales included under "
                               "their stock's category); ROI figures divide by the same monthly capital as the "
                               "overall KPIs. Standalone charge entries are excluded.")
                else:
                    st.info("No settled trades to break down in the selected year(s).")


with monthly_tab:
    if not _monthly_ready:
        st.info("Monthly figures appear once settled trades are loaded for this owner "
                "(year basis and Year filter are set on the Yearly Trading Performance tab).")
    else:
        st.caption(f"Source: {meta.get('trades_source', 'manual entry')} · settled trades only"
                   + (f" · years: {', '.join(str(y) for y in year_pick)}" if year_pick else "")
                   + (" · financial years (Apr–Mar)" if basis == "financial" else ""))
        # ------------------------------------- monthly (period selector, charts, table)
        st.subheader("Monthly performance")
        month_periods = list(pd.Series(period_label(summary["month"], basis).values, index=summary["month"].values)
                             .dropna().groupby(level=0).first().sort_index().unique())
        default_period = month_periods[-1:] if month_periods else []
        m_pick = st.multiselect("Months to show", month_periods, default=default_period, key=f"monthly_periods_{basis}",
                                placeholder="All months", help="Pick one or more years to keep the monthly table short.")
        msel = summary[period_label(summary["month"], basis).isin(m_pick).values] if m_pick else summary
        mk = kpis(msel, trades[period_label(trades["month"], basis).isin(m_pick).values] if m_pick else trades) if not msel.empty else {}
        left, right = st.columns(2)
        with left:
            st.plotly_chart(bar_signed(msel["Month"], msel["Net Profit"], "Net profit by month", text=msel["Net Profit"].map(inr)),
                            width="stretch", key="monthly_profit_chart")
        with right:
            roi = msel.dropna(subset=["Monthly ROI"])
            fig = go.Figure(go.Scatter(x=roi["Month"], y=roi["Monthly ROI"], mode="lines+markers",
                                       line=dict(color=BLUE, width=2), hovertemplate="%{x}<br>ROI %{y:.2f}%<extra></extra>"))
            fig.update_layout(title="Monthly ROI (%)", yaxis_title="%", margin=MARGIN, height=360)
            if roi.empty:
                fig.add_annotation(text="Enter capital on the Trading Book screen to see ROI", showarrow=False)
            st.plotly_chart(fig, width="stretch", key="monthly_roi_chart")
        if st.toggle(f"Show the monthly table ({len(msel)} months)", key="tgl_monthly"):
            monthly_table = monthly_table_frame(msel, mk)
            plain_table(monthly_table, key="tbl_monthly")
            st.caption("Grand Total: capital is the average of the months; profit, brokerage and trades are sums; ROI is the sum of monthly ROI.")

        # --------------------------------------- capital & charges (chart, then tables)
        st.subheader("Capital and charges")
        brk = pd.to_numeric(msel["Brokerage"], errors="coerce").fillna(0)
        fig = go.Figure(go.Bar(x=msel["Month"], y=brk, marker_color=BLUE, text=brk.map(inr), textposition="outside",
                               hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>"))
        fig.update_layout(title="Brokerage & charges by month", yaxis_title="₹", margin=MARGIN, height=340)
        st.plotly_chart(fig, width="stretch", key="brokerage_chart")
        if st.toggle(f"Show the capital and brokerage tables ({len(msel)} months)", key="tgl_capbrk"):
            p1, p2 = st.columns(2)
            cap_t = capital_table(msel)
            cap_t["Average of Capital"] = cap_t["Average of Capital"].map(inr)
            brk_t = brokerage_table(msel)
            brk_t["Brokerage"] = brk_t["Brokerage"].map(inr)
            with p1:
                plain_table(cap_t, key="tbl_capital")
            with p2:
                plain_table(brk_t, key="tbl_brokerage")

# ================================================================ INVESTMENT ==
def render_holdings(view: pd.DataFrame, heading: str, key: str) -> dict:
    """KPIs, holdings table, sector donut and top holdings for one slice. Returns sheets for export."""
    h = holdings(view)
    alloc = sector_allocation(view)
    total = float(view["cost"].sum())
    gifts = float(view["gift"].sum()) if "gift" in view else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total invested", inr(total, prefix="₹"))
    c2.metric("Stocks / schemes", f"{len(h)}")
    c3.metric("Sectors", f"{len(alloc)}")
    c4.metric("Gifted", inr(gifts, prefix="₹"), help="Sum of GIFT AMOUNT in the holdings shown.")

    st.subheader(heading)
    left, right = st.columns(2)
    with left:
        fig = go.Figure(go.Pie(labels=alloc["Sector"], values=alloc["Cost"], hole=0.45,
                               hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>"))
        fig.update_layout(title="Allocation by sector", margin=MARGIN, height=380, legend=dict(orientation="h", y=-0.1))
        st.plotly_chart(fig, width="stretch", key=f"{key}_sector_pie")
    with right:
        top = h.head(12)
        fig = go.Figure(go.Bar(x=top["Stock"], y=top["% Investment"], marker_color=BLUE,
                               text=top["% Investment"].map(pct), textposition="outside", customdata=top["Cost"],
                               hovertemplate="%{x}<br>%{y:.2f}% · ₹%{customdata:,.0f}<extra></extra>"))
        fig.update_layout(title="Top holdings (% of this class)", yaxis_title="%", margin=MARGIN, height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_top_bar")

    h_sorted = h.sort_values("Cost", ascending=False, na_position="last")
    h_shown = h_sorted
    shown = h_shown.copy()
    shown["Qty"] = shown["Qty"].map(lambda v: inr(v) if pd.notna(v) else "—")
    shown["Buy"] = shown["Buy"].map(lambda v: inr(v) if pd.notna(v) else "—")
    shown["Cost"] = shown["Cost"].map(inr)
    shown["% Investment"] = shown["% Investment"].map(pct)
    shown["Gift"] = shown["Gift"].map(lambda v: inr(v) if v else "")
    shown_total = float(pd.to_numeric(h_shown["Cost"], errors="coerce").sum())
    shown_gifts = float(pd.to_numeric(h_shown["Gift"], errors="coerce").fillna(0).sum()) if "Gift" in h_shown else 0.0
    total_row = pd.DataFrame([{"Stock": "Grand Total", "Sector": "", "Qty": "", "Buy": "",
                               "Cost": inr(shown_total),
                               "% Investment": pct(shown_total / total * 100) if total else "100.00",
                               "Gift": inr(shown_gifts) if shown_gifts else ""}])
    shown = pd.concat([shown, total_row], ignore_index=True)
    plain_table(shown, key=f"tbl_{key}_holdings")

    sec = alloc.sort_values("Cost", ascending=False, na_position="last").copy()
    sec["Cost"] = sec["Cost"].map(inr)
    sec["% Investment"] = sec["% Investment"].map(pct)
    if st.toggle("Show the sector table", key=f"tgl_{key}_sectors"):
        plain_table(sec, key=f"tbl_{key}_sectors")
    if st.toggle("Show all entries (as uploaded)", key=f"tgl_{key}_entries"):
        raw_view = stock_month_filter(view.copy(), key=f"rep_{key}_entries_filter")
        if "cost" in raw_view.columns:
            raw_view = raw_view.sort_values("cost", ascending=False, na_position="last")
        raw_view["month"] = raw_view["month"].dt.strftime("%b-%y")
        plain_table(raw_view, key=f"tbl_{key}_entries")
    return {f"{heading[:20]} holdings": h, f"{heading[:20]} sectors": alloc}


with invest_tab:
    from core.sips import run_autopost

    posted = run_autopost()
    if posted:
        st.success(f"SIP auto-post: added {posted} instalment(s) that fell due (plans are managed on Investment Book).")
    entries = state.get_frame("portfolio")
    if entries is None or entries.empty:
        st.info("No long-term holdings loaded for this owner yet.")
        st.page_link("screens/portfolio_input.py", label="Go to Investment Book", icon="📥")
    else:
        overrides = state.get_meta().get("asset_class_overrides", {})
        classified_all = with_asset_class(entries, overrides)
        inv_method = str(state.get_meta().get("sale_match_method", "lifo")).lower()
        inv_method_label = inv_method.upper()
        remaining_all, sales_all = match_sales(classified_all, method=inv_method)
        classified = remaining_all            # holdings views use what is still held

        years = sorted(int(y) for y in classified_all["month"].dt.year.dropna().unique())
        sectors = sorted(classified_all["sector"].dropna().unique())
        months = [m for m in classified_all.sort_values("month")["month"].dt.strftime("%b-%y").dropna().unique()]
        f1, f2, f3 = st.columns(3)
        year_pick = f1.multiselect("Year", years, placeholder="All years")
        sector_pick = f2.multiselect("Sectors", sectors, placeholder="All sectors")
        month_pick = f3.multiselect("Month", months, placeholder="All months")
        view = filter_entries(classified, year_pick, sector_pick, month_pick)
        sales_view = filter_entries(sales_all, year_pick, sector_pick, month_pick) if not sales_all.empty else sales_all

        with st.expander("Asset class rules (which sectors count as ETF, Equity MF, Debt or Liquid Fund)"):
            st.caption("Everything not listed here is Equity. Rules are saved for this owner; new sectors are "
                       "classified automatically from their name until you change them here.")
            current_map = sector_class_map(classified_all, overrides)
            all_sectors = sorted(current_map)
            picks = {}
            cols = st.columns(len(ASSET_CLASSES) - 1)
            for col, cls in zip(cols, ASSET_CLASSES[1:]):
                picks[cls] = col.multiselect(cls, all_sectors, default=[s for s in all_sectors if current_map[s] == cls],
                                             key=f"class_pick_{cls}")
            chosen = {}
            for cls, secs in picks.items():
                for sec in secs:
                    if sec in chosen:
                        st.error(f"{sec} is listed under both {chosen[sec]} and {cls}; pick one.")
                    chosen[sec] = cls
            new_overrides = {sec: chosen.get(sec, "Equity") for sec in all_sectors}
            if st.button("Save asset class rules") and new_overrides != {k: current_map[k] for k in all_sectors}:
                state.put_meta({"asset_class_overrides": new_overrides})
                st.rerun()

        st.subheader(f"{owner} · Investment Book" + (f" · {', '.join(str(y) for y in year_pick)}" if year_pick else ""))
        n_sell_rows = int((classified_all["side"] == "sell").sum()) if "side" in classified_all else 0
        n_buy_rows = len(classified_all) - n_sell_rows
        buy_cost_total = float(classified_all.loc[classified_all["side"] != "sell", "cost"].sum()) if "side" in classified_all else float(classified_all["cost"].sum())
        st.caption(f"On file for {owner}: {n_buy_rows:,} purchase rows worth {inr(buy_cost_total, prefix='₹')}"
                   + (f" and {n_sell_rows:,} sale rows" if n_sell_rows else "")
                   + ". If an upload is missing from these numbers, it never imported — re-check Investment Book → Upload → Import.")
        buys_all = classified_all[classified_all["side"] != "sell"] if "side" in classified_all else classified_all
        if not buys_all.empty:
            qty_ok = (pd.to_numeric(buys_all["qty"], errors="coerce") > 0) if "qty" in buys_all.columns else pd.Series(False, index=buys_all.index)
            cost_ok = (pd.to_numeric(buys_all["cost"], errors="coerce") > 0) if "cost" in buys_all.columns else pd.Series(False, index=buys_all.index)
            no_qty, no_cost = int((~qty_ok).sum()), int((~cost_ok).sum())
            if no_qty or no_cost:
                st.warning(f"{no_qty:,} purchase rows have no usable Qty and {no_cost:,} no usable Cost — the import "
                           "read those columns as blank. Such rows are kept as holdings but carry no value and cannot "
                           "be matched to sales. Open Investment Book → Entries saved to inspect them, or re-import "
                           "after checking the sheet's Qty/Buy/Cost headers.")
        inv_sheets = {}
        summary = asset_class_summary(view)
        if view.empty:
            if not sales_all.empty and remaining_all.empty:
                st.info("Nothing is currently held: every purchase has been sold. The profit booked is below.")
            elif not sales_all.empty:
                st.info("No remaining holdings match these filters (sales may have consumed them). "
                        "Profit booked is below; clear a filter to see other holdings.")
            else:
                st.warning("No holdings match these filters. Clear a filter above to see more.")
        else:
            total_all = float(view["cost"].sum())
            o2, o1 = st.columns([1, 1])
            with o1:
                shown = summary.copy()
                shown["Cost"] = shown["Cost"].map(inr)
                shown["% Investment"] = shown["% Investment"].map(pct)
                shown["Gift"] = shown["Gift"].map(lambda v: inr(v) if v else "")
                total_row = pd.DataFrame([{"Asset class": "Grand Total", "Holdings": int(view["stock"].nunique()),
                                           "Cost": inr(total_all), "% Investment": "100.00",
                                           "Gift": inr(view["gift"].sum()) if "gift" in view and view["gift"].sum() else ""}])
                plain_table(pd.concat([shown, total_row], ignore_index=True), key="tbl_class_overview",
                             full_height=True)
            with o2:
                fig = go.Figure(go.Pie(labels=summary["Asset class"], values=summary["Cost"], hole=0.45,
                                       hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>"))
                fig.update_layout(title="Allocation by asset class", margin=MARGIN, height=300, legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(fig, width="stretch", key="asset_class_pie")
            inv_sheets["Asset classes"] = summary

        if not view.empty:
            class_tabs = st.tabs(ASSET_CLASSES)
            for tab, cls in zip(class_tabs, ASSET_CLASSES):
                with tab:
                    slice_ = view[view["asset_class"] == cls]
                    if slice_.empty:
                        st.info(f"No {cls} holdings in the current selection.")
                    else:
                        inv_sheets.update(render_holdings(slice_, f"{cls}", key=cls.replace(" ", "_").lower()))
            inv_sheets["Holdings (remaining)"] = view.assign(Month=view["month"].dt.strftime("%b-%y"))
        inv_sheets["All entries"] = classified_all.assign(Month=classified_all["month"].dt.strftime("%b-%y"))

        # Profit booked on sales moved to Yearly Trading Performance -> Profit booked by stock -> Delivery.
        st.caption("Looking for **Profit booked on sales**? It now lives under "
                   "**Yearly Trading Performance → Profit booked by stock → Delivery**, together with the "
                   "delivery trades from the Trading Book.")
        if sales_view is not None and not sales_view.empty:
            inv_sheets["Sales"] = sales_view            # the Excel download still carries the sales sheets
            _ysum_dl = yearly_sales_summary(sales_view)
            if not _ysum_dl.empty:
                inv_sheets["Sales by year"] = _ysum_dl

                st.subheader("Download")
        st.download_button("Download investment report (Excel)", to_excel_bytes(inv_sheets),
                           f"investment_report_{state.current_user()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
