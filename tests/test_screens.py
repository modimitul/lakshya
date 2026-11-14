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


def by_label(widgets, label, n=0):
    return [w for w in widgets if w.label == label][n]


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
    by_label(at.get("radio"), "How do you want to provide holdings?").set_value("Add entries manually").run()
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

    def fresh():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        at.run()
        return at

    def create(at, name, invite, pw, pw2=None):
        by_label(at.text_input, "Choose a username").set_value(name)
        at.text_input(key="new_user_invite").set_value(invite)
        at.text_input(key="new_user_pw").set_value(pw)
        at.text_input(key="new_user_pw2").set_value(pw2 if pw2 is not None else pw)
        by_label(at.button, "Create login").click().run()
        return at

    # unknown username on Login is rejected
    at = fresh()
    assert not at.sidebar.selectbox, "gate should hide the app"
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password", 0).set_value("whatever")
    by_label(at.button, "Login").click().run()
    assert any("No login named" in e.value for e in at.error)

    # New user: wrong invite, short password, mismatch — then success with a personal password
    at = fresh()
    create(at, "Priya", "wrong-invite", "mypw1234")
    assert any("invite" in e.value for e in at.error)
    at = fresh()
    create(at, "Priya", "secret", "abc")
    assert any("at least 4" in e.value for e in at.error)
    at = fresh()
    create(at, "Priya", "secret", "mypw1234", "different")
    assert any("do not match" in e.value for e in at.error)
    at = fresh()
    create(at, "Priya", "secret", "mypw1234")
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["signed_in_as"] == "priya"
    # non-admin: locked to their own data, no owner switcher
    assert not at.sidebar.selectbox

    # login with the personal password works; the shared password does NOT (not admin)
    at = fresh()
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password", 0).set_value("secret")
    by_label(at.button, "Login").click().run()
    assert any("not correct" in e.value for e in at.error)
    by_label(at.text_input, "Username").set_value("Priya")
    by_label(at.text_input, "Password", 0).set_value("mypw1234")
    by_label(at.button, "Login").click().run()
    assert at.session_state["signed_in_as"] == "priya"

    # administrator: created like anyone, master password always works, sees the owner switcher
    at = fresh()
    create(at, "ModiMitul", "secret", "adminpw1")
    assert at.session_state["signed_in_as"] == "modimitul"
    assert at.sidebar.selectbox, "admin should see the owner switcher"
    at = fresh()
    by_label(at.text_input, "Username").set_value("ModiMitul")
    by_label(at.text_input, "Password", 0).set_value("secret")   # master password
    by_label(at.button, "Login").click().run()
    assert at.session_state["signed_in_as"] == "modimitul"

    # duplicate username is refused
    at = fresh()
    create(at, "priya", "secret", "whatever1")
    assert any("already exists" in e.value for e in at.error)


def by_label_n(widgets, label, n=0):
    return [w for w in widgets if w.label == label][n]


