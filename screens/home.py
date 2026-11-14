"""Home: status for every owner, admin family dashboards, owner management, how the numbers work."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import APP_NAME, APP_TAGLINE, state, store
from core.benchmarks import period_label
from core.filters import plain_table
from core.formatting import inr, pct
from core.metrics import cagr_from_monthly, kpis, monthly_summary, months_in, settled_only, yearly_summary
from core.portfolio import asset_class_summary, match_sales, with_asset_class

CAP_ORDER = ["Large cap", "Mid cap", "Small cap", "Unclassified"]
CAP_COLORS = {"Large cap": "#1565C0", "Mid cap": "#42A5F5", "Small cap": "#90CAF9", "Unclassified": "#B0BEC5"}


def _donut(labels, values, title, key, colors=None, clickable=False):
    fig = go.Figure(go.Pie(labels=list(labels), values=list(values), hole=0.45,
                           marker=(dict(colors=colors) if colors else None),
                           hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>"))
    fig.update_layout(title=title, margin=dict(l=10, r=10, t=40, b=10), height=360,
                      legend=dict(orientation="h", y=-0.1))
    if clickable:
        return st.plotly_chart(fig, width="stretch", key=key, on_select="rerun", selection_mode="points")
    st.plotly_chart(fig, width="stretch", key=key)
    return None


def _with_caps(equity: pd.DataFrame) -> pd.DataFrame:
    """Add a 'cap' column (Large/Mid/Small cap from Stocks Management, else Unclassified)."""
    stock_list = store.load_frame("_shared", "stocks")
    cap_map = {}
    if stock_list is not None and {"stock", "marketcap"} <= set(stock_list.columns):
        cap_map = {str(r["stock"]).strip().upper(): (str(r["marketcap"]).strip() or "Unclassified")
                   for _, r in stock_list.iterrows()}
    equity = equity.copy()
    equity["cap"] = equity["stock"].astype(str).str.strip().str.upper().map(
        lambda stk: cap_map.get(stk) or "Unclassified")
    return equity


def cap_pie_with_table(equity: pd.DataFrame, key: str, title: str) -> None:
    """Marketcap donut for Equity holdings; clicking a slice lists that cap's stocks below."""
    if equity is None or equity.empty:
        st.info("No Equity-class holdings yet.")
        return
    equity = _with_caps(equity)
    cap_sum = equity.groupby("cap")["cost"].sum()
    order = [c for c in CAP_ORDER if c in cap_sum.index]
    cap_sum = cap_sum.reindex(order)
    fig = go.Figure(go.Pie(labels=list(cap_sum.index), values=list(cap_sum.values), hole=0.45,
                           marker=dict(colors=[CAP_COLORS[c] for c in cap_sum.index]),
                           hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>"))
    fig.update_layout(title=title, margin=dict(l=10, r=10, t=40, b=10), height=360,
                      legend=dict(orientation="h", y=-0.1))
    label = None
    try:
        from streamlit_plotly_events import plotly_events
        clicked = plotly_events(fig, click_event=True, override_height=360, key=key)
        if clicked:
            pn = clicked[0].get("pointNumber")
            if pn is not None and 0 <= int(pn) < len(cap_sum.index):
                label = str(cap_sum.index[int(pn)])
    except Exception:
        st.plotly_chart(fig, width="stretch", key=f"{key}_fallback")
    st.caption("**Click a slice** to list that marketcap's stocks below."
               + (" Unclassified = stocks without a Marketcap in Stocks Management." if "Unclassified" in cap_sum.index else ""))
    if not label or label not in cap_sum.index:
        return
    sub = equity[equity["cap"] == label]
    by_stock = (sub.groupby("stock").agg(Sector=("sector", "first"), Invested=("cost", "sum"))
                .reset_index().rename(columns={"stock": "Stock"})
                .sort_values("Invested", ascending=False))
    cap_total = float(by_stock["Invested"].sum())
    st.markdown(f"**{label} stocks** ({len(by_stock)})")
    shown = by_stock.copy()
    shown["% of cap"] = (shown["Invested"] / cap_total * 100).map(lambda v: pct(v, 1) + "%") if cap_total else "—"
    shown["Invested"] = shown["Invested"].map(lambda v: inr(v, prefix="₹"))
    shown = pd.concat([shown, pd.DataFrame([{"Stock": "Grand Total", "Sector": "",
                                             "Invested": inr(cap_total, prefix="₹"), "% of cap": "100.0%"}])],
                      ignore_index=True)
    plain_table(shown, key=f"{key}_table", full_height=len(shown) <= 25)


st.title(APP_NAME)
st.caption(APP_TAGLINE)

users = state.users()
current = state.current_user()
_admin = state.is_admin()
if not _admin:
    users_shown = [u for u in users if u["slug"] == st.session_state.get("signed_in_as")]
else:
    users_shown = users

cols = st.columns(min(max(len(users_shown), 1), 4))
for i, u in enumerate(users_shown):
    trades = state.get_frame("trades", u["slug"])
    portfolio = state.get_frame("portfolio", u["slug"])
    capital = state.get_frame("capital", u["slug"])
    with cols[i % len(cols)]:
        with st.container(border=True):
            st.markdown(f"**{u['name']}**" + ("  ·  selected" if u["slug"] == current else "") + ("  ·  default" if u["slug"] == state.default_owner() else ""))
            if trades is None or trades.empty:
                st.write("Trading: no trades yet")
            else:
                filled = int(capital["Capital"].notna().sum()) if capital is not None and not capital.empty else 0
                st.write(f"Trading: {len(trades):,} trades, {len(months_in(trades))} months, capital entered for {filled} of {len(months_in(trades))}")
            if portfolio is None or portfolio.empty:
                st.write("Long term: no holdings yet")
            else:
                _m = str(state.get_meta(u["slug"]).get("sale_match_method", "lifo")).lower()
                _rem, _ = match_sales(portfolio, method=_m)
                _n_stk = int(_rem["stock"].nunique()) if not _rem.empty else 0
                _c_rem = float(_rem["cost"].sum()) if not _rem.empty else 0.0
                st.write(f"Long term: {_n_stk} stocks held, {inr(_c_rem, prefix='₹')}")

# --------------------------------------- my investments: pies for this owner --
_me = state.current_user()
_my_portfolio = state.get_frame("portfolio", _me)
if _my_portfolio is not None and not _my_portfolio.empty:
    st.write("")
    st.subheader(f"Investments — {state.user_name(_me)}")
    _my_method = str(state.get_meta(_me).get("sale_match_method", "lifo")).lower()
    _my_rem, _ = match_sales(_my_portfolio, method=_my_method)
    if _my_rem.empty:
        st.info("Nothing is currently held: every purchase has been sold.")
    else:
        _my_cls = with_asset_class(_my_rem, state.get_meta(_me).get("asset_class_overrides", {}))
        _my_sum = asset_class_summary(_my_cls)
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            _donut(_my_sum["Asset class"], _my_sum["Cost"], "Allocation by asset class", "my_class_pie")
        with mcol2:
            cap_pie_with_table(_my_cls[_my_cls["asset_class"] == "Equity"],
                               key="my_cap_pie", title="Equity by marketcap")

# ------------------------------------------- administrator: family dashboards --
if state.is_admin():
    family = [u for u in users if u.get("family")]
    st.write("")
    st.subheader("Family dashboards")
    if not family:
        st.info("No family members yet: open **User management** and tick **Family** on the logins to include here.")
    else:
        st.caption("Only owners marked **Family** in User management. Figures are settled trades only, "
                   "financial years (Apr–Mar).")
        st.markdown("**Trading**")
        rows = []
        for u in family:
            trades = state.get_frame("trades", u["slug"])
            trades = settled_only(trades) if trades is not None else None
            if trades is None or trades.empty:
                rows.append({"Member": u["name"], "Net profit": "—", "Avg monthly ROI": "—", "CAGR": "—",
                             "Avg yearly ROI": "—", "Avg yearly CAGR": "—", "Win rate": "—",
                             "Best month": "—", "Worst month": "—"})
                continue
            summary = monthly_summary(trades, state.get_frame("capital", u["slug"]))
            k = kpis(summary, trades)
            ys = yearly_summary(summary, "financial")
            avg_y = pd.to_numeric(ys["Yearly ROI"], errors="coerce").mean() if not ys.empty else None
            avg_y = None if avg_y is None or pd.isna(avg_y) else float(avg_y)
            cagrs = []
            if not summary.empty:
                for _, grp in summary.groupby(period_label(summary["month"], "financial"), sort=False):
                    c = cagr_from_monthly(grp["Monthly ROI"])
                    if c is not None:
                        cagrs.append(c)
            avg_yc = sum(cagrs) / len(cagrs) if cagrs else None
            rows.append({
                "Member": u["name"],
                "Net profit": inr(k["net_profit"], prefix="₹"),
                "Avg monthly ROI": f"{pct(k['avg_roi'])}%" if k["avg_roi"] is not None else "—",
                "CAGR": f"{pct(k['cagr'])}%" if k.get("cagr") is not None else "—",
                "Avg yearly ROI": f"{pct(avg_y)}%" if avg_y is not None else "—",
                "Avg yearly CAGR": f"{pct(avg_yc)}%" if avg_yc is not None else "—",
                "Win rate": f"{pct(k['win_rate'], 1)}%" if k["win_rate"] is not None else "—",
                "Best month": f"{k['best_month'][0]} ({inr(k['best_month'][1], prefix='₹')})",
                "Worst month": f"{k['worst_month'][0]} ({inr(k['worst_month'][1], prefix='₹')})",
            })
        plain_table(pd.DataFrame(rows), key="tbl_family_trading")

        st.markdown("**Investments — asset class allocation** (current holdings)")
        per_member, class_order, member_frames = {}, [], {}
        for u in family:
            entries = state.get_frame("portfolio", u["slug"])
            if entries is None or entries.empty:
                continue
            _m = str(state.get_meta(u["slug"]).get("sale_match_method", "lifo")).lower()
            remaining, _ = match_sales(entries, method=_m)
            if remaining.empty:
                continue
            classified = with_asset_class(remaining, state.get_meta(u["slug"]).get("asset_class_overrides", {}))
            member_frames[u["name"]] = classified
            summary = asset_class_summary(classified)
            per_member[u["name"]] = dict(zip(summary["Asset class"], summary["Cost"]))
            for cls in summary["Asset class"]:
                if cls not in class_order:
                    class_order.append(cls)
        if not per_member:
            st.info("No current holdings among family members yet.")
        else:
            table = pd.DataFrame(index=class_order)
            for name, costs in per_member.items():
                table[name] = [costs.get(cls) for cls in class_order]
            table["Total"] = table.sum(axis=1, skipna=True)
            grand = float(table["Total"].sum())
            table["% of family"] = table["Total"] / grand * 100 if grand else pd.NA
            class_costs = table["Total"].astype(float)
            shown = table.reset_index().rename(columns={"index": "Asset class"})
            for col in shown.columns:
                if col == "Asset class":
                    continue
                shown[col] = shown[col].map(lambda v: (pct(v, 1) + "%") if col == "% of family" and pd.notna(v)
                                            else (inr(v) if pd.notna(v) else "—"))
            fc1, fc2 = st.columns([1.3, 1])
            with fc1:
                plain_table(shown, key="tbl_family_classes", full_height=True)
            with fc2:
                _donut(class_costs.index, class_costs.values,
                       "Family allocation by asset class (all members)", "family_class_pie")

            # ---- holdings by stock, highest family investment first ----
            st.markdown("**Investments — holdings by stock** (highest family investment on top)")
            stock_cols = {}
            stock_sector = {}
            for name, frame in member_frames.items():
                grp = frame.groupby("stock").agg(cost=("cost", "sum"), sector=("sector", "first"))
                stock_cols[name] = grp["cost"].to_dict()
                for stk, sec_ in grp["sector"].items():
                    stock_sector.setdefault(stk, str(sec_ or ""))
            all_stocks = sorted(set().union(*[set(d) for d in stock_cols.values()]))
            by_stock = pd.DataFrame(index=all_stocks)
            by_stock["Sector"] = [stock_sector.get(stk, "") for stk in all_stocks]
            for name, costs in stock_cols.items():
                by_stock[name] = [costs.get(stk) for stk in all_stocks]
            member_names = list(stock_cols)
            by_stock["Total invested"] = by_stock[member_names].sum(axis=1, skipna=True)
            grand_stock = float(by_stock["Total invested"].sum())
            by_stock["% of family"] = by_stock["Total invested"] / grand_stock * 100 if grand_stock else pd.NA
            by_stock = by_stock.sort_values("Total invested", ascending=False)
            shown_stocks = by_stock.reset_index().rename(columns={"index": "Stock"})
            for col in shown_stocks.columns:
                if col in ("Stock", "Sector"):
                    continue
                shown_stocks[col] = shown_stocks[col].map(
                    lambda v, c=col: (pct(v, 1) + "%") if c == "% of family" and pd.notna(v)
                    else (inr(v) if pd.notna(v) else "—"))
            plain_table(shown_stocks, key="tbl_family_bystock")

            # ---- Equity only: how much sits in Large / Mid / Small cap ----
            st.markdown("**Equity by marketcap** (Equity asset class only; caps come from Stocks Management)")
            equity = pd.concat([f[f["asset_class"] == "Equity"] for f in member_frames.values()],
                               ignore_index=True) if member_frames else pd.DataFrame()
            if equity.empty:
                st.info("No Equity-class holdings among family members yet.")
            else:
                cap_pie_with_table(equity, key="family_cap_pie", title="Family Equity holdings by marketcap")

st.write("")
l, m, r = st.columns(3)
with l:
    st.subheader("Trading Book")
    st.write("Upload a trade log or add trades one at a time, set monthly capital, enter annual benchmark returns.")
    st.page_link("screens/trading_input.py", label="Open", icon="📥")
with m:
    st.subheader("Investment Book")
    st.write("Upload holdings or add them one at a time: month, sector, stock, quantity, buy price, gifts.")
    st.page_link("screens/portfolio_input.py", label="Open", icon="📥")
with r:
    st.subheader("Dashboard Reports")
    st.write("Trading (monthly ROI, capital, brokerage, annual ROI vs Nifty and others) and Investments (holdings, sectors, % investment).")
    st.page_link("screens/reports.py", label="Open", icon="📊")


if _admin:
    with st.expander("Manage portfolio owners"):
        st.caption("Owners are created when someone signs in with a new username. Rename them here or from the sidebar; "
                   "data is kept per owner.")
        renamed = []
        for u in users:
            new = st.text_input(f"Name for {u['slug']}", value=u["name"], key=f"rename_{u['slug']}")
            renamed.append({"slug": u["slug"], "name": new.strip() or u["name"]})
        options = ["(none)"] + [u["slug"] for u in users]
        current_default = state.default_owner()
        pick = st.selectbox("Default owner (shown first when nobody has signed in)", options,
                            index=options.index(current_default) if current_default in options else 0,
                            format_func=lambda v: v if v == "(none)" else state.user_name(v), key="home_default_owner")
        if (None if pick == "(none)" else pick) != current_default:
            state.set_default_owner(None if pick == "(none)" else pick)
            st.rerun()
        c1, c2 = st.columns([1, 2])
        if c1.button("Save names"):
            state.set_users(renamed)
            st.success("Saved.")
            st.rerun()
        new_name = c2.text_input("Add another owner", placeholder="Name")
        if new_name.strip() and c2.button("Add owner"):
            state.set_users(store.add_user(users, new_name))
            st.rerun()

with st.expander("How the numbers are calculated"):
    st.markdown(
        """
- **Net Profit** for a month is the sum of each trade's *Gross Profit* (profit/loss minus brokerage and charges).
- **Average of Capital** is the capital you enter per month, or the per-month average of a `Capital` column if the file has one. Its Grand Total is the average across months.
- **Monthly ROI** = Net Profit ÷ Average of Capital × 100. The Grand Total row and the yearly **Z ROI%** are sums of monthly ROI.
- **Brokerage** is the sum of brokerage and other charges per month.
- Benchmark returns (Nifty, NASDAQ, Gold BeES, …) are entered by you; they are not in any trade file.
- **% Investment** in the long-term dashboard is each stock's cost as a share of the total cost of the holdings currently shown (so it respects the filters).
- Rows whose period is not a calendar month (for example `YEAR 2026`) are listed separately and left out of monthly totals.
        """
    )
