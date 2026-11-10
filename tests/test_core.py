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
def test_seed_reproduces_the_annual_sheet():
    from core.benchmarks import seed_frame, comparison_table, period_label
    b = seed_frame()
    assert len(b) == 55 and b["month"].min() == pd.Timestamp("2022-04-01")
    yearly = b.assign(y=b["month"].dt.year).groupby("y")["Nifty ROI"].sum().round(2)
    assert yearly.loc[2023] == 19.06 and yearly.loc[2024] == 8.99 and yearly.loc[2026] == -11.25
    gold = b.assign(y=b["month"].dt.year).groupby("y")["GOLD BEES"].sum().round(2)
    assert gold.loc[2025] == 55.90
    assert period_label(pd.Series(pd.to_datetime(["2023-03-01", "2023-04-01"])), "financial").tolist() == ["FY 2022-23", "FY 2023-24"]


def test_comparison_table_sums_per_period_and_totals():
    from core.benchmarks import seed_frame, comparison_table
    summary = pd.DataFrame({"month": pd.to_datetime(["2026-03-01", "2026-04-01", "2026-05-01"]), "Monthly ROI": [1.0, 2.25, 1.67]})
    cal = comparison_table(summary, seed_frame(), "calendar", ["Nifty ROI"]).set_index("Period")
    assert cal.loc["2026", "Z ROI%"] == pytest.approx(4.92)
    assert cal.loc["2026", "Nifty ROI"] == pytest.approx(-11.31 + 7.46 - 1.87)   # Mar+Apr+May 2026 only, like for like
    assert list(cal.index) == ["2026", "Grand Total"]
    fin = comparison_table(summary, seed_frame(), "financial", ["Nifty ROI"]).set_index("Period")
    assert fin.loc["FY 2025-26", "Z ROI%"] == pytest.approx(1.0)
    assert fin.loc["FY 2026-27", "Z ROI%"] == pytest.approx(3.92)
    assert fin.loc["Grand Total", "Z ROI%"] == pytest.approx(4.92)


def test_monthly_benchmark_upload_accepts_old_headers_and_merges():
    import io
    from core.benchmarks import load_monthly_file, merge_monthly, seed_frame
    raw = pd.DataFrame({"Row Labels": ["Jan-22", "Apr-22", "Grand Total"], "Nifty ROI%": [-0.08, -9.99, 0], "Gold": [1.1, 2.2, 0]})
    buf = io.BytesIO(); raw.to_csv(buf, index=False); buf.seek(0)
    incoming, errors = load_monthly_file(buf, "b.csv")
    assert not errors and list(incoming.columns) == ["month", "Nifty ROI", "GOLD BEES"]
    merged = merge_monthly(seed_frame(), incoming).set_index("month")
    assert float(merged.loc["2022-01-01", "Nifty ROI"]) == -0.08          # new month added
    assert float(merged.loc["2022-04-01", "Nifty ROI"]) == -9.99          # incoming overwrites
    assert float(merged.loc["2022-04-01", "Nifty BEES ROI"]) == -1.82     # untouched column kept


def test_yearly_summary_financial_year_basis():
    from core.metrics import yearly_summary
    summary = pd.DataFrame({
        "month": pd.to_datetime(["2026-03-01", "2026-04-01"]),
        "Average of Capital": pd.array([1000000, 2000000], dtype="Float64"),
        "Net Profit": [100000.0, 50000.0], "Brokerage": [0.0, 0.0], "Trades": [1, 1],
    })
    fin = yearly_summary(summary, "financial")
    assert fin["Year"].tolist() == ["FY 2025-26", "FY 2026-27"]
    assert fin["Yearly ROI"].round(1).tolist() == [10.0, 2.5]
    assert yearly_summary(summary, "calendar")["Year"].tolist() == [2026]


# ----------------------------------------------------------------- store ----
def test_store_roundtrip(tmp_path, monkeypatch):
    from core import store
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    frame = pd.DataFrame({"month": pd.to_datetime(["2026-04-01"]), "stock": ["TCS"], "gross_profit": [100.5]})
    store.save_frame("user1", "trades", frame)
    back = store.load_frame("user1", "trades")
    assert back["month"].iloc[0] == pd.Timestamp("2026-04-01") and back["gross_profit"].iloc[0] == 100.5
    store.save_frame("user1", "trades", None)
    assert store.load_frame("user1", "trades") is None
    users = store.add_user(store.load_users(), "Priya")
    assert users[-1]["slug"] == "priya" and len(users) == 1
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


