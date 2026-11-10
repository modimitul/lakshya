"""Monthly benchmark returns (Nifty, Nifty BEES, NASDAQ, Gold BEES …) and the comparison with the owner's ROI.

The data is shared by all owners and lives in the `benchmark_monthly` table under
the pseudo-owner "_shared". It is seeded from core/seed/benchmarks_monthly.csv the
first time the table is empty. Yearly figures are the SUM of the monthly values,
which is the convention of the source sheets (Grand Total = sum of years).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import store
from .parse import _to_month_start, coerce_numeric, normalise_header, read_any

SHARED_OWNER = "_shared"
TABLE = "benchmark_monthly"
SEED_PATH = Path(__file__).resolve().parent / "seed" / "benchmarks_monthly.csv"
Z_COLUMN = "Z ROI%"

DEFAULT_COLUMNS = ["Nifty ROI", "Nifty BEES ROI", "BANK NIFTY ROI", "NIFTY IT ROI", "NASDAQ ROI",
                   "DJI ROI", "MAFANG ROI", "GOLD BEES", "SILVER BEES"]
# Accept the older header spellings too.
COLUMN_ALIASES = {
    "nifty roi%": "Nifty ROI", "nifty": "Nifty ROI", "nifty 50": "Nifty ROI",
    "nifty bees": "Nifty BEES ROI", "niftybees": "Nifty BEES ROI",
    "bank nifty roi%": "BANK NIFTY ROI", "bank nifty": "BANK NIFTY ROI", "banknifty": "BANK NIFTY ROI",
    "nifty it roi%": "NIFTY IT ROI", "nifty it": "NIFTY IT ROI",
    "nasdaq roi%": "NASDAQ ROI", "nasdaq": "NASDAQ ROI",
    "dji roi%": "DJI ROI", "dji": "DJI ROI", "dow jones": "DJI ROI",
    "mafang roi%": "MAFANG ROI", "mafang": "MAFANG ROI",
    "gold bees%": "GOLD BEES", "goldbees": "GOLD BEES", "gold": "GOLD BEES",
    "silver bees%": "SILVER BEES", "silverbees": "SILVER BEES", "silver": "SILVER BEES",
}
MONTH_HEADERS = {"month", "row labels", "date", "period"}


# -------------------------------------------------------------- shaping --
def normalise_monthly(raw: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    """Any table with a month column and numeric return columns → month-start index, Float64 columns."""
    if raw is None or raw.empty:
        return None, ["The sheet is empty."]
    raw = raw.copy()
    renamed = {}
    month_col = None
    for col in raw.columns:
        key = normalise_header(col)
        if key in MONTH_HEADERS and month_col is None:
            month_col = col
            renamed[col] = "month"
        elif key in COLUMN_ALIASES:
            renamed[col] = COLUMN_ALIASES[key]
        else:
            # keep the user's own header (e.g. a new index) trimmed
            renamed[col] = str(col).strip()
    if month_col is None:
        month_col = raw.columns[0]
        renamed[month_col] = "month"
    df = raw.rename(columns=renamed)
    df = df[~df["month"].astype(str).str.contains("total", case=False, na=False)]
    df["month"] = _to_month_start(df["month"])
    df = df.dropna(subset=["month"])
    value_cols = [c for c in df.columns if c != "month"]
    for col in value_cols:
        df[col] = coerce_numeric(df[col]).astype("Float64")
    df = df.dropna(axis=1, how="all")
    value_cols = [c for c in df.columns if c != "month"]
    if not value_cols:
        return None, ["No numeric return columns found."]
    df = df.groupby("month", as_index=False).last().sort_values("month").reset_index(drop=True)
    return df, []


def load_monthly_file(file, filename: str, sheet_name=0) -> tuple[pd.DataFrame | None, list[str]]:
    try:
        raw = read_any(file, filename, sheet_name)
    except Exception as exc:
        return None, [f"Could not read the file: {exc}"]
    return normalise_monthly(raw)


def seed_frame() -> pd.DataFrame:
    frame, errors = normalise_monthly(pd.read_csv(SEED_PATH))
    if errors:
        raise RuntimeError("Built-in benchmark seed is unreadable: " + " ".join(errors))
    return frame


def get_monthly() -> pd.DataFrame:
    """Shared monthly benchmark table; seeded from the built-in CSV when empty."""
    frame = store.load_frame(SHARED_OWNER, TABLE)
    if frame is None or frame.empty:
        frame = seed_frame()
        store.save_frame(SHARED_OWNER, TABLE, frame)
        return frame
    frame, _ = normalise_monthly(frame)
    return frame


def save_monthly(frame: pd.DataFrame) -> None:
    frame, errors = normalise_monthly(frame)
    if errors:
        raise ValueError(" ".join(errors))
    store.save_frame(SHARED_OWNER, TABLE, frame)


def merge_monthly(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Upsert: incoming months/columns overwrite existing values; everything else is kept."""
    a = existing.set_index("month")
    b = incoming.set_index("month")
    out = a.combine_first(b)      # start from existing, fill gaps with incoming …
    out.update(b)                 # … then let incoming win where both have a value
    return out.reset_index().sort_values("month").reset_index(drop=True)


