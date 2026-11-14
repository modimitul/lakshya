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
    "qty": ["qty", "qty.", "quantity", "net qty", "net quantity", "quantity available", "shares", "units"],
    "buy": ["buy", "buy price", "avg price", "average price", "price"],
    "cost": ["cost", "cost value", "investment", "amount", "invested"],
    "pct_investment": ["% investment", "pct investment", "% of investment", "weight", "weight %"],
    "gift": ["gift amount", "gift", "gifted", "gift value"],
    "side": ["side", "buy/sell", "buy / sell", "action", "transaction", "txn", "type"],
    "charges": ["charges", "brokerage", "brokerage & other charges", "sell charges"],
}
NUMERIC_COLUMNS = ["qty", "buy", "cost", "pct_investment", "gift", "charges"]
SELL_WORDS = {"sell", "sold", "sale", "s", "redeem", "redemption", "exit"}

COMMON_SECTORS = [
    "BANKS", "NBFC", "IT", "PHARMA", "CHEMICALS", "FMCG", "RETAIL", "AUTO", "CEMENT",
    "ENERGY", "METALS", "INFRA", "REALTY", "TELECOM", "INSURANCE", "CONSUMER",
    "ETF", "MUTUAL FUND", "DEBT FUND", "LIQUID FUND", "OTHER",
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


def clean_portfolio(raw: pd.DataFrame, sector_lookup: dict[str, str] | None = None) -> PortfolioResult:
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
    had_sector_col = "sector" in df
    if not had_sector_col:
        df["sector"] = pd.Series([pd.NA] * len(df), index=df.index, dtype="string")
    if sector_lookup:
        lookup = {str(k).strip().upper(): str(v).strip().upper()
                  for k, v in sector_lookup.items() if str(v or "").strip()}
        fillable = (df["sector"].isna() | df["sector"].str.upper().eq("OTHER")) & df["stock"].notna()
        looked_up = df.loc[fillable, "stock"].str.upper().map(lookup)
        n_filled = int(looked_up.notna().sum())
        if n_filled:
            df.loc[fillable, "sector"] = looked_up.astype("string")
            result.notes.append(f"Sector was filled from Stocks Management for {n_filled:,} rows.")
    missing_sector = df["sector"].isna() & df["stock"].notna()
    if missing_sector.any():
        leftover = sorted(set(df.loc[missing_sector, "stock"].str.upper()))[:8]
        result.warnings.append(
            f"{int(missing_sector.sum()):,} rows have no sector and go under OTHER "
            f"(e.g. {', '.join(leftover)}). Add these stocks' sectors in Stocks Management "
            "and re-upload, or edit them in Entries saved.")
    elif not had_sector_col and not sector_lookup:
        result.warnings.append("No 'SECTORS' column; everything is grouped under OTHER.")
    df["sector"] = df["sector"].fillna("OTHER").str.upper()
    df["gift"] = df["gift"].fillna(0) if "gift" in df else 0.0
    df["charges"] = df["charges"].fillna(0) if "charges" in df else 0.0
    if "side" in df:
        df["side"] = df["side"].astype("string").str.strip().str.lower().map(lambda v: "sell" if v in SELL_WORDS else "buy").fillna("buy").astype("string")
    else:
        df["side"] = pd.Series(["buy"] * len(df), index=df.index, dtype="string")
    n_sells = int((df["side"] == "sell").sum())
    if n_sells:
        result.notes.append(f"{n_sells} rows are sales (SIDE = SELL): matched against purchases on the dashboard "
                            "(FIFO or LIFO, as set in the Investment Book).")
    df = df.drop(columns=["pct_investment"], errors="ignore")

    if df.empty and not result.errors:
        result.errors.append("The file has headers but no portfolio rows.")
    result.entries = df.reset_index(drop=True)
    return result


def load_portfolio(file, filename: str, sheet_name=0, sector_lookup: dict[str, str] | None = None) -> PortfolioResult:
    try:
        raw = read_any(file, filename, sheet_name)
    except ValueError as exc:
        return PortfolioResult(entries=pd.DataFrame(), errors=[str(exc)])
    except Exception as exc:
        return PortfolioResult(entries=pd.DataFrame(), errors=[f"Could not read the file: {exc}"])
    if raw.empty:
        return PortfolioResult(entries=pd.DataFrame(), errors=["The selected sheet is empty."])
    return clean_portfolio(raw, sector_lookup=sector_lookup)


def entry_from_form(month, sector: str, stock: str, qty: float, buy: float, gift: float = 0.0) -> PortfolioResult:
    raw = pd.DataFrame([{"MONTH": month, "SECTORS": sector, "STOCK": stock, "QTY": qty, "BUY": buy, "GIFT AMOUNT": gift, "SIDE": "BUY"}])
    return clean_portfolio(raw)


def sale_from_form(month, sector: str, stock: str, qty: float, price: float, charges: float = 0.0) -> PortfolioResult:
    """A sale row: 'buy' holds the sell price and 'cost' the gross sale value (qty × price)."""
    raw = pd.DataFrame([{"MONTH": month, "SECTORS": sector, "STOCK": stock, "QTY": qty, "BUY": price,
                         "SIDE": "SELL", "CHARGES": charges}])
    return clean_portfolio(raw)


# ------------------------------------------------------------------ FIFO --
def _years_between(a: pd.Timestamp, b: pd.Timestamp) -> float:
    months = (b.year - a.year) * 12 + (b.month - a.month)
    return max(months, 1) / 12.0


SALE_METHODS = {"fifo": "FIFO — earliest buys sold first", "lifo": "LIFO — latest buys sold first"}


def match_sales(entries: pd.DataFrame, with_lineage: bool = False,
                method: str = "fifo") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match sell rows against buy rows of the same stock, FIFO or LIFO.

    method="fifo" consumes the earliest buy lots first; method="lifo" the most
    recent lots bought on or before the sale month. Returns (remaining, sales):
      remaining: buy rows with qty/cost reduced to what is still held (fully sold lots dropped)
      sales: one row per sale with cost basis, profit, ROI %, cost-weighted holding years and CAGR %
    With with_lineage=True, remaining also carries src_index (the row's index label in `entries`),
    sold_qty and sold_cost, so corrections can be written back to the original lot.
    """
    if entries.empty or "side" not in entries:
        out = entries.copy()
        if with_lineage and not out.empty:
            out["src_index"] = out.index
            out["sold_qty"] = 0.0
            out["sold_cost"] = 0.0
        return out.reset_index(drop=True) if with_lineage else out, pd.DataFrame()
    buys = entries[entries["side"] != "sell"].copy()
    sells = entries[entries["side"] == "sell"].copy()
    qty_num = pd.to_numeric(buys["qty"], errors="coerce") if "qty" in buys else pd.Series(float("nan"), index=buys.index)
    # A buy without a usable quantity cannot be FIFO-matched, but it is still a holding:
    # it is never consumed by a sale and is returned unchanged in `remaining`.
    buys["_matchable"] = (qty_num > 0).fillna(False)
    buys["qty_left"] = qty_num.where(buys["_matchable"], 0.0).astype(float)
    buys["_consumed_cost"] = 0.0
    buys["unit_cost"] = pd.to_numeric(buys["cost"], errors="coerce") / qty_num.where(qty_num > 0)
    buys = buys.sort_values(["month", "stock"], na_position="last")
    sale_rows = []
    for sell_idx, sale in sells.sort_values("month", na_position="last").iterrows():
        qty_to_match = float(sale["qty"]) if pd.notna(sale["qty"]) else 0.0
        price = float(sale["buy"]) if pd.notna(sale["buy"]) else 0.0
        gross = qty_to_match * price
        charges = float(sale["charges"]) if "charges" in sale and pd.notna(sale["charges"]) else 0.0
        matched_cost, weighted_years, matched_qty, first_buy = 0.0, 0.0, 0.0, None
        consumed_lots: list[tuple] = []
        lots = buys[buys["_matchable"] & (buys["stock"] == sale["stock"]) & (buys["qty_left"] > 0)]
        if pd.notna(sale["month"]):
            lots = lots[(lots["month"].isna()) | (lots["month"] <= sale["month"])]
        if str(method).lower() == "lifo":
            lots = lots.sort_values("month", ascending=False, na_position="last", kind="stable")
        for idx, lot in lots.iterrows():
            if qty_to_match <= 0:
                break
            take = min(lot["qty_left"], qty_to_match)
            unit = float(lot["unit_cost"]) if pd.notna(lot["unit_cost"]) else 0.0
            matched_cost += take * unit
            if pd.notna(lot["month"]) and pd.notna(sale["month"]):
                weighted_years += take * unit * _years_between(lot["month"], sale["month"])
            first_buy = lot["month"] if first_buy is None else min(first_buy, lot["month"]) if pd.notna(lot["month"]) else first_buy
            buys.at[idx, "qty_left"] = lot["qty_left"] - take
            buys.at[idx, "_consumed_cost"] = float(lot["_consumed_cost"]) + take * unit
            consumed_lots.append((idx, float(take)))
            matched_qty += take
            qty_to_match -= take
        net_value = gross - charges
        profit = net_value - matched_cost if matched_qty else float("nan")
        roi = profit / matched_cost * 100 if matched_cost else float("nan")
        years = weighted_years / matched_cost if matched_cost else float("nan")
        if matched_cost and net_value > 0 and years and years > 0:
            cagr = ((net_value / matched_cost) ** (1 / years) - 1) * 100
        else:
            cagr = float("nan")
        sale_rows.append({
            "month": sale["month"], "stock": sale["stock"], "sector": sale.get("sector"),
            "qty": float(sale["qty"]) if pd.notna(sale["qty"]) else 0.0, "price": price, "charges": charges,
            "sale_value": net_value, "cost": matched_cost, "profit": profit, "roi": roi,
            "first_buy": first_buy, "years": years, "cagr": cagr, "unmatched_qty": qty_to_match,
            "sell_index": sell_idx, "lots": consumed_lots,
        })
    keep = (~buys["_matchable"]) | (buys["qty_left"] > 0)
    remaining = buys[keep].copy()
    touched = remaining["_matchable"]
    if with_lineage:
        remaining["src_index"] = remaining.index
        orig_qty = pd.to_numeric(remaining["qty"], errors="coerce")
        remaining["sold_qty"] = (orig_qty - remaining["qty_left"]).where(touched, 0.0).fillna(0.0)
        remaining["sold_cost"] = remaining["_consumed_cost"].fillna(0.0)
    remaining.loc[touched, "qty"] = remaining.loc[touched, "qty_left"]
    # Reduce cost by what the sales consumed; an untouched lot keeps its original cost
    # exactly (including lots whose cost or buy price is blank).
    cost_num = pd.to_numeric(remaining["cost"], errors="coerce")
    remaining.loc[touched, "cost"] = (cost_num - remaining["_consumed_cost"]).clip(lower=0).where(cost_num.notna())[touched]
    remaining = remaining.drop(columns=["qty_left", "unit_cost", "_matchable", "_consumed_cost"])
    return remaining.reset_index(drop=True), pd.DataFrame(sale_rows)


def sales_summary(sales: pd.DataFrame) -> dict:
    if sales is None or sales.empty:
        return {"profit": 0.0, "cost": 0.0, "roi": None, "cagr": None, "count": 0}
    cost = float(sales["cost"].sum())
    profit = float(sales["profit"].fillna(0).sum())
    value = float(sales["sale_value"].sum())
    years = float((sales["years"] * sales["cost"]).sum() / cost) if cost else float("nan")
    cagr = ((value / cost) ** (1 / years) - 1) * 100 if cost and value > 0 and years and years > 0 else None
    return {"profit": profit, "cost": cost, "roi": profit / cost * 100 if cost else None, "cagr": cagr, "count": int(len(sales))}


def yearly_sales_summary(sales: pd.DataFrame) -> pd.DataFrame:
    """Per calendar year of sale: count, sale value, matched cost, profit booked, ROI % and CAGR %.

    ROI = profit ÷ cost of the lots sold that year; CAGR = (sale value ÷ cost)^(1 ÷ cost-weighted
    years held) − 1, aggregated over that year's sales. Sales without a usable month are left out.
    """
    if sales is None or sales.empty:
        return pd.DataFrame(columns=["Year", "Sales", "Sale value", "Cost", "Profit", "ROI %", "CAGR %"])
    df = sales.copy()
    df["_year"] = pd.to_datetime(df["month"]).dt.year
    rows = []
    for year, group in df.dropna(subset=["_year"]).groupby("_year"):
        agg = sales_summary(group)
        rows.append({"Year": int(year), "Sales": agg["count"], "Sale value": float(group["sale_value"].sum()),
                     "Cost": agg["cost"], "Profit": agg["profit"], "ROI %": agg["roi"], "CAGR %": agg["cagr"]})
    return pd.DataFrame(rows).sort_values("Year").reset_index(drop=True)


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
    headers = ["MONTH", "SECTORS", "STOCK", "QTY", "BUY", "COST", "GIFT AMOUNT", "SIDE", "CHARGES"]
    rows = [["Jul-23", "CHEMICALS", "SRF", 50, 2179.17, 108959, None, "BUY", None],
            ["Jan-22", "RETAIL", "DMART", 100, 3660.44, 366044, 366044, "BUY", None],
            ["Mar-26", "CHEMICALS", "SRF", 20, 2900, None, None, "SELL", 45]]
    frame = pd.DataFrame(rows, columns=headers)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Portfolio")
        ws = writer.sheets["Portfolio"]
        for idx, col in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = max(12, len(col) + 2)
    return buffer.getvalue()



def sector_lookup_from_stocks(stocks: pd.DataFrame | None) -> dict[str, str]:
    """stock -> sector map from the shared Stocks Management list (blank sectors skipped)."""
    if stocks is None or stocks.empty or "stock" not in stocks or "sector" not in stocks:
        return {}
    out: dict[str, str] = {}
    for _, row in stocks.iterrows():
        stock = str(row.get("stock") or "").strip().upper()
        sector = str(row.get("sector") or "").strip()
        if stock and sector and sector.lower() not in ("nan", "none", "<na>"):
            out[stock] = sector.upper()
    return out

def looks_like_portfolio_header(headers: list[str]) -> bool:
    mapped = set(map_columns(headers, PORTFOLIO_ALIASES).values())
    return "stock" in mapped and bool(mapped & {"cost", "buy", "qty"})


def load_portfolio_workbook(wb, sheets: list[str], sector_lookup: dict[str, str] | None = None) -> PortfolioResult:
    """Import selected sheets one at a time (low memory)."""
    import gc

    parts, mapping = [], {}
    result = PortfolioResult(entries=pd.DataFrame())
    for sheet in sheets:
        label = f"Sheet '{sheet}'"
        try:
            raw = wb.frame(str(sheet))
        except Exception as exc:
            result.warnings.append(f"{label}: could not be read ({exc}).")
            continue
        if raw.empty:
            result.warnings.append(f"{label}: empty.")
            continue
        part = clean_portfolio(raw, sector_lookup=sector_lookup)
        del raw
        if part.errors:
            result.warnings.append(f"{label}: " + " ".join(part.errors))
            continue
        part.entries["source_sheet"] = str(sheet)
        parts.append(part.entries)
        mapping.update(part.mapping)
        result.notes.append(f"{label}: {len(part.entries):,} holdings")
        for n in part.notes:
            result.notes.append(f"{label}: {n}")
        for w in part.warnings:
            result.warnings.append(f"{label}: {w}")
        gc.collect()
    if not parts:
        result.errors.append("None of the selected sheets could be read as a portfolio.")
        return result
    result.entries = pd.concat(parts, ignore_index=True)
    result.mapping = mapping
    return result


def looks_like_portfolio_frame(frame: pd.DataFrame) -> bool:
    mapped = set(map_columns(frame.columns, PORTFOLIO_ALIASES).values())
    return "stock" in mapped and bool(mapped & {"cost", "buy", "qty"})


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


def load_portfolio_frames(frames: dict[str, pd.DataFrame], sheets: list[str], sector_lookup: dict[str, str] | None = None) -> PortfolioResult:
    parts, mapping = [], {}
    result = PortfolioResult(entries=pd.DataFrame())
    for sheet in sheets:
        label = f"Sheet '{sheet}'"
        raw = frames.get(str(sheet))
        if raw is None or raw.empty:
            result.warnings.append(f"{label}: empty or missing.")
            continue
        part = clean_portfolio(raw, sector_lookup=sector_lookup)
        if part.errors:
            result.warnings.append(f"{label}: " + " ".join(part.errors))
            continue
        part.entries["source_sheet"] = str(sheet)
        parts.append(part.entries)
        mapping.update(part.mapping)
        result.notes.append(f"{label}: {len(part.entries):,} holdings")
        for n in part.notes:
            result.notes.append(f"{label}: {n}")
        for w in part.warnings:
            result.warnings.append(f"{label}: {w}")
    if not parts:
        result.errors.append("None of the selected sheets could be read as a portfolio.")
        return result
    result.entries = pd.concat(parts, ignore_index=True)
    result.mapping = mapping
    return result


def load_portfolio_multi(file, filename: str, sheets: list, sector_lookup: dict[str, str] | None = None) -> PortfolioResult:
    from .parse import read_workbook
    try:
        frames = read_workbook(file, filename)
    except Exception as exc:
        return PortfolioResult(entries=pd.DataFrame(), errors=[f"Could not read the file: {exc}"])
    return load_portfolio_frames(frames, [str(s) if not isinstance(s, int) else list(frames)[s] for s in sheets], sector_lookup=sector_lookup)


# ---------------------------------------------------------- asset classes --
import re as _re

ASSET_CLASSES = ["Equity", "ETF", "Equity MF", "Debt", "Liquid Fund"]
# Patterns are checked in this order, so "LIQUID FUND" lands in Liquid Fund (not Equity MF),
# "DEBT FUND" in Debt, and "GOLD BEES" in ETF.
_CLASS_PATTERNS = {
    "Liquid Fund": _re.compile(r"LIQUID|OVERNIGHT|MONEY MARKET|ULTRA SHORT|ARBITRAGE"),
    "Debt": _re.compile(r"\bDEBT\b|\bBOND\b|\bBONDS\b|\bFD\b|\bNCD\b|\bGILT\b|\bSGB\b|G-SEC|GSEC|TREASURY|\bRBI\b"),
    "ETF": _re.compile(r"\bETF\b|\bETFS\b|BEES\b"),
    "Equity MF": _re.compile(r"\bMF\b|\bMFS\b|MUTUAL|\bFUND\b|\bFUNDS\b|DIRECT PLAN|GROWTH PLAN"),
}


def auto_asset_class(sector, stock=None) -> str:
    """Classify from the sector label first, then from the stock name; default Equity."""
    for text_ in (str(sector or "").upper(), str(stock or "").upper()):
        for cls, pattern in _CLASS_PATTERNS.items():
            if pattern.search(text_):
                return cls
    return "Equity"


def sector_class_map(entries: pd.DataFrame, overrides: dict | None = None) -> dict[str, str]:
    """{sector: asset class} for every sector present: saved overrides win, else the auto rules."""
    overrides = {str(k).upper(): v for k, v in (overrides or {}).items() if v in ASSET_CLASSES}
    out = {}
    for sector, group in entries.groupby("sector", dropna=False):
        key = str(sector).upper()
        if key in overrides:
            out[key] = overrides[key]
        else:
            # majority vote of the row-level auto classification (stock names can tip it)
            votes = group.apply(lambda r: auto_asset_class(r["sector"], r.get("stock")), axis=1)
            out[key] = votes.mode().iat[0] if not votes.empty else "Equity"
    return out


def with_asset_class(entries: pd.DataFrame, overrides: dict | None = None) -> pd.DataFrame:
    """Add an `asset_class` column using sector_class_map."""
    if entries.empty:
        out = entries.copy()
        out["asset_class"] = pd.Series(dtype="string")
        return out
    mapping = sector_class_map(entries, overrides)
    out = entries.copy()
    out["asset_class"] = out["sector"].astype(str).str.upper().map(mapping).fillna("Equity").astype("string")
    return out


def asset_class_summary(entries: pd.DataFrame) -> pd.DataFrame:
    """Cost, share and holdings per asset class, in the fixed class order."""
    if entries.empty or "asset_class" not in entries:
        return pd.DataFrame(columns=["Asset class", "Holdings", "Cost", "% Investment", "Gift"])
    g = entries.groupby("asset_class")
    out = pd.DataFrame({
        "Holdings": g["stock"].nunique(),
        "Cost": g["cost"].sum(),
        "Gift": g["gift"].sum() if "gift" in entries else 0.0,
    })
    total = out["Cost"].sum()
    out["% Investment"] = out["Cost"] / total * 100 if total else pd.NA
    out = out.reindex(ASSET_CLASSES).dropna(subset=["Cost"]).reset_index().rename(columns={"asset_class": "Asset class"})
    return out[["Asset class", "Holdings", "Cost", "% Investment", "Gift"]]