# ---------------------------------------------------- multi-sheet import ----
def _workbook(tmp_path):
    import pandas as pd
    path = tmp_path / "years.xlsx"
    y1 = pd.DataFrame({"Buy Date": ["2025-03-03"], "Month": ["2025-03-01"], "STOCK": ["TCS"], "Gross Profit": [100]})
    y2 = pd.DataFrame({"Buy Date": ["2026-04-06"], "Month": ["2026-04-01"], "STOCK": ["INFY"], "Gross Profit": [200]})
    cap = pd.DataFrame({"Row Labels": ["Mar-25", "Apr-26", "Grand Total"], "Average of Capital": ["10,00,000", "20,00,000", "15,00,000"]})
    with pd.ExcelWriter(path) as w:
        y1.to_excel(w, sheet_name="2025", index=False)
        y2.to_excel(w, sheet_name="2026", index=False)
        cap.to_excel(w, sheet_name="Capital", index=False)
    return path


def test_multi_sheet_import_detects_tabs_and_combines(tmp_path):
    from core.parse import list_sheets, looks_like_trade_sheet, load_trades_multi, dedupe_trades
    path = _workbook(tmp_path)
    with open(path, "rb") as f:
        sheets = list_sheets(f)
        assert [s for s in sheets if looks_like_trade_sheet(f, "years.xlsx", s)] == ["2025", "2026"]
        result = load_trades_multi(f, "years.xlsx", ["2025", "2026"])
    assert result.ok and len(result.trades) == 2
    assert sorted(result.trades["source_sheet"]) == ["2025", "2026"]
    merged, dropped = dedupe_trades(pd.concat([result.trades, result.trades]))
    assert len(merged) == 2 and dropped == 2


def test_capital_sheet_from_pivot(tmp_path):
    from core.parse import load_capital_sheet
    path = _workbook(tmp_path)
    with open(path, "rb") as f:
        cap, errors = load_capital_sheet(f, "years.xlsx", "Capital")
    assert not errors
    assert cap["month"].dt.strftime("%b-%y").tolist() == ["Mar-25", "Apr-26"]
    assert cap["Capital"].tolist() == [1000000, 2000000]


# -------------------------------------------------------------- sql store ----
def test_legacy_csv_is_imported_once(tmp_path, monkeypatch):
    import json
    from core import store
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    # files exactly as the previous (CSV) version wrote them
    (tmp_path / "jyoti").mkdir()
    pd.DataFrame({"month": ["2026-04-01"], "stock": ["TCS"], "gross_profit": [83353.0]}).to_csv(tmp_path / "jyoti" / "trades.csv", index=False)
    pd.DataFrame({"month": ["2026-04-01"], "Month": ["Apr-26"], "Capital": [3700000]}).to_csv(tmp_path / "jyoti" / "capital.csv", index=False)
    (tmp_path / "jyoti" / "meta.json").write_text(json.dumps({"trades_source": "Book1.xlsx"}))
    (tmp_path / "users.json").write_text(json.dumps([{"slug": "jyoti", "name": "Jyoti"}]))

    assert store.load_users() == [{"slug": "jyoti", "name": "Jyoti"}]
    trades = store.load_frame("jyoti", "trades")
    assert trades["month"].iloc[0] == pd.Timestamp("2026-04-01") and trades["gross_profit"].iloc[0] == 83353.0
    assert float(store.load_frame("jyoti", "capital")["Capital"].iloc[0]) == 3700000
    assert store.load_json("jyoti", "meta")["trades_source"] == "Book1.xlsx"
    assert (tmp_path / "jyoti.imported").exists() and not (tmp_path / "jyoti").exists()
    assert (tmp_path / "lakshya.db").exists()
    # a second engine start must not re-import or duplicate
    store._engines.clear()
    assert len(store.load_users()) == 1 and len(store.load_frame("jyoti", "trades")) == 1


def test_concurrent_saves_by_two_owners_do_not_clash(tmp_path, monkeypatch):
    import threading
    from core import store
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    store.save_users([{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}])
    errors = []

    def writer(slug, value):
        try:
            for i in range(20):
                store.save_frame(slug, "trades", pd.DataFrame({"month": pd.to_datetime(["2026-04-01"]), "stock": [slug], "gross_profit": [value + i]}))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=("a", 1000)), threading.Thread(target=writer, args=("b", 2000))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert store.load_frame("a", "trades")["gross_profit"].iloc[0] == 1019
    assert store.load_frame("b", "trades")["gross_profit"].iloc[0] == 2019


