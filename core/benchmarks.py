"""Annual ROI versus market benchmarks.

Benchmark returns are not derivable from a trade log, so they are user-entered
(grid or upload). The user's own yearly figure ("Z ROI%") can be filled from the
trade data as the SUM of that year's monthly ROI, matching the convention in the
source sheet where Grand Total is the sum across years.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .parse import coerce_numeric, normalise_header, read_any

Z_COLUMN = "Z ROI%"
BENCHMARK_COLUMNS = [
    Z_COLUMN, "Nifty ROI%", "BANK NIFTY ROI%", "NIFTY IT ROI%", "NASDAQ ROI%",
    "DJI ROI%", "MAFANG ROI%", "GOLD BEES%", "SILVER BEES%",
]
START_YEAR = 2018


def default_table(start_year: int = START_YEAR, end_year: int | None = None) -> pd.DataFrame:
    end_year = end_year or dt.date.today().year
    table = pd.DataFrame({"Year": list(range(start_year, end_year + 1))})
    for col in BENCHMARK_COLUMNS:
        table[col] = pd.Series([pd.NA] * len(table), dtype="Float64")
    return table


def normalise_table(table: pd.DataFrame) -> pd.DataFrame:
    """Ensure Year is int, every standard column exists, values are Float64, rows sorted by year."""
    out = table.copy()
    if "Year" not in out:
        raise ValueError("Benchmark table needs a 'Year' column.")
    out["Year"] = coerce_numeric(out["Year"]).astype("Int64")
    out = out.dropna(subset=["Year"])
    for col in BENCHMARK_COLUMNS:
        out[col] = coerce_numeric(out[col]).astype("Float64") if col in out else pd.Series([pd.NA] * len(out), dtype="Float64", index=out.index)
    extra = [c for c in out.columns if c not in BENCHMARK_COLUMNS + ["Year"]]
    for col in extra:
        out[col] = coerce_numeric(out[col]).astype("Float64")
    out = out.drop_duplicates(subset="Year", keep="last").sort_values("Year").reset_index(drop=True)
    return out[["Year"] + BENCHMARK_COLUMNS + extra]


def computed_z_roi(summary: pd.DataFrame) -> pd.DataFrame:
    """Per year: sum of monthly ROI, with how many months had a capital figure."""
    if summary.empty:
        return pd.DataFrame(columns=["Year", "Z ROI%", "months", "months_with_capital"])
    years = summary["month"].dt.year
    g = summary.groupby(years)
    out = pd.DataFrame({
        "Z ROI%": g["Monthly ROI"].sum(min_count=1),
        "months": g.size(),
        "months_with_capital": g["Monthly ROI"].count(),
    }).reset_index().rename(columns={"month": "Year"})
    out["Year"] = out["Year"].astype(int)
    return out


def fill_z_from_trades(table: pd.DataFrame, computed: pd.DataFrame) -> pd.DataFrame:
    """Overwrite Z ROI% for years present in the trade data (adds missing years)."""
    out = normalise_table(table)
    for _, row in computed.iterrows():
        if pd.isna(row["Z ROI%"]):
            continue
        year = int(row["Year"])
        if year not in set(out["Year"].astype(int)):
            new = pd.DataFrame({"Year": [year]})
            out = pd.concat([out, new], ignore_index=True)
        out.loc[out["Year"] == year, Z_COLUMN] = round(float(row["Z ROI%"]), 2)
    return normalise_table(out)


def with_grand_total(table: pd.DataFrame) -> pd.DataFrame:
    """Append a 'Grand Total' row = column sums (NA-safe), Year shown as text."""
    out = normalise_table(table)
    sums = {col: out[col].sum(min_count=1) for col in out.columns if col != "Year"}
    display = out.copy()
    display["Year"] = display["Year"].astype(str)
    total = pd.DataFrame([{"Year": "Grand Total", **sums}])
    return pd.concat([display, total], ignore_index=True)


def load_benchmarks(file, filename: str, sheet_name=0) -> tuple[pd.DataFrame | None, list[str]]:
    """Read a sheet whose first column is the year and other columns are % returns."""
    try:
        raw = read_any(file, filename, sheet_name)
    except Exception as exc:
        return None, [f"Could not read the file: {exc}"]
    if raw.empty:
        return None, ["The selected sheet is empty."]
    # Accept 'Row Labels' / 'Year' / anything in the first column as the year.
    cols = list(raw.columns)
    renamed = {cols[0]: "Year"}
    known = {normalise_header(c): c for c in BENCHMARK_COLUMNS}
    for col in cols[1:]:
        key = normalise_header(col)
        if key in known:
            renamed[col] = known[key]
    table = raw.rename(columns=renamed)
    table = table[~table["Year"].astype(str).str.contains("total", case=False, na=False)]
    try:
        return normalise_table(table), []
    except ValueError as exc:
        return None, [str(exc)]
