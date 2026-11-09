"""Long-term (equity) portfolio: parse entries, aggregate holdings, sector allocation.

Canonical entry columns: month, sector, stock, qty, buy, cost, gift
(% Investment is always recomputed from the filtered total, never stored).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from .parse import _to_month_start, coerce_numeric, map_columns, read_any

PORTFOLIO_ALIASES: dict[str, list[str]] = {
    "month": ["month", "date", "buy date", "purchase month", "purchase date"],
    "sector": ["sectors", "sector", "industry", "theme"],
    "stock": ["stock", "symbol", "scrip", "company", "name"],
    "qty": ["qty", "quantity", "shares", "units"],
    "buy": ["buy", "buy price", "avg price", "average price", "price"],
    "cost": ["cost", "cost value", "investment", "amount", "invested"],
    "pct_investment": ["% investment", "pct investment", "% of investment", "weight", "weight %"],
    "gift": ["gift amount", "gift", "gifted", "gift value"],
}
NUMERIC_COLUMNS = ["qty", "buy", "cost", "pct_investment", "gift"]

COMMON_SECTORS = [
    "BANKS", "NBFC", "IT", "PHARMA", "CHEMICALS", "FMCG", "RETAIL", "AUTO", "CEMENT",
    "ENERGY", "METALS", "INFRA", "REALTY", "TELECOM", "INSURANCE", "CONSUMER", "ETF", "OTHER",
]


@dataclass
class PortfolioResult:
    entries: pd.DataFrame
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.entries.empty


def clean_portfolio(raw: pd.DataFrame) -> PortfolioResult:
    mapping = map_columns(raw.columns, PORTFOLIO_ALIASES)
    df = raw[list(mapping)].rename(columns=mapping).copy()
    result = PortfolioResult(entries=df, mapping=mapping)

    for col in NUMERIC_COLUMNS:
        if col in df:
            df[col] = coerce_numeric(df[col])
    for col in ("stock", "sector"):
        if col in df:
            df[col] = df[col].astype("string").str.strip().replace("", pd.NA)

    before = len(df)
    identity = [c for c in ("stock", "month") if c in df]
    if identity:
        df = df.dropna(subset=identity, how="all")
    if before - len(df):
        result.notes.append(f"Skipped {before - len(df):,} blank rows.")

    if "stock" not in df:
        result.errors.append("No 'STOCK' column found.")
    if "cost" not in df and {"qty", "buy"} <= set(df):
        df["cost"] = df["qty"] * df["buy"]
    elif "cost" in df and {"qty", "buy"} <= set(df):
        df["cost"] = df["cost"].fillna(df["qty"] * df["buy"])
    if "cost" not in df:
        result.errors.append("Could not find or derive cost. Provide 'COST', or 'QTY' and 'BUY'.")
    if "buy" not in df and {"cost", "qty"} <= set(df):
        df["buy"] = df["cost"] / df["qty"].where(df["qty"] > 0)

    if "month" in df:
        df["month"] = _to_month_start(df["month"])
        n = int(df["month"].isna().sum())
        if n:
            result.warnings.append(f"{n} rows have no usable month; they still count in totals but not in year/month filters.")
    else:
        result.warnings.append("No 'MONTH' column; the year and month filters will be unavailable.")
        df["month"] = pd.NaT
    if "sector" not in df:
        df["sector"] = pd.Series(["OTHER"] * len(df), dtype="string")
        result.warnings.append("No 'SECTORS' column; everything is grouped under OTHER.")
    df["sector"] = df["sector"].fillna("OTHER").str.upper()
    df["gift"] = df["gift"].fillna(0) if "gift" in df else 0.0
    df = df.drop(columns=["pct_investment"], errors="ignore")

    if df.empty and not result.errors:
        result.errors.append("The file has headers but no portfolio rows.")
    result.entries = df.reset_index(drop=True)
    return result


def load_portfolio(file, filename: str, sheet_name=0) -> PortfolioResult:
    try:
        raw = read_any(file, filename, sheet_name)
    except ValueError as exc:
        return PortfolioResult(entries=pd.DataFrame(), errors=[str(exc)])
    except Exception as exc:
        return PortfolioResult(entries=pd.DataFrame(), errors=[f"Could not read the file: {exc}"])
    if raw.empty:
        return PortfolioResult(entries=pd.DataFrame(), errors=["The selected sheet is empty."])
    return clean_portfolio(raw)


def entry_from_form(month, sector: str, stock: str, qty: float, buy: float, gift: float = 0.0) -> PortfolioResult:
    raw = pd.DataFrame([{"MONTH": month, "SECTORS": sector, "STOCK": stock, "QTY": qty, "BUY": buy, "GIFT AMOUNT": gift}])
    return clean_portfolio(raw)


# -------------------------------------------------------------- analysis --
def filter_entries(entries: pd.DataFrame, years=None, sectors=None, months=None) -> pd.DataFrame:
    df = entries
    if years:
        df = df[df["month"].dt.year.isin(years)]
    if sectors:
        df = df[df["sector"].isin(sectors)]
    if months:
        df = df[df["month"].dt.strftime("%b-%y").isin(months)]
    return df


def holdings(entries: pd.DataFrame) -> pd.DataFrame:
    """One row per stock: total qty, weighted average buy, total cost, % of total, gifts."""
    if entries.empty:
        return pd.DataFrame(columns=["Stock", "Sector", "Qty", "Buy", "Cost", "% Investment", "Gift"])
    g = entries.groupby("stock", dropna=True)
    out = pd.DataFrame({
        "Sector": g["sector"].agg(lambda s: s.mode().iat[0] if not s.mode().empty else "OTHER"),
        "Qty": g["qty"].sum() if "qty" in entries else pd.NA,
        "Cost": g["cost"].sum(),
        "Gift": g["gift"].sum(),
    })
    out["Buy"] = out["Cost"] / out["Qty"].where(out["Qty"] > 0) if "qty" in entries else pd.NA
    total = out["Cost"].sum()
    out["% Investment"] = out["Cost"] / total * 100 if total else pd.NA
    out = out.reset_index().rename(columns={"stock": "Stock"})
    return out[["Stock", "Sector", "Qty", "Buy", "Cost", "% Investment", "Gift"]].sort_values("Cost", ascending=False).reset_index(drop=True)


def sector_allocation(entries: pd.DataFrame) -> pd.DataFrame:
    if entries.empty:
        return pd.DataFrame(columns=["Sector", "Cost", "% Investment", "Stocks"])
    g = entries.groupby("sector")
    out = pd.DataFrame({"Cost": g["cost"].sum(), "Stocks": g["stock"].nunique()})
    out["% Investment"] = out["Cost"] / out["Cost"].sum() * 100
    return out.reset_index().rename(columns={"sector": "Sector"}).sort_values("Cost", ascending=False).reset_index(drop=True)


def portfolio_template_bytes() -> bytes:
    headers = ["MONTH", "SECTORS", "STOCK", "QTY", "BUY", "COST", "GIFT AMOUNT"]
    rows = [["Jul-23", "CHEMICALS", "SRF", 50, 2179.17, 108959, None],
            ["Jan-22", "RETAIL", "DMART", 100, 3660.44, 366044, 366044]]
    frame = pd.DataFrame(rows, columns=headers)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Portfolio")
        ws = writer.sheets["Portfolio"]
        for idx, col in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = max(12, len(col) + 2)
    return buffer.getvalue()


def looks_like_portfolio_sheet(file, filename: str, sheet_name) -> bool:
    from .parse import sheet_headers
    try:
        mapped = set(map_columns(sheet_headers(file, filename, sheet_name), PORTFOLIO_ALIASES).values())
    except Exception:
        return False
    return "stock" in mapped and bool(mapped & {"cost", "buy", "qty"})


def dedupe_entries(entries: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    keys = [c for c in ("month", "sector", "stock", "qty", "buy", "cost") if c in entries]
    before = len(entries)
    out = entries.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)
    return out, before - len(out)


def load_portfolio_multi(file, filename: str, sheets: list) -> PortfolioResult:
    frames, mapping = [], {}
    result = PortfolioResult(entries=pd.DataFrame())
    for sheet in sheets:
        part = load_portfolio(file, filename, sheet)
        label = f"Sheet '{sheet}'"
        if part.errors:
            result.warnings.append(f"{label}: " + " ".join(part.errors))
            continue
        part.entries["source_sheet"] = str(sheet)
        frames.append(part.entries)
        mapping.update(part.mapping)
        result.notes.append(f"{label}: {len(part.entries):,} holdings")
        for w in part.warnings:
            result.warnings.append(f"{label}: {w}")
    if not frames:
        result.errors.append("None of the selected sheets could be read as a portfolio.")
        return result
    result.entries = pd.concat(frames, ignore_index=True)
    result.mapping = mapping
    return result
