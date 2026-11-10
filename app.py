"""Entry point. Run with:  streamlit run app.py

Set APP_PASSWORD in the environment to require sign-in. There is one shared
password; the username typed at sign-in picks (or creates) the portfolio owner,
so each person lands on their own data without separate accounts.
"""

import hmac
import os

import streamlit as st

from core import APP_NAME, APP_TAGLINE, APP_VERSION, state, store

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
            st.session_state.pop("user", None)
            st.rerun()
        else:
            box.error("That password is not correct.")
    st.stop()


login_gate()
if not REQUIRED_PASSWORD:
    state.ensure_default_owner()

users = state.users()
slugs = [u["slug"] for u in users]
default_slug = state.default_owner()
initial_owner = state.current_user()  # signed-in user, else the default owner, else the first


with st.sidebar:
    signed_in = st.session_state.get("signed_in_as")
    if signed_in:
        st.caption(f"Signed in as **{state.user_name(signed_in)}**")
    st.selectbox(
        "Portfolio owner",
        options=slugs,
        format_func=state.user_name,
        key="user",
        help="Whose data to show and edit. Starts on the signed-in user, otherwise on the default owner.",
        **({} if "user" in st.session_state else {"index": slugs.index(initial_owner)}),
    )
    with st.popover("Manage owners (rename · add · default)", width="stretch"):
        current = state.current_user()
        new_name = st.text_input("Rename selected owner", value=state.user_name(current), key="sidebar_rename")
        if st.button("Save name", key="sidebar_save") and new_name.strip() and new_name.strip() != state.user_name(current):
            state.set_users(store.rename_user(users, current, new_name))
            st.rerun()
        add_name = st.text_input("Add another owner (no limit)", placeholder="Name", key="sidebar_add")
        if st.button("Add owner", key="sidebar_add_btn") and add_name.strip():
            if store.find_user(users, add_name):
                st.warning("An owner with that name already exists.")
            else:
                state.set_users(store.add_user(users, add_name))
                st.rerun()
        if current != default_slug and st.button("Make this the default owner", key="sidebar_default",
                                                 help="The owner shown first when nobody has signed in."):
            state.set_default_owner(current)
            st.rerun()
        st.caption("There is no limit on owners; signing in with a new username also creates one. "
                   "Owners: " + ", ".join(u["name"] for u in users)
                   + (f". Default: {state.user_name(default_slug)}." if default_slug else ". No default set."))
    if default_slug and not signed_in:
        st.caption(f"Default owner: **{state.user_name(default_slug)}**")
    if signed_in and st.button("Sign out", width="stretch"):
        for key in ("authed", "signed_in_as"):
            st.session_state.pop(key, None)
        st.rerun()
    st.caption(f"{APP_NAME} v{APP_VERSION}")

home = st.Page("screens/home.py", title="Home", icon=":material/home:", default=True)
trading = st.Page("screens/trading_input.py", title="Trading Book", icon=":material/upload_file:")
portfolio = st.Page("screens/portfolio_input.py", title="Investment Book", icon=":material/account_balance:")
benchmarks = st.Page("screens/benchmarks.py", title="Benchmarks", icon=":material/show_chart:")
reports = st.Page("screens/reports.py", title="Dashboard Reports", icon=":material/bar_chart:")

st.navigation([home, trading, portfolio, benchmarks, reports]).run()
