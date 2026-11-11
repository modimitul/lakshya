"""Strategy Guide: every trade type the Trading Book understands, with definition and market bias."""

import streamlit as st

from core.strategies import strategies_frame

st.title("Strategy Guide")
st.caption("Pick these as the **Type** of a trade. The bias column says when each strategy pays: "
           "🐂 bullish, 🐻 bearish, 😐 neutral / range-bound, 📈📉 volatile either way.")

query = st.text_input("Search", placeholder="e.g. straddle, bull, neutral, FUTURE")
frame = strategies_frame()
if query.strip():
    needle = query.strip().lower()
    frame = frame[frame.apply(lambda row: needle in " ".join(str(v).lower() for v in row), axis=1)]
    if frame.empty:
        st.info("No strategy matches that search.")
st.dataframe(frame, hide_index=True, width="stretch", height=(len(frame) + 1) * 35 + 3)
st.page_link("screens/trading_input.py", label="Go to Trading Book", icon="📒")
