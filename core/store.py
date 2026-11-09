"""Per-user persistence under the data folder (default: ./data, git-ignored).

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

def data_dir() -> Path:
    """Root data folder; read on every call so LAKSHYA_DATA_DIR can change (tests, redeploys)."""
    return Path(os.environ.get("LAKSHYA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


def users_file() -> Path:
    return data_dir() / "users.json"
# Used only when there is no sign-in screen (no APP_PASSWORD) and no owners yet.
DEFAULT_USERS = [{"slug": "owner", "name": "Owner"}]

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
    """Owners from users.json; otherwise any owner folders that already hold data; otherwise none."""
    if users_file().exists():
        try:
            users = json.loads(users_file().read_text())
            if isinstance(users, list):
                return users
        except (OSError, json.JSONDecodeError):
            pass
    found = []
    if data_dir().exists():
        for folder in sorted(data_dir().iterdir()):
            if folder.is_dir() and any(folder.iterdir()):
                found.append({"slug": folder.name, "name": folder.name.replace("-", " ").title()})
    return found


def find_user(users: list[dict], name: str) -> dict | None:
    """Case-insensitive match on display name or slug."""
    key = name.strip().lower()
    return next((u for u in users if u["name"].lower() == key or u["slug"] == slugify(name)), None)


def rename_user(users: list[dict], slug: str, new_name: str) -> list[dict]:
    return [{**u, "name": new_name.strip()} if u["slug"] == slug else u for u in users]


def save_users(users: list[dict]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    users_file().write_text(json.dumps(users, indent=2))


def add_user(users: list[dict], name: str) -> list[dict]:
    base = slugify(name)
    slug, n = base, 2
    taken = {u["slug"] for u in users}
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return users + [{"slug": slug, "name": name.strip()}]


# ----------------------------------------------------------------- frames --
def user_dir(slug: str) -> Path:
    path = data_dir() / slugify(slug)
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
    for col in ("stock", "type", "sector", "Month", "period_label", "source_sheet"):
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
