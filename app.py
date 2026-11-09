"""Entry point. Run with:  streamlit run app.py

Set APP_PASSWORD in the environment to require sign-in. There is one shared
password; the username typed at sign-in picks (or creates) the portfolio owner,
so each person lands on their own data without separate accounts.
"""

import hmac
import os

import streamlit as st

from core import APP_NAME, APP_TAGLINE, state, store

st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")

REQUIRED_PASSWORD = os.environ.get("APP_PASSWORD", "")


def login_gate() -> None:
    if not REQUIRED_PASSWORD or st.session_state.get("authed"):
        return
    st.title(APP_NAME)
    st.caption(APP_TAGLINE)
    _, box, _ = st.columns([1, 1.2, 1])
    with box, st.form("login", border=True):
        username = st.text_input("Username", placeholder="Your name",
                                 help="New names create a new portfolio owner; existing names open theirs.")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
    if submitted:
        if not username.strip():
            box.error("Enter a username.")
        elif len(username.strip()) > 40:
            box.error("Username is too long (40 characters max).")
        elif hmac.compare_digest(password, REQUIRED_PASSWORD):
            slug = state.sign_in(username)
            st.session_state["authed"] = True
            st.session_state["signed_in_as"] = slug
            st.session_state["user"] = slug
            st.rerun()
        else:
            box.error("That password is not correct.")
    st.stop()


login_gate()
if not REQUIRED_PASSWORD:
    state.ensure_default_owner()

users = state.users()
slugs = [u["slug"] for u in users]

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
    with st.popover("Rename or add owner", width="stretch"):
        current = state.current_user()
        new_name = st.text_input("Rename selected owner", value=state.user_name(current), key="sidebar_rename")
        if st.button("Save name", key="sidebar_save") and new_name.strip() and new_name.strip() != state.user_name(current):
            state.set_users(store.rename_user(users, current, new_name))
            st.rerun()
        add_name = st.text_input("Add another owner", placeholder="Name", key="sidebar_add")
        if st.button("Add owner", key="sidebar_add_btn") and add_name.strip():
            if store.find_user(users, add_name):
                st.warning("An owner with that name already exists.")
            else:
                state.set_users(store.add_user(users, add_name))
                st.rerun()
        st.caption("Owners: " + ", ".join(u["name"] for u in users))
    if signed_in and st.button("Sign out", width="stretch"):
        for key in ("authed", "signed_in_as"):
            st.session_state.pop(key, None)
        st.rerun()

home = st.Page("screens/home.py", title="Home", icon=":material/home:", default=True)
trading = st.Page("screens/trading_input.py", title="Trading Book", icon=":material/upload_file:")
portfolio = st.Page("screens/portfolio_input.py", title="Investment Book", icon=":material/account_balance:")
reports = st.Page("screens/reports.py", title="Dashboards", icon=":material/bar_chart:")

st.navigation([home, trading, portfolio, reports]).run()
