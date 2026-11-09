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
    if st.session_state.get("user") not in slugs:
        st.session_state["user"] = slugs[0]
    return st.session_state["user"]


def user_name(slug: str | None = None) -> str:
    slug = slug or current_user()
    return next((u["name"] for u in users() if u["slug"] == slug), slug)


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
