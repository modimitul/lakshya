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
    with box:
        tab_login, tab_new = st.tabs(["Login", "New user"])
        with tab_login, st.form("login", border=False):
            username = st.text_input("Username", placeholder="Your name")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", type="primary", width="stretch")
        with tab_new, st.form("new_user", border=False):
            new_username = st.text_input("Choose a username", placeholder="Your name",
                                         help="Creates a new portfolio owner with its own books and dashboards. No limit on users.")
            new_password = st.text_input("Password", type="password", key="new_user_pw",
                                         help="The shared app password set on the server.")
            created = st.form_submit_button("Create login", type="primary", width="stretch")

    def enter(slug: str) -> None:
        st.session_state["authed"] = True
        st.session_state["signed_in_as"] = slug
        st.session_state.pop("user", None)
        st.rerun()

    if submitted:
        name = username.strip()
        if not name:
            box.error("Enter a username.")
        elif not hmac.compare_digest(password, REQUIRED_PASSWORD):
            box.error("That password is not correct.")
        else:
            existing = store.find_user(state.users(), name)
            if existing is None:
                box.error(f"No login named “{name}”. Create one under the New user tab.")
            else:
                enter(existing["slug"])
    if created:
        name = new_username.strip()
        if not name:
            box.error("Enter a username.")
        elif len(name) > 40:
            box.error("Username is too long (40 characters max).")
        elif not hmac.compare_digest(new_password, REQUIRED_PASSWORD):
            box.error("That password is not correct.")
        elif store.find_user(state.users(), name):
            box.error("That username already exists — use the Login tab.")
        else:
            enter(state.sign_in(name))
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
        st.caption(f"Logged in as **{state.user_name(signed_in)}**")
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
        st.caption("There is no limit on owners; the New user tab on the login screen also creates one. "
                   "Owners: " + ", ".join(u["name"] for u in users)
                   + (f". Default: {state.user_name(default_slug)}." if default_slug else ". No default set."))
    if default_slug and not signed_in:
        st.caption(f"Default owner: **{state.user_name(default_slug)}**")
    if signed_in and st.button("Logout", width="stretch"):
        for key in ("authed", "signed_in_as"):
            st.session_state.pop(key, None)
        st.rerun()
    st.caption(f"{APP_NAME} v{APP_VERSION}")

home = st.Page("screens/home.py", title="Home", icon=":material/home:", default=True)
guide = st.Page("screens/strategy_guide.py", title="Strategy Guide", icon=":material/menu_book:")
trading = st.Page("screens/trading_input.py", title="Trading Book", icon=":material/upload_file:")
portfolio = st.Page("screens/portfolio_input.py", title="Investment Book", icon=":material/account_balance:")
benchmarks = st.Page("screens/benchmarks.py", title="Benchmarks", icon=":material/show_chart:")
reports = st.Page("screens/reports.py", title="Dashboard Reports", icon=":material/bar_chart:")

st.navigation([home, guide, trading, portfolio, benchmarks, reports]).run()
