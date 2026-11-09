"""Home: status for every owner, owner management, how the numbers work."""

import streamlit as st

from core import APP_NAME, APP_TAGLINE, state, store
from core.formatting import inr
from core.metrics import months_in

st.title(APP_NAME)
st.caption(APP_TAGLINE)

users = state.users()
current = state.current_user()

cols = st.columns(min(max(len(users), 1), 4))
for i, u in enumerate(users):
    trades = state.get_frame("trades", u["slug"])
    portfolio = state.get_frame("portfolio", u["slug"])
    capital = state.get_frame("capital", u["slug"])
    with cols[i % len(cols)]:
        with st.container(border=True):
            st.markdown(f"**{u['name']}**" + ("  ·  selected" if u["slug"] == current else ""))
            if trades is None or trades.empty:
                st.write("Trading: no trades yet")
            else:
                filled = int(capital["Capital"].notna().sum()) if capital is not None and not capital.empty else 0
                st.write(f"Trading: {len(trades):,} trades, {len(months_in(trades))} months, capital entered for {filled} of {len(months_in(trades))}")
            if portfolio is None or portfolio.empty:
                st.write("Long term: no holdings yet")
            else:
                st.write(f"Long term: {portfolio['stock'].nunique()} stocks, {inr(portfolio['cost'].sum(), prefix='₹')}")

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
    st.subheader("Dashboards")
    st.write("Trading (monthly ROI, capital, brokerage, annual ROI vs Nifty and others) and Investments (holdings, sectors, % investment).")
    st.page_link("screens/reports.py", label="Open", icon="📊")

with st.expander("Manage portfolio owners"):
    st.caption("Owners are created when someone signs in with a new username. Rename them here or from the sidebar; "
               "data is kept per owner.")
    renamed = []
    for u in users:
        new = st.text_input(f"Name for {u['slug']}", value=u["name"], key=f"rename_{u['slug']}")
        renamed.append({"slug": u["slug"], "name": new.strip() or u["name"]})
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