def test_schema_grows_when_a_frame_adds_a_column(tmp_path, monkeypatch):
    from core import store
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    store.save_frame("x", "portfolio", pd.DataFrame({"month": pd.to_datetime(["2023-07-01"]), "stock": ["SRF"], "cost": [108959.0]}))
    store.save_frame("y", "portfolio", pd.DataFrame({"month": pd.to_datetime(["2022-01-01"]), "stock": ["DMART"], "cost": [366044.0], "gift": [366044.0]}))
    assert store.load_frame("y", "portfolio")["gift"].iloc[0] == 366044.0
    assert store.load_frame("x", "portfolio")["cost"].iloc[0] == 108959.0  # x is untouched by y's new column


# ----------------------------------------------------------- asset classes ----
def test_asset_class_rules_and_overrides():
    from core.portfolio import clean_portfolio, with_asset_class, asset_class_summary, sector_class_map
    raw = pd.DataFrame({
        "MONTH": ["Jul-23"] * 6,
        "SECTORS": ["CHEMICALS", "ETF", "MF", "DEBT", "GOLD", "FMCG"],
        "STOCK": ["SRF", "NIFTYBEES", "HDFC INNOVATION FUND - DIRECT PLAN", "SGB 2032", "GOLDBEES", "HINDUNILVR"],
        "QTY": [1] * 6, "BUY": [100, 200, 300, 400, 500, 600],
    })
    entries = clean_portfolio(raw).entries
    classified = with_asset_class(entries)
    assert classified.set_index("stock")["asset_class"].to_dict() == {
        "SRF": "Equity", "NIFTYBEES": "ETF", "HDFC INNOVATION FUND - DIRECT PLAN": "Equity MF",
        "SGB 2032": "Debt", "GOLDBEES": "ETF", "HINDUNILVR": "Equity",
    }
    summary = asset_class_summary(classified)
    assert summary["Asset class"].tolist() == ["Equity", "ETF", "Equity MF", "Debt"]
    assert summary["Cost"].tolist() == [700, 700, 300, 400]
    assert sector_class_map(entries, {"GOLD": "Debt"})["GOLD"] == "Debt"
    assert with_asset_class(entries, {"GOLD": "Debt"}).query("stock == 'GOLDBEES'")["asset_class"].iat[0] == "Debt"


# ------------------------------------------------------------------ yearly ----
def test_yearly_summary_matches_the_year_labels_pivot():
    from core.metrics import yearly_summary, yearly_with_total
    # two years; 2026 has one month without capital, which must still count toward profit
    summary = pd.DataFrame({
        "month": pd.to_datetime(["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01"]),
        "Average of Capital": pd.array([2500000, 3050000, 1500000, 2175000, None], dtype="Float64"),
        "Net Profit": [200000.0, 229984.0, 100000.0, 200000.0, 108224.0],
        "Brokerage": [1000.0, 1000.0, 500.0, 500.0, 500.0],
        "Trades": [10, 12, 8, 9, 7],
    })
    y = yearly_summary(summary)
    assert y["Year"].tolist() == [2025, 2026]
    assert y["Investments"].tolist() == [2775000.0, 1837500.0]
    assert y["Net Profit"].tolist() == [429984.0, 408224.0]
    assert [round(v) for v in y["Yearly ROI"]] == [15, 22]          # 429984/2775000, 408224/1837500
    t = yearly_with_total(y)
    assert t.iloc[-1]["Year"] == "Grand Total"
    assert t.iloc[-1]["Investments"] == pytest.approx((2775000 + 1837500) / 2)
    assert t.iloc[-1]["Net Profit"] == pytest.approx(838208.0)
    assert t.iloc[-1]["Yearly ROI"] == pytest.approx((y["Yearly ROI"].iloc[0] + y["Yearly ROI"].iloc[1]) / 2)


