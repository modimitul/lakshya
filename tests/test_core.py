"""Run with:  pytest -q"""

import pandas as pd
import pytest

from core.formatting import inr, pct
from core.metrics import capital_frame, monthly_summary, months_in
from core.parse import clean, empty_manual_frame, from_manual


def test_inr_indian_grouping():
    assert inr(3700000) == "37,00,000"
    assert inr(83353) == "83,353"
    assert inr(-48512) == "-48,512"
    assert inr(100) == "100"
    assert inr(2.25, 2) == "2.25"
    assert inr(None) == "—"
    assert inr(float("nan")) == "—"
    assert inr(1500000, prefix="₹") == "₹15,00,000"


def test_pct():
    assert pct(2.2533) == "2.25"
    assert pct(None) == "—"


def test_clean_derives_sheet_formulas():
    raw = pd.DataFrame({
        "Buy Date": ["2026-04-06"],
        "STOCK": ["TCS"],
        "QTY": [350],
        "Buy": [52.13],
        "Sell": [58.88],
        "Brokerage & Other Charges": [None],
        "Margin": [48000],
        "Lot": [2],
    })
    result = clean(raw)
    assert result.ok
    row = result.trades.iloc[0]
    assert row["cost_value"] == pytest.approx(18245.5)
    assert row["sale_value"] == pytest.approx(20608)
    assert row["pl"] == pytest.approx(2362.5)
    assert row["gross_profit"] == pytest.approx(2362.5)
    assert row["inv_amount"] == 96000
    assert row["roi"] == pytest.approx(2.4609375)
    assert row["month"] == pd.Timestamp("2026-04-01")


def test_clean_handles_excel_errors_and_blank_rows():
    raw = pd.DataFrame({
        "Month": ["2026-04-01", "2026-04-01", None, None],
        "STOCK": ["TCS", "INFY", None, None],
        "Gross Profit": [100, "#NUM!", 0, 0],   # formula rows evaluate to 0 on blanks
        "ROI": ["#DIV/0!", 5, 0, 0],
    })
    result = clean(raw)
    assert result.ok
    assert len(result.trades) == 2
    assert result.trades["gross_profit"].tolist() == [100, 0]
    assert any("blank rows" in n for n in result.notes)


def test_non_month_periods_are_excluded_not_misfiled():
    raw = pd.DataFrame({
        "Buy Date": ["2026-04-06", "2025-07-01"],
        "Month": ["2026-04-01", "YEAR 2026"],
        "STOCK": ["TCS", "SOME FUND"],
        "Gross Profit": [500, 900],
    })
    result = clean(raw)
    assert len(result.trades) == 1
    assert len(result.excluded) == 1
    assert result.excluded.iloc[0]["period_label"] == "YEAR 2026"


def test_blank_month_falls_back_to_buy_date():
    raw = pd.DataFrame({
        "Buy Date": ["2026-11-03"],
        "Month": [None],
        "STOCK": ["EQUITY SIP"],
        "Gross Profit": [-156.94],
    })
    result = clean(raw)
    assert result.trades.iloc[0]["month"] == pd.Timestamp("2026-11-01")


def test_monthly_summary_matches_pivot():
    trades = pd.DataFrame({
        "month": pd.to_datetime(["2026-04-01", "2026-04-01", "2026-05-01"]),
        "gross_profit": [50000.0, 33353.0, 46846.0],
    })
    cap = capital_frame(months_in(trades))
    cap["Capital"] = pd.Series([3700000, 2800000], dtype="Float64")
    summary = monthly_summary(trades, cap)
    assert summary["Month"].tolist() == ["Apr-26", "May-26"]
    assert summary["Net Profit"].tolist() == [83353.0, 46846.0]
    assert summary["Monthly ROI"].round(2).tolist() == [2.25, 1.67]
    assert summary["Win rate"].tolist() == [100.0, 100.0]


def test_missing_capital_gives_blank_roi():
    trades = pd.DataFrame({"month": pd.to_datetime(["2026-06-01"]), "gross_profit": [10.0]})
    summary = monthly_summary(trades, None)
    assert pd.isna(summary["Monthly ROI"].iloc[0])


def test_manual_grid_roundtrip():
    grid = empty_manual_frame(rows=1)
    grid.loc[0, "Buy Date"] = pd.Timestamp("2026-05-04")
    grid.loc[0, "Stock"] = "INFY"
    grid.loc[0, "Qty"] = 400
    grid.loc[0, "Buy"] = 4.2
    grid.loc[0, "Sell"] = 16
    grid.loc[0, "Margin"] = 50000
    grid.loc[0, "Lot"] = 1
    result = from_manual(grid)
    assert result.ok
    assert result.trades.iloc[0]["gross_profit"] == pytest.approx(4720)
    assert result.trades.iloc[0]["month"] == pd.Timestamp("2026-05-01")


def test_empty_manual_grid_errors():
    result = from_manual(empty_manual_frame(rows=3))
    assert not result.ok and result.errors


