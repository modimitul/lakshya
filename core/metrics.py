"""Aggregations behind the Reports page.

Monthly ROI follows the original pivot: Net Profit / Average Capital x 100,
where Net Profit is the sum of per-trade gross profit (P&L minus charges).
"""

from __future__ import annotations

import io

import pandas as pd

from .formatting import EXCEL_INR_FORMAT

SUMMARY_COLUMNS = ["month", "Month", "Trades", "Charges", "Average of Capital", "Net Profit", "Brokerage", "Monthly ROI", "Win rate"]


def charge_mask(trades: pd.DataFrame) -> pd.Series:
    """True for charge entries. Works for data stored before entry_kind existed."""
    if "entry_kind" in trades:
        return trades["entry_kind"].fillna("trade") == "charge"
    zero = lambda c: (trades[c].fillna(0) == 0) if c in trades else pd.Series(True, index=trades.index)
    brok = trades["brokerage"].fillna(0) > 0 if "brokerage" in trades else pd.Series(False, index=trades.index)
    return zero("pl") & zero("buy") & zero("sell") & brok


def month_label(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%b-%y")


def months_in(trades: pd.DataFrame) -> list[pd.Timestamp]:
    if "month" not in trades or trades.empty:
        return []
    return sorted(pd.Timestamp(m) for m in trades["month"].dropna().unique())


def capital_frame(
    months: list[pd.Timestamp],
    existing: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per month with the capital to use for ROI.

    Priority: value the user already entered > per-month mean of a 'capital'
    column in the data > blank.
    """
    frame = pd.DataFrame({"month": months})
    frame["Month"] = frame["month"].map(month_label)
    frame["Capital"] = pd.Series([pd.NA] * len(frame), dtype="Float64")

    if trades is not None and "capital" in trades and not trades.empty:
        from_data = trades.groupby("month")["capital"].mean()
        frame["Capital"] = frame["month"].map(from_data).astype("Float64")

    if existing is not None and not existing.empty and {"month", "Capital"} <= set(existing):
        entered = existing.dropna(subset=["Capital"]).set_index("month")["Capital"]
        frame["Capital"] = frame["month"].map(entered).astype("Float64").fillna(frame["Capital"])
    return frame


def monthly_summary(trades: pd.DataFrame, capital: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-month trades, capital, net profit, ROI and win rate."""
    if trades.empty or "month" not in trades:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    is_charge = charge_mask(trades)
    grouped = trades.groupby("month", sort=True)
    real = trades[~is_charge].groupby("month", sort=True)
    out = pd.DataFrame({
        "Trades": real.size(),
        "Net Profit": grouped["gross_profit"].sum(),
        "Brokerage": grouped["brokerage"].sum() if "brokerage" in trades else pd.NA,
        "Wins": real["gross_profit"].apply(lambda s: int((s > 0).sum())),
        "Charges": grouped.apply(lambda g: int(is_charge.loc[g.index].sum())),
    }).reset_index()
    out["Trades"] = out["Trades"].fillna(0).astype(int)
    out["Wins"] = out["Wins"].fillna(0).astype(int)

    cap = capital_frame(list(out["month"]), capital, trades)
    out = out.merge(cap[["month", "Capital"]], on="month", how="left")
    out = out.rename(columns={"Capital": "Average of Capital"})

    cap_values = out["Average of Capital"].astype("float")
    out["Monthly ROI"] = out["Net Profit"] / cap_values.where(cap_values > 0) * 100
    out["Win rate"] = out["Wins"] / out["Trades"].where(out["Trades"] > 0) * 100
    out["Month"] = out["month"].map(month_label)
    return out[SUMMARY_COLUMNS].sort_values("month").reset_index(drop=True)


def kpis(summary: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Headline numbers for the top of the Reports page."""
    if summary.empty:
        return {}
    roi = summary["Monthly ROI"].dropna()
    best = summary.loc[summary["Net Profit"].idxmax()]
    worst = summary.loc[summary["Net Profit"].idxmin()]
    real = trades[~charge_mask(trades)]
    gp = real["gross_profit"] if "gross_profit" in real else pd.Series(dtype=float)
    return {
        "net_profit": float(summary["Net Profit"].sum()),
        "avg_roi": float(roi.mean()) if not roi.empty else None,
        "months_with_roi": int(roi.size),
        "months": int(len(summary)),
        "trades": int(summary["Trades"].sum()),
        "charges": int(summary["Charges"].sum()) if "Charges" in summary else 0,
        "win_rate": float((gp > 0).mean() * 100) if len(gp) else None,
        "best_month": (best["Month"], float(best["Net Profit"])),
        "worst_month": (worst["Month"], float(worst["Net Profit"])),
    }


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    """Trades, net profit, win rate and mean ROI grouped by `by` (e.g. stock, type)."""
    if by not in trades or trades.empty:
        return pd.DataFrame()
    is_charge = charge_mask(trades)
    grouped = trades.groupby(by, dropna=True)
    real = trades[~is_charge].groupby(by, dropna=True)
    out = pd.DataFrame({
        "Trades": real.size(),
        "Net Profit": grouped["gross_profit"].sum(),
        "Win rate": real["gross_profit"].apply(lambda s: float((s > 0).mean() * 100) if len(s) else float("nan")),
    })
    out["Trades"] = out["Trades"].fillna(0).astype(int)
    if "roi" in trades:
        out["Avg trade ROI"] = real["roi"].mean()
    out = out.sort_values("Net Profit", ascending=False).reset_index().rename(columns={by: by.title()})
    if by == "type":
        from .strategies import bias
        out.insert(1, "Bias", out["Type"].map(bias))
    return out


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Write several DataFrames to one workbook, with Indian grouping on money columns."""
    money_columns = {"Average of Capital", "Net Profit", "cost_value", "sale_value", "pl", "gross_profit", "inv_amount", "margin", "capital"}
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            export = frame.drop(columns=[c for c in ("month",) if c in frame], errors="ignore")
            export.to_excel(writer, sheet_name=name[:31], index=False)
            ws = writer.sheets[name[:31]]
            for idx, col in enumerate(export.columns, start=1):
                letter = ws.cell(row=1, column=idx).column_letter
                ws.column_dimensions[letter].width = max(12, min(40, len(str(col)) + 4))
                if col in money_columns:
                    for cell in ws[letter][1:]:
                        cell.number_format = EXCEL_INR_FORMAT
    return buffer.getvalue()


def capital_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Month / Average of Capital with a Grand Total row (mean of the months that have a value)."""
    cap = summary[["Month", "Average of Capital"]].copy()
    mean = pd.to_numeric(cap["Average of Capital"], errors="coerce").mean()
    total = pd.DataFrame([{"Month": "Grand Total", "Average of Capital": mean}])
    return pd.concat([cap, total], ignore_index=True)


def brokerage_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Month / Brokerage with a Grand Total row (sum)."""
    brk = summary[["Month", "Brokerage"]].copy()
    total = pd.DataFrame([{"Month": "Grand Total", "Brokerage": pd.to_numeric(brk["Brokerage"], errors="coerce").sum(min_count=1)}])
    return pd.concat([brk, total], ignore_index=True)


def yearly_summary(summary: pd.DataFrame, basis: str = "calendar") -> pd.DataFrame:
    """Per year (calendar Jan–Dec) or financial year (Apr–Mar): Investments, Net Profit, Yearly ROI.

    Investments = mean of the period's monthly capital; Yearly ROI = Net Profit / Investments × 100,
    matching the source sheet's 'Year Labels' pivot. Months without capital count in
    Net Profit but not in the Investments average.
    """
    from .benchmarks import period_label

    if summary.empty:
        return pd.DataFrame(columns=["Year", "Investments", "Net Profit", "Brokerage", "Trades", "Yearly ROI"])
    labels = period_label(summary["month"], basis)
    g = summary.groupby(labels, sort=False)
    out = pd.DataFrame({
        "Investments": g["Average of Capital"].apply(lambda s: pd.to_numeric(s, errors="coerce").mean()),
        "Net Profit": g["Net Profit"].sum(),
        "Brokerage": g["Brokerage"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum()),
        "Trades": g["Trades"].sum(),
        "_first": g["month"].min(),
    }).sort_values("_first").drop(columns="_first").reset_index().rename(columns={"month": "Year", "index": "Year"})
    out.columns = ["Year" if c in ("Year", labels.name, 0) else c for c in out.columns]
    if basis == "calendar":
        out["Year"] = out["Year"].astype(int)
    inv = pd.to_numeric(out["Investments"], errors="coerce")
    out["Yearly ROI"] = out["Net Profit"] / inv.where(inv > 0) * 100
    return out.reset_index(drop=True)


def yearly_with_total(yearly: pd.DataFrame) -> pd.DataFrame:
    """Append the Grand Total row: Investments and ROI averaged across years, the rest summed."""
    if yearly.empty:
        return yearly
    inv = pd.to_numeric(yearly["Investments"], errors="coerce")
    roi = pd.to_numeric(yearly["Yearly ROI"], errors="coerce")
    total = pd.DataFrame([{
        "Year": "Grand Total",
        "Investments": inv.mean(),
        "Net Profit": yearly["Net Profit"].sum(),
        "Brokerage": pd.to_numeric(yearly["Brokerage"], errors="coerce").sum(),
        "Trades": int(yearly["Trades"].sum()),
        "Yearly ROI": roi.mean(),
    }])
    shown = yearly.copy()
    shown["Year"] = shown["Year"].astype(str)
    return pd.concat([shown, total], ignore_index=True)