# ----------------------------------------------------------- charge entries ----
def test_charge_entries_are_not_trades_but_still_cost_money():
    from core.metrics import monthly_summary, kpis, breakdown, charge_mask
    raw = pd.DataFrame({
        "Buy Date": ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"],
        "Month": ["2026-04-01"] * 5,
        "STOCK": ["TCS", "EQUITY SIP", "EQUITY SIP", "TCS", "INFY"],
        "Strike Price": [3400, "BROKERAGE", "DP Charges", "FUTURE", 1500],
        "TYPE": ["Naked Put Sell", "Equity", "Equity", "FUTURE Long", "Naked Put Sell"],
        "QTY": [175, 1, 1, 175, 400], "Buy": [52.13, 0, 0, 2325, 20], "Sell": [58.88, 0, 0, 2335, 15],
        "Brokerage & Other Charges": [48.5, 240.82, 15.34, 60, 40],
    })
    result = clean(raw)
    t = result.trades
    assert t["entry_kind"].tolist() == ["trade", "charge", "charge", "trade", "trade"]
    assert t["strike_label"].tolist()[1:4] == ["BROKERAGE", "DP CHARGES", "FUTURE"]
    assert any("charge entries" in n for n in result.notes)
    summary = monthly_summary(t)
    assert summary["Trades"].iat[0] == 3 and summary["Charges"].iat[0] == 2
    assert summary["Net Profit"].iat[0] == pytest.approx(t["gross_profit"].sum())      # charges still cost money
    k = kpis(summary, t)
    assert k["win_rate"] == pytest.approx(2 / 3 * 100) and k["trades"] == 3 and k["charges"] == 2
    assert t["type"].tolist() == ["Naked Put Sell", "Brokerages", "Brokerages", "FUTURE Long", "Naked Put Sell"]
    assert pd.isna(t["strike"].iloc[1]) and pd.isna(t["strike"].iloc[2])      # strike cleared on charge rows
    by_type = breakdown(t, "type").set_index("Type")
    assert by_type.loc["Brokerages", "Trades"] == 0 and by_type.loc["Brokerages", "Net Profit"] < 0
    assert by_type.loc["Naked Put Sell", "Bias"] == "🐂 Bull"
    # data saved before entry_kind existed is classified structurally
    legacy = t.drop(columns=["entry_kind", "strike_label"])
    assert charge_mask(legacy).tolist() == [False, True, True, False, False]


# ------------------------------------------------------------ sales / CAGR ----
def test_fifo_sale_matching_profit_roi_cagr():
    from core.portfolio import clean_portfolio, match_sales, sales_summary, holdings
    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Jan-24", "Mar-26", "Jan-22"], "SECTORS": ["CHEMICALS", "CHEMICALS", "CHEMICALS", "RETAIL"],
        "STOCK": ["SRF", "SRF", "SRF", "DMART"], "QTY": [50, 30, 60, 100], "BUY": [2000, 2500, 3000, 3660.44],
        "SIDE": ["BUY", "BUY", "SELL", "BUY"], "CHARGES": [None, None, 100, None],
    })
    entries = clean_portfolio(raw).entries
    assert entries["side"].tolist() == ["buy", "buy", "sell", "buy"]
    remaining, sales = match_sales(entries)
    sale = sales.iloc[0]
    assert sale["cost"] == pytest.approx(50 * 2000 + 10 * 2500)          # oldest lots first
    assert sale["sale_value"] == pytest.approx(60 * 3000 - 100)
    assert sale["profit"] == pytest.approx(54900) and sale["roi"] == pytest.approx(43.92)
    assert sale["years"] == pytest.approx((100000 * 32 / 12 + 25000 * 26 / 12) / 125000)
    assert sale["cagr"] == pytest.approx(((179900 / 125000) ** (1 / sale["years"]) - 1) * 100)
    held = holdings(remaining).set_index("Stock")
    assert held.loc["SRF", "Qty"] == 20 and held.loc["SRF", "Cost"] == 50000
    assert held.loc["DMART", "Qty"] == 100
    assert sales_summary(sales)["profit"] == pytest.approx(54900)


def test_trading_cagr_kpi_and_benchmark_cagr_table():
    from core.metrics import cagr_from_monthly, monthly_summary, kpis
    from core.benchmarks import seed_frame, cagr_table
    assert cagr_from_monthly(pd.Series([1.0] * 12)) == pytest.approx((1.01 ** 12 - 1) * 100)
    assert cagr_from_monthly(pd.Series([2.0] * 6)) == pytest.approx((1.02 ** 12 - 1) * 100)   # annualised
    assert cagr_from_monthly(pd.Series([], dtype=float)) is None
    summary = pd.DataFrame({"month": pd.to_datetime(["2026-04-01", "2026-05-01"]), "Monthly ROI": [2.0, 2.0]})
    cg = cagr_table(summary, seed_frame(), "calendar", ["Nifty ROI"]).set_index("Period")
    assert cg.loc["Overall", "Months"] == 2
    assert cg.loc["Overall", "Z ROI%"] == pytest.approx((1.02 ** 12 - 1) * 100)
    assert cg.loc["Overall", "Nifty ROI"] == pytest.approx(((1.0746 * (1 - 0.0187)) ** 6 - 1) * 100, rel=1e-3)