def template_bytes() -> bytes:
    import io
    buf = io.BytesIO()
    frame = pd.DataFrame([["Apr-26"] + [None] * len(DEFAULT_COLUMNS)], columns=["Month"] + DEFAULT_COLUMNS)
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        frame.to_excel(w, index=False, sheet_name="Monthly returns")
    return buf.getvalue()


# ---------------------------------------------------------- comparison --
def period_label(months: pd.Series, basis: str) -> pd.Series:
    """Calendar year ('2024') or financial year Apr–Mar ('FY 2024-25') per month."""
    months = pd.to_datetime(months)
    if basis == "financial":
        start = months.dt.year.where(months.dt.month >= 4, months.dt.year - 1)
        return start.map(lambda y: f"FY {int(y)}-{str(int(y) + 1)[-2:]}" if pd.notna(y) else None)
    return months.dt.year.map(lambda y: str(int(y)) if pd.notna(y) else None)


def user_monthly_roi(summary: pd.DataFrame) -> pd.DataFrame:
    """month + Z ROI% from the owner's monthly summary."""
    if summary.empty:
        return pd.DataFrame(columns=["month", Z_COLUMN])
    return pd.DataFrame({"month": summary["month"], Z_COLUMN: pd.to_numeric(summary["Monthly ROI"], errors="coerce")})


def comparison_table(summary: pd.DataFrame, monthly_bench: pd.DataFrame, basis: str = "calendar",
                     columns: list[str] | None = None) -> pd.DataFrame:
    """Per year/FY: Z ROI% and each benchmark as the SUM of monthly values, plus a Grand Total row.

    Like-for-like: benchmarks are summed only over the months where the owner has a
    monthly ROI, so a part-year of trading is compared with the same part-year of the market.
    """
    user = user_monthly_roi(summary).dropna(subset=[Z_COLUMN])
    bench = monthly_bench.copy() if monthly_bench is not None else pd.DataFrame(columns=["month"])
    if columns:
        bench = bench[["month"] + [c for c in columns if c in bench]]
    merged = pd.merge(user, bench, on="month", how="left").sort_values("month")
    if merged.empty:
        return merged
    merged["Period"] = period_label(merged["month"], basis)
    value_cols = [c for c in merged.columns if c not in ("month", "Period")]
    out = merged.groupby("Period", sort=False)[value_cols].sum(min_count=1)
    # order periods chronologically by their first month
    order = merged.groupby("Period")["month"].min().sort_values().index
    out = out.reindex(order).reset_index()
    totals = {c: out[c].sum(min_count=1) for c in value_cols}
    total_row = pd.DataFrame([{"Period": "Grand Total", **totals}])
    return pd.concat([out, total_row], ignore_index=True)


def cumulative_series(summary: pd.DataFrame, monthly_bench: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Running sum of monthly % for Z ROI% and the chosen benchmarks, over months where the owner has ROI."""
    user = user_monthly_roi(summary).dropna(subset=[Z_COLUMN])
    if user.empty:
        return pd.DataFrame()
    bench = monthly_bench[["month"] + [c for c in columns if c in monthly_bench]] if monthly_bench is not None else user[["month"]]
    merged = pd.merge(user, bench, on="month", how="left").sort_values("month")
    for col in merged.columns:
        if col != "month":
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).cumsum()
    merged["Month"] = merged["month"].dt.strftime("%b-%y")
    return merged


def cagr_table(summary: pd.DataFrame, monthly_bench: pd.DataFrame, basis: str = "calendar",
               columns: list[str] | None = None) -> pd.DataFrame:
    """Per year/FY: annualised compound return of Z ROI% and each benchmark over the owner's months,
    plus an 'Overall' row compounded across all those months (annualised)."""
    from .metrics import cagr_from_monthly

    user = user_monthly_roi(summary).dropna(subset=[Z_COLUMN])
    bench = monthly_bench.copy() if monthly_bench is not None else pd.DataFrame(columns=["month"])
    if columns:
        bench = bench[["month"] + [c for c in columns if c in bench]]
    merged = pd.merge(user, bench, on="month", how="left").sort_values("month")
    if merged.empty:
        return merged
    merged["Period"] = period_label(merged["month"], basis)
    value_cols = [c for c in merged.columns if c not in ("month", "Period")]
    order = merged.groupby("Period")["month"].min().sort_values().index
    rows = []
    for period in order:
        part = merged[merged["Period"] == period]
        rows.append({"Period": period, "Months": len(part), **{c: cagr_from_monthly(part[c]) for c in value_cols}})
    rows.append({"Period": "Overall", "Months": len(merged), **{c: cagr_from_monthly(merged[c]) for c in value_cols}})
    return pd.DataFrame(rows)
