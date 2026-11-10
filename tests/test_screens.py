"""Render every screen in every input mode headlessly, so widget errors surface in CI.

Run with:  pytest -q   (these take a few seconds each)
"""

import warnings
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

warnings.simplefilter("ignore")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))


ROOT = Path(__file__).resolve().parent.parent


def app(page=None):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    if page:
        at.switch_page(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def by_label(widgets, label):
    return next(w for w in widgets if w.label == label)


@pytest.mark.parametrize("page", [None, "screens/trading_input.py", "screens/portfolio_input.py", "screens/reports.py"])
def test_every_screen_renders_empty(page):
    app(page)


def test_trading_manual_form_adds_a_trade():
    at = app("screens/trading_input.py")
    at.radio[0].set_value("Add trades manually").run()
    assert not at.exception
    by_label(at.text_input, "Stock").set_value("TCS")
    by_label(at.number_input, "Qty").set_value(175)
    by_label(at.number_input, "Buy price").set_value(52.13)
    by_label(at.number_input, "Sell price").set_value(58.88)
    by_label(at.button, "Add trade").click().run()
    assert any("Strike price is required" in e.value for e in at.error)       # mandatory for option strategies
    by_label(at.text_input, "Stock").set_value("TCS")
    by_label(at.number_input, "Strike price *").set_value(3400)
    by_label(at.number_input, "Qty").set_value(175)
    by_label(at.number_input, "Buy price").set_value(52.13)
    by_label(at.number_input, "Sell price").set_value(58.88)
    by_label(at.button, "Add trade").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Added TCS" in s.value for s in at.success)
    # a Brokerages entry needs only the amount
    by_label(at.selectbox, "Type").set_value("Brokerages").run()
    by_label(at.number_input, "Brokerage & other charges (₹)").set_value(240.82)
    by_label(at.button, "Add charge entry").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Added charge entry" in s.value for s in at.success)
    from core import store
    saved = store.load_frame("owner", "trades")
    assert saved["type"].tolist() == ["Naked Call Sell", "Brokerages"] and saved["entry_kind"].tolist() == ["trade", "charge"]


def test_portfolio_manual_form_adds_an_entry():
    at = app("screens/portfolio_input.py")
    at.radio[0].set_value("Add entries manually").run()
    assert not at.exception, [e.value for e in at.exception]
    by_label(at.selectbox, "Purchase month").set_value("Jul")
    by_label(at.selectbox, "Year").set_value(2023)
    by_label(at.selectbox, "Sector").set_value("CHEMICALS")
    by_label(at.text_input, "Stock").set_value("SRF")
    by_label(at.number_input, "Qty").set_value(50)
    by_label(at.number_input, "Buy price").set_value(2179.17)
    by_label(at.button, "Add entry").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Added SRF" in s.value for s in at.success)
    # and the Reports screen now has something to show for this owner
    at.switch_page("screens/reports.py").run()
    assert not at.exception
    assert any(m.label == "Total invested" for m in at.metric)


def test_sign_in_with_new_username_creates_owner(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    assert not at.exception
    assert not at.sidebar.selectbox, "gate should hide the app"
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password").set_value("wrong")
    by_label(at.button, "Sign in").click().run()
    assert any("not correct" in e.value for e in at.error)
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password").set_value("secret")
    by_label(at.button, "Sign in").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["signed_in_as"] == "priya"
    assert at.session_state["user"] == "priya"
    # second person signs in in a fresh session: both owners exist, no placeholders
    at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at2.run()
    by_label(at2.text_input, "Username").set_value("Rahul")
    by_label(at2.text_input, "Password").set_value("secret")
    by_label(at2.button, "Sign in").click().run()
    names = sorted(u["name"] for u in at2.session_state["users"])
    assert names == ["Priya", "Rahul"]


def test_asset_class_rules_can_be_saved_from_the_dashboard(tmp_path, monkeypatch):
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    raw = pd.DataFrame({"MONTH": ["Jul-23", "Jul-23"], "SECTORS": ["GOLD", "BANKS"], "STOCK": ["GOLDBEES", "KOTAKBANK"],
                        "QTY": [1, 1], "BUY": [100, 200]})
    store.save_users([{"slug": "owner", "name": "Owner"}])
    store.save_frame("owner", "portfolio", clean_portfolio(raw).entries)
    at = app("screens/reports.py")
    assert by_label(at.multiselect, "ETF").value == ["GOLD"]          # auto rule: GOLDBEES is an ETF
    by_label(at.multiselect, "ETF").set_value([])
    by_label(at.multiselect, "Debt").set_value(["GOLD"])
    by_label(at.button, "Save asset class rules").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert store.load_json("owner", "meta")["asset_class_overrides"] == {"BANKS": "Equity", "GOLD": "Debt"}
    assert by_label(at.multiselect, "Debt").value == ["GOLD"]


def test_benchmarks_screen_renders_and_dashboard_compares(tmp_path, monkeypatch):
    import pandas as pd
    from core import store
    from core.parse import open_workbook, load_trades_workbook
    from core.metrics import months_in, capital_frame
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    at = app("screens/benchmarks.py")
    assert any("55 months" in m.value for m in at.markdown), [m.value for m in at.markdown][:3]
    # owner with capital → comparison section must appear, in both bases
    wb = open_workbook(open("/mnt/user-data/uploads/Book1.xlsx", "rb").read(), "Book1.xlsx")
    r = load_trades_workbook(wb, wb.sheet_names)
    store.save_users([{"slug": "owner", "name": "Owner"}])
    store.save_frame("owner", "trades", r.trades)
    cap = capital_frame(months_in(r.trades)); cap["Capital"] = pd.Series([3000000.0] * len(cap), dtype="Float64")
    store.save_frame("owner", "capital", cap)
    at = app("screens/reports.py")
    assert any(sh.value == "My returns vs benchmarks" for sh in at.subheader)
    by_label(at.radio, "Year basis").set_value("Financial (Apr–Mar)").run()
    assert not at.exception, [e.value for e in at.exception]
    yearly_table = at.dataframe[0].value
    assert yearly_table["Year"].iloc[0].startswith("FY ")


def test_default_owner_is_used_when_nobody_signed_in(tmp_path, monkeypatch):
    from core import store
    monkeypatch.setenv("LAKSHYA_DATA_DIR", str(tmp_path))
    store._engines.clear()
    store.save_users([{"slug": "rahul", "name": "Rahul"}, {"slug": "priya", "name": "Priya"}])
    store.save_json("_shared", "default_owner", "priya")
    at = app()
    assert at.session_state["user"] == "priya"
    # sections appear in the new order on the Trading tab: yearly before monthly, monthly collapsed
    store.save_frame("priya", "trades", __import__("pandas").DataFrame({
        "month": __import__("pandas").to_datetime(["2026-04-01"]), "buy_date": __import__("pandas").to_datetime(["2026-04-06"]),
        "stock": ["TCS"], "gross_profit": [100.0], "brokerage": [1.0], "entry_kind": ["trade"]}))
    at = app("screens/reports.py")
    assert not at.exception, [e.value for e in at.exception]
    headers = [h.value for h in at.subheader]
    expected = ["Yearly performance", "My returns vs benchmarks", "Monthly performance", "Capital and charges", "Breakdown"]
    assert [h for h in headers if h in expected] == expected        # yearly first, monthly after
    assert any(e.label.startswith("Monthly table") for e in at.expander)        # table collapsed, charts open
    assert any(e.label.startswith("Capital and brokerage tables") for e in at.expander)
    assert by_label(at.multiselect, "Benchmarks to compare").value[:3] == ["GOLD BEES", "SILVER BEES", "Nifty ROI"]