def test_replace_only_covered_months():
    from core.parse import replace_covered_months
    existing = pd.DataFrame({"month": pd.to_datetime(["2024-04-01", "2024-05-01", "2025-04-01"]), "stock": ["A", "B", "C"], "gross_profit": [1.0, 2.0, 3.0]})
    incoming = pd.DataFrame({"month": pd.to_datetime(["2024-04-01", "2024-04-01"]), "stock": ["A2", "A3"], "gross_profit": [10.0, 11.0]})
    merged, removed, months = replace_covered_months(existing, incoming)
    assert removed == 1 and months == [pd.Timestamp("2024-04-01")]
    assert sorted(merged["stock"]) == ["A2", "A3", "B", "C"]          # Apr-24 replaced; May-24 and Apr-25 kept
    merged2, removed2, _ = replace_covered_months(None, incoming)
    assert removed2 == 0 and len(merged2) == 2


def test_liquid_fund_asset_class_and_fund_sectors():
    from core.portfolio import clean_portfolio, with_asset_class, asset_class_summary, COMMON_SECTORS
    raw = pd.DataFrame({
        "MONTH": ["Jul-23"] * 4,
        "SECTORS": ["LIQUID FUND", "DEBT FUND", "MUTUAL FUND", "ETF"],
        "STOCK": ["PARAG PARIKH LIQUID", "HDFC CORPORATE BOND FUND", "PARAG PARIKH FLEXI CAP", "NIFTYBEES"],
        "QTY": [1] * 4, "BUY": [100, 200, 300, 400],
    })
    classified = with_asset_class(clean_portfolio(raw).entries)
    assert classified.set_index("sector")["asset_class"].to_dict() == {
        "LIQUID FUND": "Liquid Fund", "DEBT FUND": "Debt", "MUTUAL FUND": "Equity MF", "ETF": "ETF",
    }
    assert asset_class_summary(classified)["Asset class"].tolist() == ["ETF", "Equity MF", "Debt", "Liquid Fund"]
    for sector in ("MUTUAL FUND", "DEBT FUND", "LIQUID FUND", "ETF"):
        assert sector in COMMON_SECTORS


def test_yearly_sales_summary_groups_by_sale_year():
    from core.portfolio import clean_portfolio, match_sales, yearly_sales_summary
    raw = pd.DataFrame({
        "MONTH": ["Jan-22", "Jan-23", "Mar-25", "Jun-25", "Feb-26"],
        "SECTORS": ["RETAIL", "RETAIL", "RETAIL", "RETAIL", "RETAIL"],
        "STOCK": ["DMART", "DMART", "DMART", "DMART", "DMART"],
        "QTY": [100, 50, 40, 30, 20], "BUY": [3000, 3500, 4000, 4200, 4500],
        "SIDE": ["BUY", "BUY", "SELL", "SELL", "SELL"], "CHARGES": [None, None, 0, 0, 0],
    })
    _, sales = match_sales(clean_portfolio(raw).entries)
    ysum = yearly_sales_summary(sales).set_index("Year")
    assert list(ysum.index) == [2025, 2026]
    assert ysum.loc[2025, "Sales"] == 2
    # 2025: 70 shares sold FIFO from the 100 @3000 lot
    assert ysum.loc[2025, "Cost"] == pytest.approx(70 * 3000)
    assert ysum.loc[2025, "Profit"] == pytest.approx(40 * 4000 + 30 * 4200 - 70 * 3000)
    assert ysum.loc[2025, "ROI %"] == pytest.approx(ysum.loc[2025, "Profit"] / ysum.loc[2025, "Cost"] * 100)
    # 2026: 20 shares from the remaining 30 @3000
    assert ysum.loc[2026, "Cost"] == pytest.approx(20 * 3000)
    assert ysum.loc[2026, "CAGR %"] is not None


