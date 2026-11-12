"""User management: change your password; administrator manages users, passwords, family flags."""

import os

import pandas as pd
import streamlit as st

from core import ADMIN_SLUG, state, store
from core.crypto import hash_password, verify_password

st.title("User management")

REQUIRED_PASSWORD = os.environ.get("APP_PASSWORD", "")
signed_in = st.session_state.get("signed_in_as")
admin = state.is_admin()
users = state.refresh_users()

for _flash in st.session_state.pop("users_flash", []):
    st.success(_flash)

# ------------------------------------------------------- change my password --
if REQUIRED_PASSWORD and signed_in:
    st.subheader("Change my password")
    me = next((u for u in users if u["slug"] == signed_in), None)
    with st.form("change_pw", border=True):
        current_pw = st.text_input("Current password", type="password")
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Repeat new password", type="password")
        changed = st.form_submit_button("Change password", type="primary")
    if changed and me is not None:
        current_ok = verify_password(current_pw, me.get("password_hash")) or (
            not me.get("password_hash") and current_pw == REQUIRED_PASSWORD) or (
            signed_in == ADMIN_SLUG and current_pw == REQUIRED_PASSWORD)
        if not current_ok:
            st.error("The current password is not correct.")
        elif len(pw1) < 4:
            st.error("Choose a new password of at least 4 characters.")
        elif pw1 != pw2:
            st.error("The two new passwords do not match.")
        else:
            store.set_user_fields(signed_in, password_hash=hash_password(pw1))
            state.refresh_users()
            st.session_state["users_flash"] = ["Your password has been changed."]
            st.rerun()
elif not REQUIRED_PASSWORD:
    st.info("The app is running without a password gate (APP_PASSWORD is not set), so there are no "
            "login passwords to manage here. The sections below still manage owners and the family flag.")

# --------------------------------------------------------------- admin area --
if not admin:
    st.caption("Only the administrator can manage other users, reset passwords or delete logins. "
               "Forgot your password? Ask the administrator to reset it here.")
else:
    st.subheader("Users")
    st.caption("**Family** marks the owners whose combined Trading and Investment dashboards appear on the "
               "administrator's Home page. Edit the ticks and press **Save users**.")
    grid = pd.DataFrame({
        "Username": [u["name"] for u in users],
        "Family": [bool(u.get("family")) for u in users],
        "Has password": ["yes" if u.get("password_hash") else "not set (shared password still accepted)" for u in users],
        "Administrator": ["yes" if u["slug"] == ADMIN_SLUG else "" for u in users],
    })
    edited = st.data_editor(
        grid, hide_index=True, width="stretch", height=(len(grid) + 1) * 35 + 3,
        disabled=["Username", "Has password", "Administrator"],
        key=f"users_grid_{len(users)}",
        column_config={"Family": st.column_config.CheckboxColumn("Family",
                       help="Counted in the family dashboards on the administrator's Home page")},
    )
    if st.button("Save users", type="primary"):
        new_users = [{**u, "family": bool(edited["Family"].iloc[i])} for i, u in enumerate(users)]
        state.set_users(new_users)
        st.session_state["users_flash"] = ["Family flags saved."]
        st.rerun()

    st.subheader("Reset a password")
    with st.form("reset_pw", border=True):
        a, b = st.columns(2)
        target = a.selectbox("User", [u["slug"] for u in users], format_func=state.user_name)
        new_pw = b.text_input("New password for this user", type="password")
        reset = st.form_submit_button("Reset password", type="primary")
    if reset:
        if len(new_pw) < 4:
            st.error("Choose a password of at least 4 characters.")
        else:
            store.set_user_fields(target, password_hash=hash_password(new_pw))
            state.refresh_users()
            st.session_state["users_flash"] = [f"Password reset for {state.user_name(target)}. Tell them the new password."]
            st.rerun()

    st.subheader("Delete a user")
    st.warning("Deleting a user removes their login **and all of their data** (trades, investments, capital, "
               "SIPs). This cannot be undone.")
    a, b = st.columns(2)
    victim = a.selectbox("User to delete", [u["slug"] for u in users], format_func=state.user_name, key="del_user")
    sure = b.checkbox("I understand all their data is deleted permanently", key="del_sure")
    if st.button("Delete this user", type="primary", disabled=not sure):
        if victim == ADMIN_SLUG:
            st.error("The administrator login cannot be deleted.")
        elif victim == signed_in:
            st.error("You cannot delete the login you are using right now.")
        else:
            name = state.user_name(victim)
            store.delete_user_data(victim)
            state.refresh_users()
            if state.default_owner() == victim:
                state.set_default_owner(None)
            st.session_state.pop("user", None)
            st.session_state["users_flash"] = [f"Deleted {name} and all of their data."]
            st.rerun()