# ------------------------------------------------------------- portfolio ----
def test_portfolio_sample_rows_with_text_months_and_indian_commas():
    from core.portfolio import clean_portfolio, holdings, sector_allocation, filter_entries
    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Jul-23", "Jan-22", "Sep-23"],
        "SECTORS": ["CHEMICALS", "CHEMICALS", "RETAIL", "BANKS"],
        "STOCK": ["SRF", "CLEAN", "DMART", "KOTAKBANK"],
        "QTY": [50, 230, 100, 400], "BUY": [2179.17, 990.5, 3660.44, 337.89],
        "COST": ["1,08,959", "2,27,815", "3,66,044", "1,35,156"],
        "% Investment": [1, 3, 5, 2], "GIFT AMOUNT": [None, None, "3,66,044", None],
    })
    result = clean_portfolio(raw)
    assert result.ok and not result.errors
    assert result.entries["month"].dt.strftime("%b-%y").tolist() == ["Jul-23", "Jul-23", "Jan-22", "Sep-23"]
    assert result.entries["cost"].tolist() == [108959, 227815, 366044, 135156]
    assert result.entries["gift"].tolist() == [0, 0, 366044, 0]
    h = holdings(result.entries)
    assert h.iloc[0]["Stock"] == "DMART" and h["% Investment"].sum() == pytest.approx(100)
    assert sector_allocation(result.entries).iloc[0]["Sector"] == "RETAIL"
    assert filter_entries(result.entries, years=[2023])["stock"].tolist() == ["SRF", "CLEAN", "KOTAKBANK"]


def test_portfolio_cost_derived_when_missing():
    from core.portfolio import clean_portfolio
    raw = pd.DataFrame({"MONTH": ["2024-01-01"], "SECTORS": ["IT"], "STOCK": ["INFY"], "QTY": [10], "BUY": [1500]})
    result = clean_portfolio(raw)
    assert result.entries.iloc[0]["cost"] == 15000


# ------------------------------------------------------------ benchmarks ----
def test_benchmarks_fill_and_grand_total_is_sum():
    from core.benchmarks import default_table, computed_z_roi, fill_z_from_trades, with_grand_total
    summary = pd.DataFrame({
        "month": pd.to_datetime(["2026-04-01", "2026-05-01", "2025-12-01"]),
        "Monthly ROI": [2.25, 1.67, 3.0],
    })
    computed = computed_z_roi(summary)
    table = fill_z_from_trades(default_table(2024, 2026), computed)
    assert table.loc[table["Year"] == 2026, "Z ROI%"].iat[0] == pytest.approx(3.92)
    assert table.loc[table["Year"] == 2025, "Z ROI%"].iat[0] == pytest.approx(3.0)
    total = with_grand_total(table)
    assert total.iloc[-1]["Year"] == "Grand Total"
    assert total.iloc[-1]["Z ROI%"] == pytest.approx(6.92)


def test_benchmarks_upload_accepts_row_labels_header_and_drops_total():
    import io
    from core.benchmarks import load_benchmarks
    raw = pd.DataFrame({"Row Labels": [2018, 2019, "Grand Total"], "Z ROI%": [3.97, 18.86, 22.83], "Nifty ROI%": [-0.13, 11.98, 11.85]})
    buf = io.BytesIO(); raw.to_csv(buf, index=False); buf.seek(0)
    table, errors = load_benchmarks(buf, "bench.csv")
    assert not errors and table["Year"].tolist() == [2018, 2019]
    assert table["Nifty ROI%"].tolist() == [-0.13, 11.98]


# ----------------------------------------------------------------- store ----
def test_store_roundtrip(tmp_path, monkeypatch):
    from core import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "USERS_FILE", tmp_path / "users.json")
    frame = pd.DataFrame({"month": pd.to_datetime(["2026-04-01"]), "stock": ["TCS"], "gross_profit": [100.5]})
    store.save_frame("user1", "trades", frame)
    back = store.load_frame("user1", "trades")
    assert back["month"].iloc[0] == pd.Timestamp("2026-04-01") and back["gross_profit"].iloc[0] == 100.5
    store.save_frame("user1", "trades", None)
    assert store.load_frame("user1", "trades") is None
    users = store.add_user(store.load_users(), "Priya")
    assert users[-1]["slug"] == "priya" and len(users) == 3
    store.save_users(users)
    assert store.load_users()[-1]["name"] == "Priya"


def test_trade_from_form_matches_sheet_formulas():
    import datetime as dt
    from core.parse import trade_from_form
    r = trade_from_form(buy_date=dt.date(2026, 4, 6), stock="TCS", type="Naked Put Sell", qty=175, buy=52.13,
                        sell=58.88, brokerage=48.5, margin=48000, lot=1)
    row = r.trades.iloc[0]
    assert row["pl"] == pytest.approx(175 * (58.88 - 52.13))
    assert row["gross_profit"] == pytest.approx(row["pl"] - 48.5)
    assert row["roi"] == pytest.approx(row["pl"] / 48000 * 100)