def test_buys_without_quantity_are_never_treated_as_sold():
    from core.portfolio import clean_portfolio, match_sales
    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Jan-22", "Sep-23", "Feb-26"],
        "SECTORS": ["MUTUAL FUND", "RETAIL", "CHEMICALS", "CHEMICALS"],
        "STOCK": ["PP FLEXI CAP SIP", "DMART", "SRF", "SRF"],
        "QTY": [None, 100, 50, 20], "BUY": [None, 3660.44, 2179.17, 2900],
        "COST": [250000, 366044, 108958.5, None],
        "SIDE": ["BUY", "BUY", "BUY", "SELL"], "CHARGES": [None, None, None, 45],
    })
    remaining, sales = match_sales(clean_portfolio(raw).entries)
    held = remaining.set_index("stock")["cost"]
    assert held["PP FLEXI CAP SIP"] == 250000            # qty-less buy survives at full cost
    assert held["DMART"] == 366044                       # untouched lot keeps its exact cost
    assert held["SRF"] == pytest.approx(108958.5 * 30 / 50)
    assert len(remaining) == 3 and len(sales) == 1
    assert sales.iloc[0]["cost"] == pytest.approx(108958.5 * 20 / 50)


# -------------------------------------------------------------- grid edits ----
def test_recompute_trades_after_square_off_edit():
    from core.parse import apply_grid_edits, recompute_trades
    trades = clean(pd.DataFrame({
        "Buy Date": ["2026-04-06", "2026-04-07"], "Month": ["2026-04-01", "2026-04-01"],
        "STOCK": ["TCS", "INFY"], "Strike Price": [3400, 1500], "TYPE": ["Naked Put Sell", "Naked Put Sell"],
        "QTY": [175, 400], "Buy": [52.13, 20.0], "Sell": [0.0, 15.0],
        "Brokerage & Other Charges": [0, 40], "Margin": [48000, 50000], "Lot": [1, 1],
    })).trades
    order = trades.index
    edited = trades.copy()
    edited["sell"] = edited["sell"].astype("float64")
    edited["brokerage"] = edited["brokerage"].astype("float64")   # data_editor returns float columns
    edited.insert(0, "Remove", False)
    edited.at[order[0], "sell"] = 58.88          # square off the open TCS position
    edited.at[order[0], "brokerage"] = 48.5
    updated, changed = apply_grid_edits(trades, order, edited, ["sell", "brokerage", "stock", "qty", "buy"])
    assert changed == [order[0]]
    updated = recompute_trades(updated, changed)
    row = updated.loc[order[0]]
    assert row["pl"] == pytest.approx(175 * (58.88 - 52.13))
    assert row["gross_profit"] == pytest.approx(row["pl"] - 48.5)
    assert row["roi"] == pytest.approx(row["pl"] / 48000 * 100)
    assert row["entry_kind"] == "trade"
    # untouched row keeps its original figures exactly
    assert updated.loc[order[1], "gross_profit"] == trades.loc[order[1], "gross_profit"]


def test_cell_changed_handles_na_dates_and_floats():
    import datetime as dt
    from core.parse import cell_changed
    assert not cell_changed(float("nan"), None)
    assert not cell_changed(pd.NaT, None)
    assert cell_changed(None, 5)
    assert not cell_changed(52.130000001, 52.13)
    assert cell_changed(pd.Timestamp("2026-04-06"), dt.date(2026, 4, 7))
    assert not cell_changed(pd.Timestamp("2026-04-06"), dt.date(2026, 4, 6))
    assert cell_changed("buy", "sell") and not cell_changed("buy", "buy")


def test_match_sales_keeps_buys_without_quantity():
    from core.portfolio import clean_portfolio, match_sales
    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Jan-24", "Mar-26"], "SECTORS": ["RETAIL", "IT", "RETAIL"],
        "STOCK": ["DMART", "TCS", "DMART"], "QTY": [100, None, 100], "BUY": [3000, None, 4000],
        "COST": [300000, 500000, None], "SIDE": ["BUY", "BUY", "SELL"], "CHARGES": [None, None, 0],
    })
    remaining, sales = match_sales(clean_portfolio(raw).entries)
    held = remaining.set_index("stock")
    assert "TCS" in held.index and held.loc["TCS", "cost"] == 500000     # no qty → still a holding
    assert "DMART" not in held.index                                     # fully sold
    assert sales.iloc[0]["cost"] == pytest.approx(300000)
