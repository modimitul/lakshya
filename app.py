"""Entry point. Run with:  streamlit run app.py

Set APP_PASSWORD in the environment to require sign-in. There is one shared
password; the sign-in screen asks for a username only to pick the portfolio
owner, so every person sees their own data first without separate accounts.
"""

import hmac
import os

import streamlit as st

from core import APP_NAME, APP_TAGLINE, state

st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")

users = state.users()
slugs = [u["slug"] for u in users]


def login_gate() -> None:
    required = os.environ.get("APP_PASSWORD", "")
    if not required or st.session_state.get("authed"):
        return
    st.title(APP_NAME)
    st.caption(APP_TAGLINE)
    _, box, _ = st.columns([1, 1.2, 1])
    with box, st.form("login", border=True):
        who = st.selectbox("Username", slugs, format_func=state.user_name)
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
    if submitted:
        if hmac.compare_digest(password, required):
            st.session_state["authed"] = True
            st.session_state["signed_in_as"] = who
            st.session_state["user"] = who
            st.rerun()
        box.error("That password is not correct.")
    st.stop()


login_gate()

with st.sidebar:
    signed_in = st.session_state.get("signed_in_as")
    if signed_in:
        st.caption(f"Signed in as **{state.user_name(signed_in)}**")
    st.selectbox(
        "Portfolio owner",
        options=slugs,
        format_func=state.user_name,
        key="user",
        help="Whose data to show and edit. Defaults to the signed-in user.",
    )
    if signed_in and st.button("Sign out", width="stretch"):
        for key in ("authed", "signed_in_as"):
            st.session_state.pop(key, None)
        st.rerun()

home = st.Page("screens/home.py", title="Home", icon=":material/home:", default=True)
trading = st.Page("screens/trading_input.py", title="User Input (Trading)", icon=":material/upload_file:")
portfolio = st.Page("screens/portfolio_input.py", title="Long Term Portfolio", icon=":material/account_balance:")
reports = st.Page("screens/reports.py", title="Reports", icon=":material/bar_chart:")

st.navigation([home, trading, portfolio, reports]).run()