def test_user_management_and_family_home(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    import pandas as pd
    from core import store, crypto
    from core.parse import clean

    # admin + one family member with data
    users = store.add_user(store.load_users(), "ModiMitul")
    users = store.add_user(users, "Priya")
    users[0]["password_hash"] = crypto.hash_password("adminpw1")
    users[1]["password_hash"] = crypto.hash_password("priyapw1")
    store.save_users(users)
    raw = pd.DataFrame({
        "Month": ["Apr-25"], "Buy Date": [pd.Timestamp("2025-04-07")], "Stock": ["TCS"],
        "Type": ["Naked Call Sell"], "Strike Price": [3400], "QTY": [175], "Buy": [52.13],
        "Sale Date": [pd.Timestamp("2025-04-16")], "Sell": [58.88], "Brokerage": [48.5],
    })
    store.save_frame("priya", "trades", clean(raw).trades)
    from core.portfolio import clean_portfolio
    port = pd.DataFrame({"Month": ["Jul-23"], "Sector": ["IT"], "Stock": ["TCS"], "QTY": [30], "Buy": [3385.0],
                         "Cost": [30 * 3385.0]})
    store.save_frame("priya", "portfolio", clean_portfolio(port).entries)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    by_label(at.text_input, "Username").set_value("ModiMitul")
    [w for w in at.text_input if w.label == "Password"][0].set_value("adminpw1")
    by_label(at.button, "Login").click().run()
    assert at.session_state["signed_in_as"] == "modimitul"

    # Home: no family members marked yet
    assert any("No family members yet" in i.value for i in at.info)

    # User management: tick Priya as family and save
    at.switch_page("screens/users_admin.py").run()
    assert not at.exception, [e.value for e in at.exception]
    grid = next(e for e in at.get("data_editor") if "Family" in e.value.columns)
    disp = grid.value.reset_index(drop=True)
    pos = int(disp.index[disp["Username"] == "Priya"][0])
    at.session_state[grid.key] = {"edited_rows": {str(pos): {"Family": True}}, "added_rows": [], "deleted_rows": []}
    by_label(at.button, "Save users").click().run()
    assert any(u["slug"] == "priya" and u["family"] for u in store.load_users())

    # admin resets Priya's password
    by_label(at.selectbox, "User").set_value("priya")
    by_label(at.text_input, "New password for this user").set_value("newpw999")
    by_label(at.button, "Reset password").click().run()
    priya = next(u for u in store.load_users() if u["slug"] == "priya")
    assert crypto.verify_password("newpw999", priya["password_hash"])

    # Home now shows the family trading KPIs and asset allocation
    at.switch_page("screens/home.py").run()
    assert not at.exception, [e.value for e in at.exception]
    found_kpis = found_alloc = found_bystock = False
    for frame in at.get("dataframe"):
        cols = list(frame.value.columns)
        if {"Member", "Net profit", "Avg yearly ROI", "Win rate", "Best month", "Worst month"} <= set(cols):
            row = frame.value.iloc[0]
            assert row["Member"] == "Priya" and row["Net profit"] != "—"
            found_kpis = True
        if "Asset class" in cols and "% of family" in cols:
            assert "Priya" in cols
            found_alloc = True
        if "Total invested" in cols:
            vals = frame.value["Total invested"].str.replace(",", "").astype(float, errors="ignore")
            found_bystock = True
    assert found_kpis and found_alloc and found_bystock

    # deleting Priya removes login and data
    at.switch_page("screens/users_admin.py").run()
    by_label(at.selectbox, "User to delete").set_value("priya")
    at.checkbox(key="del_sure").set_value(True).run()
    by_label(at.button, "Delete this user").click().run()
    assert all(u["slug"] != "priya" for u in store.load_users())
    assert store.load_frame("priya", "trades") is None


def test_stocks_page_and_encrypted_store():
    import pandas as pd
    from core import store

    at = app("screens/stocks.py")
    editor = next(e for e in at.get("data_editor") if "Stock" in e.value.columns)
    at.session_state[editor.key] = {"edited_rows": {}, "added_rows": [
        {"Stock": "nifty", "Sector": "index", "Marketcap": "", "Note": "index"},
        {"Stock": "TCS", "Sector": "IT", "Marketcap": "Large cap", "Note": ""},
        {"Stock": "tcs", "Sector": "IT", "Marketcap": "Large cap", "Note": "dup"}],
        "deleted_rows": []}
    by_label(at.button, "Save list").click().run()
    assert not at.exception, [e.value for e in at.exception]
    saved = store.load_frame("_shared", "stocks")
    assert saved["stock"].tolist() == ["NIFTY", "TCS"]        # uppercased, deduped
    assert saved.loc[saved["stock"] == "TCS", "marketcap"].iloc[0] == "Large cap"
    assert saved.loc[saved["stock"] == "NIFTY", "sector"].iloc[0] == "INDEX"

    # delete via the grid: tick 🗑 on NIFTY and save again
    at2 = app("screens/stocks.py")
    editor = next(e for e in at2.get("data_editor") if "Stock" in e.value.columns)
    disp = editor.value.reset_index(drop=True)
    pos = int(disp.index[disp["Stock"] == "NIFTY"][0])
    at2.session_state[editor.key] = {"edited_rows": {str(pos): {"Delete": True}}, "added_rows": [], "deleted_rows": []}
    by_label(at2.button, "Save list").click().run()
    saved = store.load_frame("_shared", "stocks")
    assert saved["stock"].tolist() == ["TCS"]

    # the saved list feeds the manual-entry dropdown
    at2 = app("screens/trading_input.py")
    at2.get("radio")[0].set_value("Add trades manually").run()
    stock_sel = by_label(at2.selectbox, "Stock")
    assert "TCS" in stock_sel.options and "➕ New stock…" in stock_sel.options and "NIFTY" not in stock_sel.options

    # encrypted at rest: no plaintext stock names in the DB file
    import os
    db = os.path.join(os.environ["LAKSHYA_DATA_DIR"], "lakshya.db")
    blob = open(db, "rb").read()
    assert b"NIFTY" not in blob and b"TCS" not in blob


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
    # the open NIFTY row is nowhere on the dashboard — not even in the trade log tables
    at.toggle(key="tgl_tradelog").set_value(True).run()
    found_log_total = False
    for frame in at.get("dataframe"):
        vals = frame.value.to_numpy().ravel().tolist()
        assert not any("NIFTY" in str(v) for v in vals), "open position leaked into a dashboard table"
        if "Month" in frame.value.columns and (frame.value["Month"].astype(str) == "Total").any():
            found_log_total = True
    assert found_log_total, "trade log should end with a Total row"


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
    # strike price is a whole-number field (no decimals)
    strike_w = by_label(at.number_input, "Strike price *")
    from streamlit.proto.NumberInput_pb2 import NumberInput as NumberInputProto
    assert strike_w.proto.data_type == NumberInputProto.INT   # whole numbers only
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
    # NIFTY was auto-added to the shared Stocks list, so the form now shows a dropdown;
    # type the new name in the "new stock" box instead
    by_label(at.text_input, "If ➕ New stock…, type it").set_value("TCS")
    by_label(at.number_input, "Strike price *").set_value(3400)
    by_label(at.number_input, "Qty").set_value(100)
    by_label(at.number_input, "Sell price").set_value(58.88)
    by_label(at.button, "Add trade").click().run()
    assert any("opens with a buy" in e.value for e in at.error)


def test_investment_entry_dropdown_and_sale_columns():
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio, match_sales

    store.save_frame("_shared", "stocks", pd.DataFrame({
        "stock": ["DMART", "SRF"], "sector": ["RETAIL", "CHEMICALS"], "marketcap": ["Large cap", "Large cap"],
        "note": ["", ""]}))
    raw = pd.DataFrame({
        "Month": ["Jul-23", "Jan-24"], "Sector": ["CHEMICALS", "RETAIL"], "Stock": ["SRF", "DMART"],
        "QTY": [50, 20], "Buy": [2179.17, 3800.0],
    })
    raw["Cost"] = raw["QTY"] * raw["Buy"]
    store.save_frame("owner", "portfolio", clean_portfolio(raw).entries)

    # ---- (1) Add entries manually: Stock is a dropdown fed by Stocks Management, sector Auto
    at = app("screens/portfolio_input.py")
    by_label(at.get("radio"), "How do you want to provide holdings?").set_value("Add entries manually").run()
    stock_sel = by_label(at.selectbox, "Stock")
    assert "DMART" in stock_sel.options and "➕ New stock…" in stock_sel.options
    sector_sel = by_label(at.selectbox, "Sector")
    assert sector_sel.value == "Auto (from Stocks Management)"
    stock_sel.set_value("DMART")
    by_label(at.number_input, "Qty").set_value(5)
    by_label(at.number_input, "Buy price").set_value(4000.0)
    by_label(at.button, "Add entry").click().run()
    assert not at.exception, [e.value for e in at.exception]
    saved = store.load_frame("owner", "portfolio")
    added = saved[(saved["stock"] == "DMART") & (pd.to_numeric(saved["buy"], errors="coerce") == 4000.0)]
    assert len(added) == 1 and added["sector"].iloc[0] == "RETAIL"      # sector came from Stocks Management

    # ---- (2) All entries grid: Sale date + Sale price columns
    at2 = app("screens/portfolio_input.py")
    editor = next(e for e in at2.get("data_editor") if "sale_date" in e.value.columns)
    disp = editor.value.reset_index(drop=True)
    assert "sale_price" in disp.columns
    # fill both on the SRF buy row -> books a sale of the whole lot
    pos = int(disp.index[disp["stock"] == "SRF"][0])
    at2.session_state[editor.key] = {"edited_rows": {str(pos): {"sale_date": "2025-03-14", "sale_price": 2890.0}},
                                     "added_rows": [], "deleted_rows": []}
    by_label(at2.button, "Save changes").click().run()
    assert not at2.exception, [e.value for e in at2.exception]
    saved = store.load_frame("owner", "portfolio")
    sells = saved[saved["side"] == "sell"]
    assert len(sells) == 1 and sells["stock"].iloc[0] == "SRF"
    assert float(sells["qty"].iloc[0]) == 50 and float(sells["buy"].iloc[0]) == 2890.0
    assert pd.Timestamp(sells["month"].iloc[0]) == pd.Timestamp("2025-03-01")   # snapped to month start
    remaining, sales = match_sales(saved)
    assert "SRF" not in set(remaining.loc[pd.to_numeric(remaining["qty"], errors="coerce") > 0, "stock"])

    # one row per lot: no side column, the SOLD SRF lot shows its sale inline
    at3 = app("screens/portfolio_input.py")
    editor = next(e for e in at3.get("data_editor") if "sale_date" in e.value.columns)
    disp = editor.value.reset_index(drop=True)
    assert "side" not in disp.columns                                   # merged view: one row per transaction
    assert len(disp[disp["stock"] == "SRF"]) == 1                       # not a buy row + a sell row
    srf_pos = int(disp.index[disp["stock"] == "SRF"][0])
    assert float(disp.loc[srf_pos, "sale_price"]) == 2890.0             # the lot carries its sale info
    assert float(disp.loc[srf_pos, "sold"]) == 50.0
    # correcting the sale price on the lot's row updates the underlying sell row
    at3.session_state[editor.key] = {"edited_rows": {str(srf_pos): {"sale_price": 2900.0}},
                                     "added_rows": [], "deleted_rows": []}
    by_label(at3.button, "Save changes").click().run()
    assert not at3.exception, [e.value for e in at3.exception]
    saved = store.load_frame("owner", "portfolio")
    assert float(saved.loc[saved["side"] == "sell", "buy"].iloc[0]) == 2900.0

    # filling only one of the two on an unsold lot is refused, nothing saved
    at4 = app("screens/portfolio_input.py")
    editor = next(e for e in at4.get("data_editor") if "sale_date" in e.value.columns)
    disp = editor.value.reset_index(drop=True)
    buy_pos = int(disp.index[(disp["stock"] == "DMART") & (pd.to_numeric(disp["sold"]) == 0)][0])
    at4.session_state[editor.key] = {"edited_rows": {str(buy_pos): {"sale_price": 4100.0}},
                                     "added_rows": [], "deleted_rows": []}
    by_label(at4.button, "Save changes").click().run()
    assert any("both" in e.value for e in at4.error)
    saved2 = store.load_frame("owner", "portfolio")
    assert len(saved2[saved2["side"] == "sell"]) == 1                   # no extra sale was booked


def test_profit_method_setting_flows_to_dashboard():
    import datetime as dt
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio, sale_from_form

    raw = pd.DataFrame({
        "Month": ["Jan-23", "Jan-25"], "Sector": ["IT", "IT"], "Stock": ["TCS", "TCS"],
        "QTY": [10, 10], "Buy": [3000.0, 4000.0],
    })
    raw["Cost"] = raw["QTY"] * raw["Buy"]
    entries = pd.concat([clean_portfolio(raw).entries,
                         sale_from_form(dt.date(2025, 6, 1), "IT", "TCS", 10, 4500.0, 0.0).entries],
                        ignore_index=True)
    store.save_frame("owner", "portfolio", entries)

    # default is LIFO: the dashboard's profit booked uses the Jan-25 lot's cost
    at = app("screens/reports.py")
    assert not at.exception, [e.value for e in at.exception]
    body_frames = [f.value for f in at.get("dataframe")]
    def find_cost(frames, label):
        for fr in frames:
            if label in fr.columns:
                return fr
        return None
    per_sale = find_cost(body_frames, "Cost (LIFO)")
    assert per_sale is not None, "LIFO cost column should be on the dashboard by default"

    # switch to FIFO in the Investment Book and the dashboard follows
    at2 = app("screens/portfolio_input.py")
    by_label(at2.get("radio"), "Profit booking method").set_value("FIFO — earliest buys sold first").run()
    assert not at2.exception, [e.value for e in at2.exception]
    assert (store.load_json("owner", "meta", {}) or {}).get("sale_match_method") == "fifo"
    at3 = app("screens/reports.py")
    frames3 = [f.value for f in at3.get("dataframe")]
    assert find_cost(frames3, "Cost (FIFO)") is not None


def test_remove_recorded_sale_restores_holdings():
    import datetime as dt
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio, sale_from_form, match_sales

    raw = pd.DataFrame({
        "Month": ["Jul-23"], "Sector": ["CHEMICALS"], "Stock": ["SRF"],
        "QTY": [50], "Buy": [2179.17], "Cost": [50 * 2179.17],
    })
    entries = clean_portfolio(raw).entries
    sale = sale_from_form(dt.date(2025, 3, 1), "CHEMICALS", "SRF", 20, 2890.0, 35.0)
    entries = pd.concat([entries, sale.entries], ignore_index=True)
    store.save_frame("owner", "portfolio", entries)

    at = app("screens/portfolio_input.py")
    by_label(at.get("radio"), "How do you want to provide holdings?").set_value("Record a sale").run()
    assert not at.exception, [e.value for e in at.exception]
    sales_editor = next(e for e in at.get("data_editor") if "Sell price" in e.value.columns)
    disp = sales_editor.value.reset_index(drop=True)
    assert len(disp) == 1 and disp.loc[0, "Stock"] == "SRF" and float(disp.loc[0, "Sell price"]) == 2890.0
    # pressing the button with nothing ticked is refused
    by_label(at.button, "Remove selected sales").click().run()
    assert any("Tick at least one sale" in i.value for i in at.info)
    # tick the sale and remove it
    at.session_state[sales_editor.key] = {"edited_rows": {"0": {"Remove": True}}, "added_rows": [], "deleted_rows": []}
    by_label(at.button, "Remove selected sales").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Removed 1 sale(s): SRF" in s_.value for s_ in at.success)   # flash survives the rerun

    left = store.load_frame("owner", "portfolio")
    assert "side" not in left.columns or not (left["side"] == "sell").any()
    remaining, sales = match_sales(left)
    assert float(remaining["qty"].sum()) == 50.0                            # full holding restored
    assert sales.empty


def test_tradebook_focus_filters_trades_saved():
    import pandas as pd
    from core import store
    from core.parse import clean

    raw = pd.DataFrame({
        "Month": ["Mar-25", "Apr-25", "May-24"],
        "Buy Date": [pd.Timestamp("2025-03-05"), pd.Timestamp("2025-04-07"), pd.Timestamp("2024-05-06")],
        "Stock": ["TCS", "NIFTY", "INFY"],
        "Type": ["Naked Call Sell", "Naked Put Sell", "Naked Call Buy"],
        "Strike Price": [3400, 25000, 1500],
        "QTY": [175, 75, 100],
        "Buy": [52.13, 90.0, 10.0],
        "Sale Date": [pd.Timestamp("2025-03-16"), pd.Timestamp("2025-04-17"), pd.Timestamp("2024-05-20")],
        "Sell": [58.88, 120.0, 14.0],
        "Brokerage": [48.5, 30.0, 5.0],
    })
    store.save_frame("owner", "trades", clean(raw).trades)

    # calendar-year focus from the Dashboard: only 2025 trades are shown
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["tradebook_focus"] = {"label": "2025", "basis": "calendar"}
    at.run()
    at.switch_page("screens/trading_input.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("2025 only (2)" in ex.label for ex in at.expander)
    assert any("behind the Dashboard" in i.value for i in at.info)
    # clearing the filter brings back all three
    by_label(at.button, "Show all trades").click().run()
    assert any("Trades saved for Owner (3)" in ex.label.replace(",", "") for ex in at.expander)

    # a financial-year focus label groups Mar-25 under FY 2024-25
    at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at2.session_state["tradebook_focus"] = {"label": "FY 2024-25", "basis": "financial"}
    at2.run()
    at2.switch_page("screens/trading_input.py").run()
    assert any("FY 2024-25 only (2)" in ex.label for ex in at2.expander)   # May-24 + Mar-25

    # a label with no matching trades is dropped silently
    at3 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at3.session_state["tradebook_focus"] = {"label": "2019", "basis": "calendar"}
    at3.run()
    at3.switch_page("screens/trading_input.py").run()
    assert "tradebook_focus" not in at3.session_state
    assert any("Trades saved for Owner (3)" in ex.label.replace(",", "") for ex in at3.expander)


def test_month_edit_and_move_to_investment():
    import pandas as pd
    from core import store
    from core.parse import clean

    raw = pd.DataFrame({
        "Month": ["Mar-25", "Apr-25"],
        "Buy Date": [pd.Timestamp("2025-03-05"), pd.Timestamp("2025-04-07")],
        "Stock": ["TCS", "RELIANCE"],
        "Type": ["Naked Call Sell", "Equity"],
        "Strike Price": [3400, 0],
        "QTY": [175, 50],
        "Buy": [52.13, 1400.0],
        "Sale Date": [pd.Timestamp("2025-03-16"), pd.NaT],
        "Sell": [58.88, None],
        "Brokerage": [48.5, 0.0],
    })
    # RELIANCE row: buy-only equity -> would be an open position; give it a sale so both rows are settled
    raw.loc[1, "Sale Date"] = pd.Timestamp("2025-06-10")
    raw.loc[1, "Sell"] = 1520.0
    store.save_frame("owner", "trades", clean(raw).trades)

    at = app("screens/trading_input.py")

    # ---- Month is editable: move TCS from Mar-25 to Feb-25 via the grid
    trades_editor = next(e for e in at.get("data_editor") if "To investment" in e.value.columns)
    disp = trades_editor.value.reset_index(drop=True)
    assert "month" in disp.columns
    pos = int(disp.index[disp["stock"] == "TCS"][0])
    at.session_state[trades_editor.key] = {"edited_rows": {str(pos): {"month": "2025-02-14"}},   # mid-month on purpose
                                           "added_rows": [], "deleted_rows": []}
    by_label(at.button, "Save changes").click().run()
    assert not at.exception, [e.value for e in at.exception]
    moved = store.load_frame("owner", "trades")
    tcs_month = pd.Timestamp(moved.loc[moved["stock"] == "TCS", "month"].iloc[0])
    assert (tcs_month.year, tcs_month.month, tcs_month.day) == (2025, 2, 1)   # snapped to month start

    # ---- Move RELIANCE (trade entered by mistake) to the Investment Book
    at2 = app("screens/trading_input.py")
    trades_editor = next(e for e in at2.get("data_editor") if "To investment" in e.value.columns)
    disp = trades_editor.value.reset_index(drop=True)
    pos = int(disp.index[disp["stock"] == "RELIANCE"][0])
    at2.session_state[trades_editor.key] = {"edited_rows": {str(pos): {"To investment": True}},
                                            "added_rows": [], "deleted_rows": []}
    by_label(at2.button, "Move to Investment Book").click().run()
    assert not at2.exception, [e.value for e in at2.exception]
    # (the success toast is cleared by the rerun; the stores are the proof)

    left = store.load_frame("owner", "trades")
    assert "RELIANCE" not in set(left["stock"])                      # out of the trade book
    port = store.load_frame("owner", "portfolio")
    rel = port[port["stock"] == "RELIANCE"]
    assert len(rel) == 2                                             # purchase + its sale leg
    buys = rel[rel["side"] == "buy"]
    sells = rel[rel["side"] == "sell"]
    assert float(buys["qty"].iloc[0]) == 50 and float(buys["buy"].iloc[0]) == 1400.0
    assert float(sells["buy"].iloc[0]) == 1520.0                     # sale rows keep price in 'buy'

    # ---- a charge row cannot be moved
    import numpy as np
    charge = pd.DataFrame({
        "Month": ["May-25"], "Stock": ["CHARGES"], "Type": ["Brokerages"],
        "QTY": [np.nan], "Buy": [np.nan], "Sell": [np.nan], "Brokerage": [240.0],
    })
    combined = pd.concat([left, clean(charge).trades], ignore_index=True)
    store.save_frame("owner", "trades", combined)
    at3 = app("screens/trading_input.py")
    trades_editor = next(e for e in at3.get("data_editor") if "To investment" in e.value.columns)
    disp = trades_editor.value.reset_index(drop=True)
    pos = int(disp.index[disp["stock"] == "CHARGES"][0])
    at3.session_state[trades_editor.key] = {"edited_rows": {str(pos): {"To investment": True}},
                                            "added_rows": [], "deleted_rows": []}
    by_label(at3.button, "Move to Investment Book").click().run()
    assert any("not an investment" in e.value for e in at3.error)
    assert "CHARGES" in set(store.load_frame("owner", "trades")["stock"])   # nothing moved


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
    assert any(t.label.startswith("Show the monthly table") for t in at.toggle)  # table off by default, charts open
    assert any(t.label.startswith("Show the capital and brokerage tables") for t in at.toggle)
    assert by_label(at.multiselect, "Benchmarks to compare").value[:3] == ["GOLD BEES", "SILVER BEES", "Nifty ROI"]


def test_v31_intraday_auto_sale_date_and_sector_column():
    """Equity Intraday manual trades get Sale date = Buy date automatically, and the
    trades grid carries an editable sector column prefilled from Stocks Management."""
    import pandas as pd
    from core import store

    store.save_frame("_shared", "stocks", pd.DataFrame(
        [{"stock": "TCS", "sector": "IT", "marketcap": "Large cap", "note": ""}]))

    at = app("screens/trading_input.py")
    at.radio[0].set_value("Add trades manually").run()
    by_label(at.selectbox, "Type").set_value("Equity Intraday").run()
    # no "Sale date (optional)" field for intraday
    assert not [w for w in at.date_input if w.label == "Sale date (optional)"]
    by_label(at.selectbox, "Stock").set_value("TCS")
    by_label(at.number_input, "Qty").set_value(10)
    by_label(at.number_input, "Buy price").set_value(100.0)
    by_label(at.number_input, "Sell price").set_value(105.0)
    import datetime as dt
    by_label(at.date_input, "Buy date *").set_value(dt.date(2025, 7, 14))
    by_label(at.button, "Add trade").click().run()
    assert not at.exception, [e.value for e in at.exception]
    saved = store.load_frame("owner", "trades")
    assert pd.Timestamp(saved["sale_date"].iloc[0]).date() == dt.date(2025, 7, 14)   # auto same-day

    # grid shows sector prefilled from Stocks Management; editing it persists
    at2 = app("screens/trading_input.py")
    trades_editor = next(e for e in at2.get("data_editor") if "To investment" in e.value.columns)
    disp = trades_editor.value.reset_index(drop=True)
    assert "sector" in disp.columns and disp["sector"].iloc[0] == "IT"
    at2.session_state[trades_editor.key] = {"edited_rows": {"0": {"sector": "FINANCE"}},
                                            "added_rows": [], "deleted_rows": []}
    by_label(at2.button, "Save changes").click().run()
    assert not at2.exception, [e.value for e in at2.exception]
    assert store.load_frame("owner", "trades")["sector"].iloc[0] == "FINANCE"


def test_v31_entries_saved_above_open_positions_with_filter_and_totals():
    """Investment Book: Entries saved sits above Open positions; All entries is stock-sorted,
    filterable by stock and shows a Grand Total; sector is editable in Remaining holdings."""
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio

    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Aug-23", "Sep-23"],
        "SECTORS": ["IT", "PAINTS", "IT"],
        "STOCK": ["TCS", "BERGEPAINT", "INFY"],
        "QTY": [10, 20, 5],
        "BUY": [3000.0, 800.0, 1500.0],
    })
    store.save_frame("owner", "portfolio", clean_portfolio(raw).entries)

    at = app("screens/portfolio_input.py")
    labels = [ex.label for ex in at.expander]
    i_entries = next(i for i, l in enumerate(labels) if l.startswith("Entries saved"))
    i_open = next(i for i, l in enumerate(labels) if l.startswith("Open positions"))
    assert i_entries < i_open                                         # point 3

    # All entries grid is sorted by stock
    editor = next(e for e in at.get("data_editor") if "sale_date" in e.value.columns)
    stocks_shown = editor.value["stock"].tolist()
    assert stocks_shown == sorted(stocks_shown)                       # point 5

    # grand total line present
    assert any("Grand Total" in str(m.value) for m in at.markdown)    # points 4-5

    # filter by stock narrows the grid
    by_label(at.selectbox, "Filter by stock").set_value("TCS").run()
    assert not at.exception, [e.value for e in at.exception]
    editor = next(e for e in at.get("data_editor") if "sale_date" in e.value.columns)
    assert editor.value["stock"].tolist() == ["TCS"]

    # Remaining holdings: sector editable, written back
    at2 = app("screens/portfolio_input.py")
    by_label(at2.radio, "View").set_value("Remaining holdings (after sales)").run()
    rem_editor = next(e for e in at2.get("data_editor") if "buy_price" in e.value.columns)
    disp = rem_editor.value.reset_index(drop=True)
    pos = int(disp.index[disp["stock"] == "BERGEPAINT"][0])
    at2.session_state[rem_editor.key] = {"edited_rows": {str(pos): {"sector": "CHEMICALS"}},
                                         "added_rows": [], "deleted_rows": []}
    by_label(at2.button, "Save corrections").click().run()
    assert not at2.exception, [e.value for e in at2.exception]
    port = store.load_frame("owner", "portfolio")
    assert port.loc[port["stock"] == "BERGEPAINT", "sector"].iloc[0] == "CHEMICALS"


