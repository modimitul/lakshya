"""Reports: Trading dashboard and Long Term Investment dashboard for the selected owner."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import state
from core.benchmarks import BENCHMARK_COLUMNS, Z_COLUMN, normalise_table, with_grand_total
from core.formatting import inr, pct
from core.metrics import breakdown, brokerage_table, capital_table, kpis, monthly_summary, to_excel_bytes
from core.portfolio import filter_entries, holdings, sector_allocation

owner = state.user_name()
st.title("Dashboards")
st.caption(f"Portfolio owner: **{owner}**")

GREEN, RED, BLUE = "#2E7D32", "#C62828", "#1F4E79"
MARGIN = dict(t=50, b=20, l=10, r=10)

trading_tab, invest_tab = st.tabs(["Trading", "Investments"])


def bar_signed(x, y, title, text=None, height=360, yaxis="₹"):
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=[GREEN if v >= 0 else RED for v in y],
                           text=text, textposition="outside" if text is not None else None,
                           hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>"))
    fig.update_layout(title=title, yaxis_title=yaxis, margin=MARGIN, height=height)
    return fig


# =================================================================== TRADING ==
with trading_tab:
    trades = state.get_frame("trades")
    if trades is None or trades.empty:
        st.info("No trades loaded for this owner yet.")
        st.page_link("screens/trading_input.py", label="Go to Trading Book", icon="📥")
    else:
        capital = state.get_frame("capital")
        excluded = state.get_frame("excluded")
        summary = monthly_summary(trades, capital)
        k = kpis(summary, trades)
        meta = state.get_meta()

        st.caption(f"Source: {meta.get('trades_source', 'manual entry')} · {k['trades']:,} trades · {k['months']} months")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Net profit", inr(k["net_profit"], prefix="₹"))
        c2.metric("Avg monthly ROI", f"{pct(k['avg_roi'])}%" if k["avg_roi"] is not None else "—",
                  help=f"Simple average over the {k['months_with_roi']} month(s) that have a capital figure.")
        c3.metric("Win rate", f"{pct(k['win_rate'], 1)}%" if k["win_rate"] is not None else "—")
        c4.metric("Best month", k["best_month"][0], inr(k["best_month"][1]))
        c5.metric("Worst month", k["worst_month"][0], inr(k["worst_month"][1]))

        if summary["Monthly ROI"].isna().any():
            n = int(summary["Monthly ROI"].isna().sum())
            st.warning(f"{n} month(s) have no capital figure, so their ROI is blank. Add it on the Trading Book screen.")

        # ---- monthly table
        st.subheader("Monthly performance")
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
        total_row = pd.DataFrame([{
            "Month": "Grand Total",
            "Average of Capital": inr(cap_mean) if pd.notna(cap_mean) else "—",
            "Net Profit": inr(summary["Net Profit"].sum()),
            "Brokerage": inr(pd.to_numeric(summary["Brokerage"], errors="coerce").sum()),
            "Monthly ROI": pct(summary["Monthly ROI"].sum(min_count=1)) if summary["Monthly ROI"].notna().any() else "—",
            "Trades": int(summary["Trades"].sum()),
            "Win rate %": pct(k["win_rate"], 1) if k["win_rate"] is not None else "—",
        }])
        monthly_table = pd.concat([table, total_row], ignore_index=True)
        st.dataframe(monthly_table, hide_index=True, width="stretch", height=(len(monthly_table) + 1) * 35 + 3)
        st.caption("Grand Total: capital is the average of the months; profit, brokerage and trades are sums; ROI is the sum of monthly ROI.")

        left, right = st.columns(2)
        with left:
            st.plotly_chart(bar_signed(summary["Month"], summary["Net Profit"], "Net profit by month",
                                       text=summary["Net Profit"].map(inr)), width="stretch")
        with right:
            roi = summary.dropna(subset=["Monthly ROI"])
            fig = go.Figure(go.Scatter(x=roi["Month"], y=roi["Monthly ROI"], mode="lines+markers",
                                       line=dict(color=BLUE, width=2), hovertemplate="%{x}<br>ROI %{y:.2f}%<extra></extra>"))
            fig.update_layout(title="Monthly ROI (%)", yaxis_title="%", margin=MARGIN, height=360)
            if roi.empty:
                fig.add_annotation(text="Enter capital on the Trading Book screen to see ROI", showarrow=False)
            st.plotly_chart(fig, width="stretch")

        # ---- capital & brokerage pivots
        st.subheader("Capital and charges")
        p1, p2, p3 = st.columns([1, 1, 2])
        cap_t = capital_table(summary)
        cap_t["Average of Capital"] = cap_t["Average of Capital"].map(inr)
        p1.dataframe(cap_t, hide_index=True, width="stretch", height=(len(cap_t) + 1) * 35 + 3)
        brk_t = brokerage_table(summary)
        brk_t["Brokerage"] = brk_t["Brokerage"].map(inr)
        p2.dataframe(brk_t, hide_index=True, width="stretch", height=(len(brk_t) + 1) * 35 + 3)
        with p3:
            brk = pd.to_numeric(summary["Brokerage"], errors="coerce").fillna(0)
            fig = go.Figure(go.Bar(x=summary["Month"], y=brk, marker_color=BLUE, text=brk.map(inr), textposition="outside",
                                   hovertemplate="%{x}<br>₹%{y:,.0f}<extra></extra>"))
            fig.update_layout(title="Brokerage & charges by month", yaxis_title="₹", margin=MARGIN, height=380)
            st.plotly_chart(fig, width="stretch")

        # ---- annual ROI vs benchmarks
        st.subheader("Annual ROI % vs benchmarks")
        bench = state.get_frame("benchmarks")
        if bench is None or bench.empty or normalise_table(bench).drop(columns="Year").isna().all().all():
            st.info("No annual figures yet. Enter them under Trading Book → 3. Annual ROI and benchmarks.")
        else:
            bench = normalise_table(bench)
            shown = with_grand_total(bench)
            display = shown.copy()
            for col in display.columns[1:]:
                display[col] = display[col].map(lambda v: pct(v) if pd.notna(v) else "")
            st.dataframe(display, hide_index=True, width="stretch", height=(len(display) + 1) * 35 + 3)

            series_options = [c for c in bench.columns if c != "Year" and bench[c].notna().any()]
            default = [c for c in (Z_COLUMN, "Nifty ROI%") if c in series_options] or series_options[:2]
            picked = st.multiselect("Series to chart", series_options, default=default)
            if picked:
                fig = go.Figure()
                for col in picked:
                    fig.add_bar(name=col, x=bench["Year"].astype(str), y=bench[col].astype(float),
                                hovertemplate="%{x}: %{y:.2f}%<extra>" + col + "</extra>")
                fig.update_layout(barmode="group", title="Annual return by year (%)", yaxis_title="%", margin=MARGIN, height=400,
                                  legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig, width="stretch")

        # ---- breakdown
        dimensions = [c for c in ("stock", "type") if c in trades]
        if dimensions:
            st.subheader("Breakdown")
            by = st.selectbox("Group by", dimensions, format_func=str.title)
            bd = breakdown(trades, by)
            shown_bd = bd.copy()
            shown_bd["Net Profit"] = shown_bd["Net Profit"].map(inr)
            shown_bd["Win rate"] = shown_bd["Win rate"].map(lambda v: pct(v, 1))
            if "Avg trade ROI" in shown_bd:
                shown_bd["Avg trade ROI"] = shown_bd["Avg trade ROI"].map(pct)
            st.dataframe(shown_bd, hide_index=True, width="stretch", height=min(len(shown_bd) + 1, 13) * 35 + 3)
            top = bd.head(12)
            st.plotly_chart(bar_signed(top[by.title()].astype(str), top["Net Profit"], f"Net profit by {by} (top 12)", height=340),
                            width="stretch")

        with st.expander("Trade log"):
            f1, f2 = st.columns(2)
            month_pick = f1.multiselect("Months", summary["Month"].tolist())
            stock_pick = f2.multiselect("Stocks", sorted(trades["stock"].dropna().unique()) if "stock" in trades else [])
            log = trades.copy()
            log["Month"] = log["month"].dt.strftime("%b-%y")
            if month_pick:
                log = log[log["Month"].isin(month_pick)]
            if stock_pick:
                log = log[log["stock"].isin(stock_pick)]
            st.dataframe(log.drop(columns=["month"]), hide_index=True, width="stretch")
        if excluded is not None and not excluded.empty:
            with st.expander(f"Excluded from monthly totals ({len(excluded)} rows)"):
                st.dataframe(excluded, hide_index=True, width="stretch")

        st.subheader("Download")
        sheets = {"Monthly Summary": summary, "Capital": capital_table(summary), "Brokerage": brokerage_table(summary)}
        if bench is not None and not bench.empty:
            sheets["Annual ROI"] = with_grand_total(bench)
        for dim in dimensions:
            sheets[f"By {dim.title()}"] = breakdown(trades, dim)
        sheets["Trades"] = trades.assign(Month=trades["month"].dt.strftime("%b-%y"))
        if excluded is not None and not excluded.empty:
            sheets["Excluded"] = excluded
        d1, d2 = st.columns(2)
        d1.download_button("Download trading report (Excel)", to_excel_bytes(sheets), f"trading_report_{state.current_user()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        d2.download_button("Download monthly summary (CSV)", summary.drop(columns=["month"]).to_csv(index=False).encode(),
                           "monthly_summary.csv", "text/csv")

# ================================================================ INVESTMENT ==
with invest_tab:
    entries = state.get_frame("portfolio")
    if entries is None or entries.empty:
        st.info("No long-term holdings loaded for this owner yet.")
        st.page_link("screens/portfolio_input.py", label="Go to Investment Book", icon="📥")
    else:
        years = sorted(int(y) for y in entries["month"].dt.year.dropna().unique())
        sectors = sorted(entries["sector"].dropna().unique())
        months = [m for m in entries.sort_values("month")["month"].dt.strftime("%b-%y").dropna().unique()]
        f1, f2, f3 = st.columns(3)
        year_pick = f1.multiselect("Year", years, placeholder="All years")
        sector_pick = f2.multiselect("Sectors", sectors, placeholder="All sectors")
        month_pick = f3.multiselect("Month", months, placeholder="All months")
        view = filter_entries(entries, year_pick, sector_pick, month_pick)

        if view.empty:
            st.warning("No holdings match these filters.")
        else:
            h = holdings(view)
            alloc = sector_allocation(view)
            total = float(view["cost"].sum())
            gifts = float(view["gift"].sum()) if "gift" in view else 0.0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total invested", inr(total, prefix="₹"))
            c2.metric("Stocks", f"{len(h)}")
            c3.metric("Sectors", f"{len(alloc)}")
            c4.metric("Gifted", inr(gifts, prefix="₹"), help="Sum of GIFT AMOUNT in the selected holdings.")

            title_bits = [owner, "Investment Book"] + ([", ".join(str(y) for y in year_pick)] if year_pick else [])
            st.subheader(" · ".join(title_bits))
            shown = h.copy()
            shown["Qty"] = shown["Qty"].map(lambda v: inr(v) if pd.notna(v) else "—")
            shown["Buy"] = shown["Buy"].map(lambda v: inr(v) if pd.notna(v) else "—")
            shown["Cost"] = shown["Cost"].map(inr)
            shown["% Investment"] = shown["% Investment"].map(pct)
            shown["Gift"] = shown["Gift"].map(lambda v: inr(v) if v else "")
            total_row = pd.DataFrame([{"Stock": "Grand Total", "Sector": "", "Qty": "", "Buy": "",
                                       "Cost": inr(total), "% Investment": "100.00", "Gift": inr(gifts) if gifts else ""}])
            shown = pd.concat([shown, total_row], ignore_index=True)
            st.dataframe(shown, hide_index=True, width="stretch", height=min(len(shown) + 1, 22) * 35 + 3)

            left, right = st.columns([1, 1])
            with left:
                fig = go.Figure(go.Pie(labels=alloc["Sector"], values=alloc["Cost"], hole=0.45,
                                       hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>"))
                fig.update_layout(title="Allocation by sector", margin=MARGIN, height=380, legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(fig, width="stretch")
            with right:
                top = h.head(12)
                fig = go.Figure(go.Bar(x=top["Stock"], y=top["% Investment"], marker_color=BLUE,
                                       text=top["% Investment"].map(pct), textposition="outside",
                                       hovertemplate="%{x}<br>%{y:.2f}% · ₹%{customdata:,.0f}<extra></extra>", customdata=top["Cost"]))
                fig.update_layout(title="Top holdings (% of investment)", yaxis_title="%", margin=MARGIN, height=380)
                st.plotly_chart(fig, width="stretch")

            sec = alloc.copy()
            sec["Cost"] = sec["Cost"].map(inr)
            sec["% Investment"] = sec["% Investment"].map(pct)
            with st.expander("Sector table"):
                st.dataframe(sec, hide_index=True, width="stretch")
            with st.expander("All entries (as uploaded)"):
                raw_view = view.copy()
                raw_view["month"] = raw_view["month"].dt.strftime("%b-%y")
                st.dataframe(raw_view, hide_index=True, width="stretch")

            st.subheader("Download")
            inv_sheets = {"Holdings": h, "Sectors": alloc, "Entries": view.assign(Month=view["month"].dt.strftime("%b-%y"))}
            st.download_button("Download investment report (Excel)", to_excel_bytes(inv_sheets),
                               f"investment_report_{state.current_user()}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
