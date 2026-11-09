"""Per-user persistence under DATA_DIR (default: ./data, git-ignored).

Layout:
    data/users.json
    data/<slug>/trades.csv, excluded.csv, capital.csv, benchmarks.csv, portfolio.csv, meta.json

Frames are stored as CSV with ISO dates and re-typed on load, so the files are
readable in Excel if ever needed. Set LAKSHYA_DATA_DIR to move the folder.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.environ.get("LAKSHYA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
USERS_FILE = DATA_DIR / "users.json"
DEFAULT_USERS = [
    {"slug": "user1", "name": "User 1"},
    {"slug": "user2", "name": "User 2"},
]

# Which stored frames carry which date columns.
DATE_COLUMNS = {
    "trades": ["buy_date", "sale_date", "month"],
    "excluded": ["buy_date", "sale_date"],
    "capital": ["month"],
    "portfolio": ["month"],
    "benchmarks": [],
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "user"


# ------------------------------------------------------------------ users --
def load_users() -> list[dict]:
    if USERS_FILE.exists():
        try:
            users = json.loads(USERS_FILE.read_text())
            if isinstance(users, list) and users:
                return users
        except (OSError, json.JSONDecodeError):
            pass
    return [dict(u) for u in DEFAULT_USERS]


def save_users(users: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2))


def add_user(users: list[dict], name: str) -> list[dict]:
    base = slugify(name)
    slug, n = base, 2
    taken = {u["slug"] for u in users}
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return users + [{"slug": slug, "name": name.strip()}]


# ----------------------------------------------------------------- frames --
def user_dir(slug: str) -> Path:
    path = DATA_DIR / slugify(slug)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_frame(slug: str, name: str, frame: pd.DataFrame | None) -> None:
    path = user_dir(slug) / f"{name}.csv"
    if frame is None or frame.empty:
        path.unlink(missing_ok=True)
        return
    frame.to_csv(path, index=False, date_format="%Y-%m-%d")


def load_frame(slug: str, name: str) -> pd.DataFrame | None:
    path = user_dir(slug) / f"{name}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    for col in DATE_COLUMNS.get(name, []):
        if col in frame:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
    for col in ("stock", "type", "sector", "Month", "period_label"):
        if col in frame:
            frame[col] = frame[col].astype("string")
    return frame


def save_json(slug: str, name: str, obj) -> None:
    (user_dir(slug) / f"{name}.json").write_text(json.dumps(obj, indent=2, default=str))


def load_json(slug: str, name: str, default=None):
    path = user_dir(slug) / f"{name}.json"
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default