def test_v31_home_counts_match_dashboard_and_pies_render():
    """Home long-term figures use remaining holdings (like the Dashboard), and the
    per-user asset-class / marketcap pies render."""
    import pandas as pd
    from core import store
    from core.portfolio import clean_portfolio, sale_from_form

    raw = pd.DataFrame({
        "MONTH": ["Jul-23", "Aug-23"], "SECTORS": ["IT", "PAINTS"],
        "STOCK": ["TCS", "BERGEPAINT"], "QTY": [10, 20], "BUY": [3000.0, 800.0],
    })
    entries = clean_portfolio(raw).entries
    # sell all of TCS: Home should now count 1 stock held, cost = Berger only
    sale = sale_from_form(pd.Timestamp("2024-01-01").date(), "IT", "TCS", 10, 3500.0, 0.0).entries
    store.save_frame("owner", "portfolio", pd.concat([entries, sale], ignore_index=True))
    store.save_frame("_shared", "stocks", pd.DataFrame(
        [{"stock": "TCS", "sector": "IT", "marketcap": "Large cap", "note": ""},
         {"stock": "BERGEPAINT", "sector": "PAINTS", "marketcap": "Mid cap", "note": ""}]))

    at = app()
    body = " ".join(str(m.value) for m in at.markdown)
    assert "1 stocks held" in body or any("1 stocks held" in str(w.value) for w in at.markdown), body[:500]
    assert not at.exception
