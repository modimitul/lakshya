"""Per-owner persistence in a SQL database (SQLite by default, MariaDB/MySQL optional).

Connection URL comes from LAKSHYA_DB_URL; when unset, a SQLite file is used at
<data dir>/lakshya.db, where the data dir is LAKSHYA_DATA_DIR or ./data.

    LAKSHYA_DB_URL=mysql+pymysql://user:password@host/lakshya   # needs: pip install pymysql

Tables (all keyed by owner slug): owners, meta, trades, excluded, capital,
benchmarks, portfolio. Frames are stored whole per owner and replaced on save,
inside a transaction, so two owners saving at once cannot corrupt each other.

Existing CSV data from the earlier file-based version is imported automatically
the first time the database is found empty.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pandas as pd
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, delete, select, text
from sqlalchemy.engine import Engine

# Used only when there is no sign-in screen (no APP_PASSWORD) and no owners yet.
DEFAULT_USERS = [{"slug": "owner", "name": "Owner"}]

FRAME_TABLES = ("trades", "excluded", "capital", "benchmarks", "portfolio", "benchmark_monthly")

# Type restoration on read: SQLite is loosely typed, so we re-type by column name.
DATE_COLUMNS = {
    "trades": ["buy_date", "sale_date", "month"],
    "excluded": ["buy_date", "sale_date"],
    "capital": ["month"],
    "portfolio": ["month"],
    "benchmarks": [],
    "benchmark_monthly": ["month"],
}
STRING_COLUMNS = ("stock", "type", "sector", "Month", "period_label", "source_sheet", "entry_kind", "strike_label")

_engines: dict[str, Engine] = {}
_write_lock = threading.RLock()  # serialise writes within this process; the DB handles other processes
_CI_SUFFIX = re.compile(r"__ci\d+$")
_metadata = MetaData()
owners_table = Table(
    "owners", _metadata,
    Column("slug", String(80), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("position", String(8), nullable=False, default="0"),
)
meta_table = Table(
    "meta", _metadata,
    Column("owner", String(80), primary_key=True),
    Column("key", String(80), primary_key=True),
    Column("value", Text),
)


# ------------------------------------------------------------- connection --
def data_dir() -> Path:
    return Path(os.environ.get("LAKSHYA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


def db_url() -> str:
    url = os.environ.get("LAKSHYA_DB_URL", "").strip()
    if url:
        return url
    data_dir().mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir() / 'lakshya.db'}"


def engine() -> Engine:
    url = db_url()
    if url not in _engines:
        eng = create_engine(url, future=True, pool_pre_ping=True)
        if url.startswith("sqlite"):
            with eng.begin() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=5000"))
        _metadata.create_all(eng)
        with eng.begin() as conn:
            for table in FRAME_TABLES:
                conn.execute(text(f'CREATE TABLE IF NOT EXISTS "{table}" (owner VARCHAR(80))'))
        _engines[url] = eng
        _migrate_legacy_csv(eng)
    return _engines[url]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "user"


# ------------------------------------------------------------------ users --
def load_users() -> list[dict]:
    with engine().connect() as conn:
        rows = conn.execute(select(owners_table.c.slug, owners_table.c.name, owners_table.c.position)).all()
    rows.sort(key=lambda r: int(r.position or 0))
    return [{"slug": r.slug, "name": r.name} for r in rows]


def save_users(users: list[dict]) -> None:
    with _write_lock, engine().begin() as conn:
        conn.execute(delete(owners_table))
        if users:
            conn.execute(owners_table.insert(), [
                {"slug": u["slug"], "name": u["name"], "position": str(i)} for i, u in enumerate(users)
            ])


def add_user(users: list[dict], name: str) -> list[dict]:
    base = slugify(name)
    slug, n = base, 2
    taken = {u["slug"] for u in users}
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return users + [{"slug": slug, "name": name.strip()}]


def find_user(users: list[dict], name: str) -> dict | None:
    key = name.strip().lower()
    return next((u for u in users if u["name"].lower() == key or u["slug"] == slugify(name)), None)


def rename_user(users: list[dict], slug: str, new_name: str) -> list[dict]:
    return [{**u, "name": new_name.strip()} if u["slug"] == slug else u for u in users]


def delete_user_data(slug: str) -> None:
    """Remove an owner and every row they own."""
    with _write_lock, engine().begin() as conn:
        for table in FRAME_TABLES:
            conn.execute(text(f'DELETE FROM "{table}" WHERE owner = :o'), {"o": slug})
        conn.execute(delete(meta_table).where(meta_table.c.owner == slug))
        conn.execute(delete(owners_table).where(owners_table.c.slug == slug))


# ----------------------------------------------------------------- frames --
def _prepare(frame: pd.DataFrame, slug: str) -> pd.DataFrame:
    """Plain Python objects for the driver: dates as ISO text, NA as NULL."""
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
        elif isinstance(out[col].dtype, pd.api.extensions.ExtensionDtype):
            out[col] = out[col].astype(object)
    out = out.astype(object).where(out.notna(), None)
    # SQL column names are case-insensitive in SQLite/MySQL: 'month' and 'Month' must not collide.
    seen: dict[str, int] = {}
    renamed = []
    for col in out.columns:
        key = str(col).lower()
        if key in seen:
            seen[key] += 1
            renamed.append(f"{col}__ci{seen[key]}")
        else:
            seen[key] = 0
            renamed.append(str(col))
    out.columns = renamed
    out.insert(0, "owner", slug)
    return out


def _restore(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    frame = frame.drop(columns=["owner"], errors="ignore")
    frame.columns = [_CI_SUFFIX.sub("", str(c)) for c in frame.columns]
    frame = frame.dropna(axis=1, how="all") if name != "capital" else frame
    for col in DATE_COLUMNS.get(name, []):
        if col in frame:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
    for col in frame.columns:
        if col in STRING_COLUMNS:
            frame[col] = frame[col].astype("string")
        elif col not in DATE_COLUMNS.get(name, []) and (frame[col].dtype == object or pd.api.types.is_string_dtype(frame[col])):
            try:
                frame[col] = pd.to_numeric(frame[col])
            except (ValueError, TypeError):
                frame[col] = frame[col].astype("string")
    if name == "benchmarks" and "Year" in frame:
        frame["Year"] = pd.to_numeric(frame["Year"], errors="coerce").astype("Int64")
    if name == "capital" and "Capital" in frame:
        frame["Capital"] = pd.to_numeric(frame["Capital"], errors="coerce").astype("Float64")
    return frame


def _sql_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "TEXT"
    return "REAL" if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null) else "TEXT"


def save_frame(slug: str, name: str, frame: pd.DataFrame | None) -> None:
    """Replace this owner's rows in `name`, atomically. None/empty deletes them."""
    from sqlalchemy import inspect

    eng = engine()
    with _write_lock, eng.begin() as conn:
        conn.execute(text(f'DELETE FROM "{name}" WHERE owner = :o'), {"o": slug})
        if frame is None or frame.empty:
            return
        prepared = _prepare(frame, slug)
        existing = {c["name"] for c in inspect(conn).get_columns(name)}
        for col in prepared.columns:
            if col not in existing:
                conn.execute(text(f'ALTER TABLE "{name}" ADD COLUMN "{col}" {_sql_type(prepared[col])}'))
        prepared.to_sql(name, conn, if_exists="append", index=False)


