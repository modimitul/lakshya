"""Entry point. Run with:  streamlit run app.py

Set APP_PASSWORD in the environment to require login. Each user has a personal
password (stored as a PBKDF2 hash); APP_PASSWORD doubles as the invite code for
creating a login and as the administrator's master password. Data frames are
encrypted at rest (see core/crypto.py).
"""

import hmac
import os

import streamlit as st

from core import ADMIN_SLUG, APP_NAME, APP_TAGLINE, APP_VERSION, state, store
from core.crypto import hash_password, verify_password

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
        with tab_login:
            with st.form("login", border=False):
                username = st.text_input("Username", placeholder="Your name")
                password = st.text_input("Password", type="password",
                                         help="Your personal password. First time after the upgrade? "
                                              "Your old shared password still works once, then becomes yours.")
                submitted = st.form_submit_button("Login", type="primary", width="stretch")
            with st.expander("Forgot password?"):
                st.markdown("Ask the administrator to reset it: they log in, open **User management** "
                            "and set you a new password. (The administrator can always log in with the "
                            "server password set in `APP_PASSWORD`.)")
        with tab_new, st.form("new_user", border=False):
            new_username = st.text_input("Choose a username", placeholder="Your name",
                                         help="Creates a new portfolio owner with its own books and dashboards.")
            invite = st.text_input("App password (invite)", type="password", key="new_user_invite",
                                   help="The shared app password set on the server — ask the administrator.")
            new_pw = st.text_input("Your new password", type="password", key="new_user_pw")
            new_pw2 = st.text_input("Repeat your new password", type="password", key="new_user_pw2")
            created = st.form_submit_button("Create login", type="primary", width="stretch")

    def enter(slug: str) -> None:
        st.session_state["authed"] = True
        st.session_state["signed_in_as"] = slug
        st.session_state.pop("user", None)
        st.rerun()

    if submitted:
        name = username.strip()
        user = store.find_user(state.refresh_users(), name) if name else None
        if not name:
            box.error("Enter a username.")
        elif user is None:
            box.error(f"No login named “{name}”. Create one under the New user tab.")
        elif user.get("password_hash") and verify_password(password, user["password_hash"]):
            enter(user["slug"])
        elif user["slug"] == ADMIN_SLUG and hmac.compare_digest(password, REQUIRED_PASSWORD):
            enter(user["slug"])     # master password always works for the administrator
        elif not user.get("password_hash") and hmac.compare_digest(password, REQUIRED_PASSWORD):
            # user from the shared-password era: adopt it as their personal password
            store.set_user_fields(user["slug"], password_hash=hash_password(password))
            state.refresh_users()
            enter(user["slug"])
        else:
            box.error("That password is not correct. (Forgotten? See “Forgot password?” below.)")
    if created:
        name = new_username.strip()
        if not name:
            box.error("Enter a username.")
        elif len(name) > 40:
            box.error("Username is too long (40 characters max).")
        elif not hmac.compare_digest(invite, REQUIRED_PASSWORD):
            box.error("The app password (invite) is not correct — ask the administrator for it.")
        elif len(new_pw) < 4:
            box.error("Choose a password of at least 4 characters.")
        elif new_pw != new_pw2:
            box.error("The two passwords do not match.")
        elif store.find_user(state.refresh_users(), name):
            box.error("That username already exists — use the Login tab.")
        else:
            slug = state.sign_in(name)
            store.set_user_fields(slug, password_hash=hash_password(new_pw))
            state.refresh_users()
            enter(slug)
    st.stop()


login_gate()
if not REQUIRED_PASSWORD:
    state.ensure_default_owner()

users = state.users()
signed_in = st.session_state.get("signed_in_as")
admin = state.is_admin()

# Restricted access: a non-admin login sees only their own owner's data.
if REQUIRED_PASSWORD and signed_in and not admin:
    st.session_state["user"] = signed_in

slugs = [u["slug"] for u in users]
default_slug = state.default_owner()
initial_owner = state.current_user()  # signed-in user, else the default owner, else the first


with st.sidebar:
    if signed_in:
        st.caption(f"Logged in as **{state.user_name(signed_in)}**" + (" · administrator" if admin and REQUIRED_PASSWORD else ""))
    if admin:
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
    else:
        st.caption("Your login sees only your own books and dashboards.")
    if default_slug and not signed_in and admin:
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
stocks_page = st.Page("screens/stocks.py", title="Stocks Management", icon=":material/format_list_bulleted:")
users_page = st.Page("screens/users_admin.py", title="User management", icon=":material/manage_accounts:")

st.navigation([home, guide, trading, portfolio, benchmarks, reports, stocks_page, users_page]).run()
