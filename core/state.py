"""Per-owner data access for the screens: read from disk once, write through on change."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import store

FRAME_KEYS = ("trades", "excluded", "capital", "benchmarks", "portfolio")


def users() -> list[dict]:
    if "users" not in st.session_state:
        st.session_state["users"] = store.load_users()
    return st.session_state["users"]


SHARED = "_shared"


def default_owner() -> str | None:
    """Slug of the owner shown first when nobody has signed in; None if unset."""
    if "default_owner" not in st.session_state:
        st.session_state["default_owner"] = store.load_json(SHARED, "default_owner", None)
    slug = st.session_state["default_owner"]
    return slug if slug in {u["slug"] for u in users()} else None


def set_default_owner(slug: str | None) -> None:
    st.session_state["default_owner"] = slug
    store.save_json(SHARED, "default_owner", slug)


def ensure_default_owner() -> None:
    """With no sign-in screen there must be someone to show: create the fallback owner."""
    if not users():
        set_users([dict(u) for u in store.DEFAULT_USERS])


def sign_in(username: str) -> str:
    """Return the slug for this username, creating the owner if it does not exist yet."""
    existing = store.find_user(users(), username)
    if existing:
        return existing["slug"]
    new_users = store.add_user(users(), username.strip())
    set_users(new_users)
    return new_users[-1]["slug"]


def set_users(new_users: list[dict]) -> None:
    st.session_state["users"] = new_users
    store.save_users(new_users)


def current_user() -> str:
    slugs = [u["slug"] for u in users()]
    if not slugs:
        ensure_default_owner()
        slugs = [u["slug"] for u in users()]
    user = st.session_state.get("user")
    if user not in slugs:
        user = st.session_state.get("signed_in_as") if st.session_state.get("signed_in_as") in slugs else None
        user = user or default_owner() or slugs[0]
    return user


def user_name(slug: str | None = None) -> str:
    slug = slug or current_user()
    name = next((u["name"] for u in users() if u["slug"] == slug), None)
    if name is None:
        # Another session (or process) may have added or renamed owners: refresh from the database.
        st.session_state["users"] = store.load_users()
        name = next((u["name"] for u in users() if u["slug"] == slug), slug)
    return name


def _cache(slug: str) -> dict:
    data = st.session_state.setdefault("data", {})
    return data.setdefault(slug, {})


def get_frame(key: str, slug: str | None = None) -> pd.DataFrame | None:
    slug = slug or current_user()
    cache = _cache(slug)
    if key not in cache:
        cache[key] = store.load_frame(slug, key)
    return cache[key]


def put_frame(key: str, frame: pd.DataFrame | None, slug: str | None = None) -> None:
    slug = slug or current_user()
    _cache(slug)[key] = frame
    store.save_frame(slug, key, frame)


def get_meta(slug: str | None = None) -> dict:
    slug = slug or current_user()
    cache = _cache(slug)
    if "meta" not in cache:
        cache["meta"] = store.load_json(slug, "meta", {}) or {}
    return cache["meta"]


def put_meta(updates: dict, slug: str | None = None) -> None:
    slug = slug or current_user()
    meta = {**get_meta(slug), **updates}
    _cache(slug)["meta"] = meta
    store.save_json(slug, "meta", meta)


def bump(key: str) -> int:
    """Version counter used to reset data_editor widgets after programmatic changes."""
    st.session_state[key] = st.session_state.get(key, 0) + 1
    return st.session_state[key]


def version(key: str) -> int:
    return st.session_state.get(key, 0)


def cached_workbook(upload, key: str):
    """Wrap an upload in a low-memory Workbook once per upload and keep it in the session.

    Only the file bytes are held; sheets are streamed on demand. Returns None (with
    the error shown) if the file cannot be opened.
    """
    from .parse import open_workbook

    fingerprint = f"{upload.name}:{upload.size}"
    if st.session_state.get(f"{key}_fp") != fingerprint:
        try:
            with st.spinner(f"Opening {upload.name} …"):
                st.session_state[key] = open_workbook(upload.getvalue(), upload.name)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            st.session_state.pop(key, None)
            st.session_state.pop(f"{key}_fp", None)
            return None
        st.session_state[f"{key}_fp"] = fingerprint
    return st.session_state.get(key)