def load_frame(slug: str, name: str) -> pd.DataFrame | None:
    eng = engine()
    with eng.connect() as conn:
        frame = pd.read_sql(text(f'SELECT * FROM "{name}" WHERE owner = :o'), conn, params={"o": slug})
    if frame.empty:
        return None
    return _restore(frame, name)


# ------------------------------------------------------------------- meta --
def save_json(slug: str, name: str, obj) -> None:
    with _write_lock, engine().begin() as conn:
        conn.execute(delete(meta_table).where((meta_table.c.owner == slug) & (meta_table.c.key == name)))
        conn.execute(meta_table.insert().values(owner=slug, key=name, value=json.dumps(obj, default=str)))


def load_json(slug: str, name: str, default=None):
    with engine().connect() as conn:
        row = conn.execute(select(meta_table.c.value).where((meta_table.c.owner == slug) & (meta_table.c.key == name))).first()
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return default


# -------------------------------------------------------- legacy CSV import --
def _migrate_legacy_csv(eng: Engine) -> None:
    """One-time import of data/<owner>/*.csv + users.json from the file-based version."""
    root = data_dir()
    users_json = root / "users.json"
    folders = [p for p in root.iterdir() if p.is_dir() and any(p.glob("*.csv"))] if root.exists() else []
    if not folders and not users_json.exists():
        return
    with eng.connect() as conn:
        if conn.execute(select(owners_table.c.slug)).first() is not None:
            return  # database already in use; leave the old files alone
    users: list[dict] = []
    if users_json.exists():
        try:
            users = [u for u in json.loads(users_json.read_text()) if isinstance(u, dict)]
        except (OSError, json.JSONDecodeError):
            users = []
    known = {u["slug"] for u in users}
    for folder in folders:
        if folder.name not in known:
            users.append({"slug": folder.name, "name": folder.name.replace("-", " ").title()})
    _engines[db_url()] = eng  # allow save_* helpers to use this engine during migration
    save_users(users)
    for folder in folders:
        slug = folder.name
        for name in FRAME_TABLES:
            path = folder / f"{name}.csv"
            if path.exists():
                try:
                    frame = pd.read_csv(path)
                except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
                    continue
                for col in DATE_COLUMNS.get(name, []):
                    if col in frame:
                        frame[col] = pd.to_datetime(frame[col], errors="coerce")
                save_frame(slug, name, frame)
        meta_path = folder / "meta.json"
        if meta_path.exists():
            try:
                save_json(slug, "meta", json.loads(meta_path.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
    # Keep the originals but mark them as imported so a later run does not re-import.
    for folder in folders:
        folder.rename(folder.with_name(folder.name + ".imported"))
    if users_json.exists():
        users_json.rename(users_json.with_name("users.json.imported"))
