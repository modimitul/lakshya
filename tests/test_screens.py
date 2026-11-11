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


def test_login_and_new_user_tabs(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    assert not at.exception
    assert not at.sidebar.selectbox, "gate should hide the app"
    # Login tab: unknown username is rejected, it does not silently create an owner
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password").set_value("secret")
    by_label(at.button, "Login").click().run()
    assert any("No login named" in e.value for e in at.error)
    # New user tab: wrong password rejected, correct password creates the owner and signs in
    by_label(at.text_input, "Choose a username").set_value("Priya")
    at.text_input(key="new_user_pw").set_value("wrong")
    by_label(at.button, "Create login").click().run()
    assert any("not correct" in e.value for e in at.error)
    by_label(at.text_input, "Choose a username").set_value("Priya")
    at.text_input(key="new_user_pw").set_value("secret")
    by_label(at.button, "Create login").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["signed_in_as"] == "priya"
    assert at.session_state["user"] == "priya"
    # fresh session: a second owner via New user, then an existing-name login works
    at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at2.run()
    by_label(at2.text_input, "Choose a username").set_value("Rahul")
    at2.text_input(key="new_user_pw").set_value("secret")
    by_label(at2.button, "Create login").click().run()
    names = sorted(u["name"] for u in at2.session_state["users"])
    assert names == ["Priya", "Rahul"]
    at3 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at3.run()
    by_label(at3.text_input, "Username").set_value("Priya")
    by_label(at3.text_input, "Password").set_value("secret")
    by_label(at3.button, "Login").click().run()
    assert not at3.exception and at3.session_state["signed_in_as"] == "priya"
    # duplicate username on New user is refused
    at4 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at4.run()
    by_label(at4.text_input, "Choose a username").set_value("priya")
    at4.text_input(key="new_user_pw").set_value("secret")
    by_label(at4.button, "Create login").click().run()
    assert any("already exists" in e.value for e in at4.error)


def test_open_positions_flow_and_dashboard_exclusion():
    import pandas as pd
    from core import store
    from core.parse import clean

    raw = pd.DataFrame({
        "Month": ["Oct-25", "Oct-25"],
        "Buy Date": [pd.Timestamp("2025-10-07"), pd.NaT],
        "Stock": ["TCS", "NIFTY"],
        "Type": ["Naked Call Sell", "Naked Put Sell"],
        "Strike Price": [3400, 25000],
        "QTY": [175, 75],
        "Buy": [52.13, None],          # NIFTY: sold, buy leg still open
        "Sale Date": [pd.Timestamp("2025-10-16"), pd.Timestamp("2025-10-10")],
        "Sell": [58.88, 120.0],
        "Brokerage": [48.5, 0.0],
    })
    trades = clean(raw).trades
    store.save_frame("owner", "trades", trades)

    at = app("screens/trading_input.py")
    body = str(at)
    assert "Open positions for" in body and "Trades saved for" in body
    # the open NIFTY row sits in the open grid, not in Trades saved (1 settled row)
    assert "Trades saved for Owner (1)" in body.replace(",", "")

    at.switch_page("screens/reports.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("open position(s) are excluded" in c.value for c in at.caption)
    # only the TCS trade counts
    assert any(m.label == "Net profit" for m in at.metric)
    assert any(m.label == "Avg yearly ROI" for m in at.metric)


def test_strategy_guide_page_renders():
    at = app("screens/strategy_guide.py")
    assert any(t.value == "Strategy Guide" for t in at.title)
    frames = at.get("dataframe")
    assert frames, "the strategies table should render"
    table = frames[0].value
    assert "Iron Condor" in set(table["Strategy"]) and len(table) >= 30


def test_manual_form_dates_follow_opening_side():
    at = app("screens/trading_input.py")
    at.radio[0].set_value("Add trades manually").run()
    # default type is Naked Call Sell -> sale date mandatory, buy date optional
    labels = [w.label for w in at.date_input]
    assert "Sale date *" in labels and "Buy date (optional)" in labels
    # a buy-opening type flips the pair
    by_label(at.selectbox, "Type").set_value("Naked Call Buy").run()
    labels = [w.label for w in at.date_input]
    assert "Buy date *" in labels and "Sale date (optional)" in labels
    # sell-first: entering only the sell leg saves an OPEN trade under the sale month
    by_label(at.selectbox, "Type").set_value("Naked Put Sell").run()
    by_label(at.text_input, "Stock").set_value("NIFTY")
    by_label(at.number_input, "Strike price *").set_value(25000)
    by_label(at.number_input, "Qty").set_value(75)
    by_label(at.number_input, "Sell price").set_value(142.0)
    by_label(at.button, "Add trade").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Added NIFTY" in s_.value for s_ in at.success)
    from core import store
    from core.parse import open_positions_mask
    saved = store.load_frame("owner", "trades")
    assert bool(open_positions_mask(saved).iloc[0])
    # buy-first: entering only the buy price must be refused without... actually buy-only is allowed (open long);
    # but a buy-first type with ONLY a sell price is refused
    by_label(at.selectbox, "Type").set_value("Naked Call Buy").run()
    by_label(at.text_input, "Stock").set_value("TCS")
    by_label(at.number_input, "Strike price *").set_value(3400)
    by_label(at.number_input, "Qty").set_value(100)
    by_label(at.number_input, "Sell price").set_value(58.88)
    by_label(at.button, "Add trade").click().run()
    assert any("opens with a buy" in e.value for e in at.error)


def test_investment_open_positions_record_sale():
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio

    raw = pd.DataFrame({
        "Month": ["Jul-23"], "Sector": ["CHEMICALS"], "Stock": ["SRF"],
        "QTY": [50], "Buy": [2179.17], "Cost": [50 * 2179.17],
    })
    store.save_frame("owner", "portfolio", clean_portfolio(raw).entries)

    at = app("screens/portfolio_input.py")
    assert "Open positions for" in str(at)
    grid = at.get("data_editor")
    assert grid, "open-positions editor should render"


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
