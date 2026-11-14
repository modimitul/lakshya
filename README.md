# Lakshya

Trading and long-term-investment dashboards for up to any number of portfolio
owners, built from Excel uploads or simple entry forms. Python + Streamlit.

**Screens**

| Screen | What it does |
|---|---|
| Home | Status card per owner, owner names, how the numbers are calculated |
| Trading Book | Trades by upload or an adaptive *Add trade* form (pick the Type first; Brokerages needs only date, description, amount; strike mandatory for option strategies); strategy guide; **editable saved-trades grid** (fill Sell/Sale date to square off; P&L, gross profit and ROI recalculate on Save); monthly capital |
| Benchmarks | Monthly % returns of indices/ETFs (Nifty, Nifty BEES, Bank Nifty, NIFTY IT, NASDAQ, DJI, MAFANG, Gold BEES, Silver BEES), shared by all owners; grid or upload; ships with Apr-2022 → Oct-2026 built in |
| Investment Book | Holdings by upload (full template MONTH/SECTORS/STOCK/QTY/BUY/COST, **or a simple lot list with just Buy Date, STOCK, QTY, Buy, Cost — missing sectors are auto-filled from Stocks Management, anything unmapped lands in OTHER with a warning**) or an *Add entry* form: month, sector, stock, qty, buy, gift; *Record a sale* (month, stock, qty up to what is held, sell price, charges); uploads may carry a SIDE column (BUY/SELL); **editable entries grid** with an *All entries / Remaining holdings (after sales)* toggle — the Remaining view is also editable: corrections write back to the original lot, leaving sold portions and past profit untouched; **SIP plans** auto-post one BUY row per month per active plan (fund, amount, day, start month; Cost = amount, sector default MUTUAL FUND, Qty blank), catching up months missed while the app was closed |
| Dashboard Reports → Trading | Year basis toggle (calendar Jan–Dec or financial Apr–Mar) and Year filter; KPIs incl. CAGR; Yearly performance (chart, then table); *My returns vs benchmarks* (default: Gold BEES, Silver BEES, Nifty, Bank Nifty, NIFTY IT, NASDAQ, DJI): total-return table + one bar of Grand Totals, then CAGR table + one bar of Overall CAGR; Monthly performance with its own *Months to show* selector (charts open, table collapsed); Capital and charges (chart open, tables collapsed); breakdown; trade log; Excel download. Charts sit above tables throughout. |
| Dashboard Reports → Investments | Reconciliation line (purchase/sale rows and value on file); Year / sector / month filters; asset-class overview (Equity, ETF, Equity MF, Debt, Liquid Fund); *Profit booked on sales* (matched cost — LIFO by default, FIFO selectable in the Investment Book — profit, ROI, years held, CAGR, per sale and overall); a sub-tab per class with remaining holdings by stock, % Investment, sector allocation, gifts; Excel download |

A **Portfolio owner** selector in the sidebar switches between owners. Each
owner's data is saved in a SQL database on the server (SQLite file
`data/lakshya.db` by default), so it survives refreshes and restarts and two
owners can save at the same moment safely.

## How the numbers work

| Figure | Source |
|---|---|
| Net Profit | Sum of each trade's `Gross Profit` for the month (P&L minus brokerage and charges). Derived from Qty × (Sell − Buy) − charges if the file lacks it. |
| Average of Capital | Entered per month on the Trading Book screen (or the per-month mean of a `Capital` column). Grand Total = average of months. |
| Brokerage | Sum of `Brokerage & Other Charges` per month. Grand Total = sum. |
| Charge entries | Rows whose Strike Price reads BROKERAGE / …CHARGES (or with Buy = Sell = P/L = 0 and charges > 0) become Type = **Brokerages** with the strike cleared (the label is kept in `strike_label`). They count in Net Profit and Brokerage but not in trade counts or win rate. Rows labelled FUTURE / EQUITY / MF with real prices remain trades. |
| Types | The Type column is matched case-insensitively to the strategy catalogue in `core/strategies.py` (Naked Put Sell, Iron Condor, FUTURE Long, Long Build Up, Brokerages …), each with a definition and Bull/Bear/Neutral bias shown in the form, the Strategy guide and the breakdown by Type. Strike Price is mandatory in the form for option strategies and not applicable to Brokerages, Equity, Debt, Futures and OI types. |
| Win rate | Trades with positive gross profit ÷ trades, excluding charge entries. |
| Monthly ROI | Net Profit ÷ Average of Capital × 100. The monthly Grand Total and the comparison's `Z ROI%` = sum of monthly ROI. |
| CAGR (trading) | Monthly ROIs compounded and annualised: (∏(1 + ROI))^(12 ÷ months) − 1, over months with capital. Shown under Avg monthly ROI and, per period and overall, in the benchmark comparison (benchmarks compounded over the same months). |
| SIP plans | Managed on Investment Book. Due instalments post automatically when the Investment Book or Investments dashboard opens; `last_applied` on each plan makes posting idempotent. Posted rows carry the marker `SIP`. |
| Sales (long-term) | SELL rows are matched to BUY rows of the same stock — **LIFO (latest lots first) by default; switch to FIFO** with the Profit booking method control in the Investment Book. Profit = net sale value − cost of matched lots; ROI = profit ÷ cost; years held = cost-weighted months ÷ 12 (minimum one month); CAGR = (sale value ÷ cost)^(1 ÷ years) − 1. Holdings everywhere are what remains after sales. |
| Yearly ROI | Period's Net Profit ÷ Investments × 100, where Investments = average of that period's monthly capital; period = calendar year or financial year (Apr–Mar, labelled e.g. FY 2024-25). Grand Total averages Investments and ROI across periods. |
| Benchmarks | Monthly % returns kept on the Benchmarks screen. In the comparison, `Z ROI%` and each benchmark are the SUM of monthly values per calendar or financial year, summed over the same months the owner has ROI. Grand Total = sum of listed periods. |
| % Investment | Stock cost ÷ total cost of the holdings currently shown × 100 (inside a class tab, the class total). |
| Asset class | From the SECTORS label, then the stock name, checked in order: LIQUID/OVERNIGHT/MONEY MARKET/ULTRA SHORT/ARBITRAGE → Liquid Fund; DEBT/BOND/SGB/GILT/FD/NCD → Debt; ETF/BEES → ETF; MF/MUTUAL/FUND → Equity MF; otherwise Equity. Adjust per owner under *Asset class rules* on the Investments tab. |

Rows whose period is not a calendar month (e.g. `YEAR 2026`) are shown under
"Excluded rows" and left out of monthly totals. Formatted-but-empty Excel rows,
`#NUM!` / `#DIV/0!` cells, text months like `Jul-23` and Indian-formatted numbers
like `1,08,959` are all handled.

## What's new in 3.0

- **Personal passwords**: each login has its own password. `APP_PASSWORD` is now the
  *invite code* for creating a login and the administrator's master password.
  Users from the shared-password era log in once with the old shared password,
  which then becomes their personal one. **Forgot password?** The administrator
  resets it in *User management*.
- **Administrator**: the login `ModiMitul` (slug `modimitul`). Only the
  administrator can switch portfolio owners, manage owners/users, and see the
  family dashboards; every other login sees only its own data.
- **User management** (menu): change your own password; the administrator can
  reset passwords, delete a user (with all their data), and tick **Family** on
  logins — family members' combined dashboards appear on the administrator's Home.
- **Stocks** (menu): one shared list of instruments with add / edit / delete /
  save; it feeds the Stock dropdown in the Trading Book's manual entry, and a
  newly typed name is added to the list automatically.
- **Encrypted at rest**: all books are stored in the database as encrypted
  blobs (Fernet/AES). The key lives in `LAKSHYA_SECRET_KEY` (optional) or in
  `<data dir>/.secret.key` (created automatically, mode 600). **Back up the key
  file together with the database** — without it the data is unreadable. Data
  from older versions is migrated (and the plaintext removed) on first read.
- **Second upload template**: Sharekhan-style intraday sheets (Buy Date, Stock,
  Qty, Buy, Sell, Profit/Loss, Brokerage and Other Charges, numeric month;
  no Type/Sale Date/Strike) import correctly: rows become Equity trades with
  same-day exits, the running Gross-Profit column is recomputed per row, and
  EQUITY charge rows count against net profit.

## Login and owners

Set `APP_PASSWORD` in the environment (the Lightsail setup script passes it into
the service) and the app shows one login screen with two tabs:

- **Login** — an existing username plus the shared password. An unknown
  username is refused with a pointer to the New user tab.
- **New user** — creates a new portfolio owner (no limit on users) with the
  same shared password and signs them in.

The sidebar shows who is logged in, lets you switch owner, has *Rename or add
owner* and *Make this the default owner* (the default owner is shown first when
nobody has logged in; also settable on Home), and a **Logout** button. There
are no per-user passwords: anyone with the shared password can view every
owner's data. If you need strict separation, ask for per-user passwords; it is
a small change.

Without `APP_PASSWORD` (for example when running locally) there is no login
screen and a single owner called "Owner" is used.

## Strategy Guide and open positions

- **Strategy Guide** is its own page in the menu (after Home): every trade
  Type with its definition and Bull/Bear/Neutral bias, searchable.
- **Trading Book → Open positions** lists trades with one leg still missing
  (e.g. sold, not yet bought back): they stay out of every dashboard figure
  until closed. Fill the missing price + date (0 with the expiry date for an
  option that expired worthless) and press **Close / save** — the row moves to
  Trades saved and starts counting in the Dashboard, which also notes how many
  open positions are excluded.
- **Investment Book → Open positions** lists everything still held (purchases
  minus matched sales) one row per stock; fill Sell qty / Sell price /
  charges / sale month and press **Record sales** to book sales in bulk —
  the SELL rows land in Entries saved and profit booked flows to the Dashboard.
- **Dashboard Reports → Trading** shows Avg yearly ROI (with avg yearly CAGR)
  beside Avg monthly ROI; **→ Investments** shows Profit booked at the bottom
  of the page, table above chart.

## Storage

All data lives in one SQL database. By default that is a SQLite file,
`data/lakshya.db` (set `LAKSHYA_DATA_DIR` to move the folder). Tables:
`owners`, `meta`, `trades`, `excluded`, `capital`, `benchmarks`, `portfolio`,
each keyed by owner. Writes are transactional; a save replaces that owner's
rows atomically.

**Backup:** copy `data/lakshya.db` (plus `lakshya.db-wal` if present), or for a
consistent copy while the app is running:
`sqlite3 data/lakshya.db ".backup /home/ubuntu/lakshya-backup.db"`
(`sudo apt install sqlite3` once). A Lightsail snapshot also covers it.

**MariaDB / MySQL instead of SQLite:** create an empty database, then set
`LAKSHYA_DB_URL=mysql+pymysql://user:password@host/lakshya` in the service
environment and `pip install pymysql`. Tables are created on first start. No
code change.

**Upgrading from the earlier CSV version:** on first start the app imports
`data/<owner>/*.csv` and `data/users.json` into the database automatically and
renames the old folders to `<owner>.imported`. Delete those once you have
checked the dashboards.

**Removing an owner:** `sqlite3 data/lakshya.db "DELETE FROM owners WHERE slug='name'"`
plus the same `DELETE FROM <table> WHERE owner='name'` for the data tables, or
ask for a Remove button if you need it often.

## Importing a workbook with one tab per year

Upload the whole workbook on Trading Book. Tabs that look like trade logs are
pre-selected; untick pivot or summary tabs. Then choose how to import:
**Replace only the months covered by the file** (default once data exists:
existing rows for the months present in the file are removed and the file's
rows added; other months are untouched, so a corrected 2024 tab replaces only
2024), **Add to existing** (keeps everything, skips exact duplicates), or
**Replace ALL** (deletes every trade for this owner first). Each row remembers its tab in
`source_sheet`. Investment Book works the same way for holdings.

Large workbooks: only the file bytes are kept in memory; tab detection reads
header rows, and import streams one tab at a time, dropping the tens of
thousands of formatted-but-empty rows that broker exports carry before any
table is built (calamine engine; openpyxl fallback). Peak memory for a 9-tab
export is a few MB, so the $5 (512 MB) VM copes. While the server is working
the page fades and a spinner shows; that is normal.

If the service ever dies on upload, check for an out-of-memory kill with
`sudo dmesg | grep -i "out of memory"` and `journalctl -u lakshya -n 50`; the
fix is the larger $7 plan (1 GB).

Monthly capital can be uploaded under *2. Monthly capital*: any sheet with a
Month (or "Row Labels") column and a Capital (or "Average of Capital") column;
Grand Total rows are ignored. A `Capital` column in the trade rows is also used.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## What's new in v3.1
- **Sector editable everywhere** — Trading Book grids now carry a Sector column (prefilled from Stocks
  Management, editable, saved with the trades); in the Investment Book, Sector can be changed in All
  entries, Remaining holdings (written back to the lot) and Open positions (applies to every entry of
  that stock).
- **Equity Intraday** manual trades set the Sale date automatically to the Buy date.
- Investment Book: **Entries saved now sits above Open positions**; All entries has a **stock filter**;
  every book table is **sorted by stock** with a **Grand Total** underneath (Trades saved stays sorted
  by latest Buy date).
- Dashboard Reports: tables are plain again (no header filters) and the Asset class table shows all
  rows without a scroll bar.
- Home: long-term figures = what the Dashboard shows (remaining holdings); no table filters; per-user
  **asset-class pie** and a **marketcap pie** whose slices click through to the stocks in that cap;
  the admin's Family dashboards get the same two pies family-wide.
- Navigation: Benchmarks sits right after Home, and the sidebar is split into
  Overview / Books / Reports / Settings sections.

## Deploy

### Option A — Streamlit Community Cloud (free; data does not persist between redeploys)

1. Push this folder to a **private** GitHub repository (the `.gitignore` already
   excludes `*.xlsx` / `*.csv`, so trade data never lands in the repo).
2. Go to share.streamlit.io, sign in with GitHub, **New app**, pick the repo,
   branch and `app.py`, then **Deploy**.
3. In the app's **Settings → Sharing**, keep it private and add the email
   addresses allowed to view it. Free accounts get one private app.

You get a `https://<name>.streamlit.app` URL. Free apps sleep after a period of
inactivity and take ~30–60 s to wake on the next visit.

### Option B — AWS Lightsail VM ($5–7/month, fixed price; recommended for multi-owner data)

Everything is done in the AWS Console; no command-line tools on your laptop.

1. **Account.** Sign in at console.aws.amazon.com (create an account if needed;
   if offered a Free vs Paid plan, Paid avoids the account closing after six
   months — the sign-up credits apply either way). Turn on MFA for the root
   user, then under **Billing → Budgets** create a $10/month alert.
2. **Create the instance.** Search "Lightsail" → **Create instance** →
   Region *Mumbai (ap-south-1)* → Platform *Linux/Unix* → Blueprint *OS only →
   Ubuntu 24.04 LTS* → Network type *Dual-stack* → plan *$5 (512 MB)* or
   *$7 (1 GB)* → name it `lakshya` → **Create instance**.
3. **Static IP.** Instance → **Networking** tab → **Create static IP** →
   attach to `lakshya`. (Free while attached to a running instance.)
4. **Firewall.** Same tab, **IPv4 Firewall → Add rule**: *Custom TCP 8501* for
   the plain-HTTP setup, or *HTTP 80* and *HTTPS 443* if you will use a domain.
   Optionally restrict the existing SSH rule to your own IP.
5. **Get the code onto the VM**, either way:
   - *GitHub (recommended):* create a free account, a public repository named
     `lakshya`, and upload this folder's contents through the browser
     ("uploading an existing file", drag the folders in). No git commands needed.
     Folders starting with a dot (`.streamlit`) are hidden on Windows and are
     often skipped by drag-and-drop; the setup script restores the theme config
     from `deploy/streamlit-config.toml` if it is missing.
     For a private repo run `gh auth login` on the server before step 6.
   - *No GitHub:* download the Lightsail default SSH key (Account → SSH keys)
     and copy the zip from your laptop:
     `scp -i LightsailDefaultKey-ap-south-1.pem lakshya.zip ubuntu@<static-ip>:~`
6. **Install.** Instance → **Connect using SSH** (browser terminal) and run
   one of these, with your GitHub username and a password of your choice:

   ```bash
   # from GitHub
   curl -fsSL https://raw.githubusercontent.com/<user>/lakshya/main/deploy/setup-lightsail.sh -o setup.sh
   REPO_URL=https://github.com/<user>/lakshya.git APP_PASSWORD='choose-a-strong-password' bash setup.sh

   # from the zip you copied with scp
   unzip -o lakshya.zip && ZIP_PATH=~/lakshya.zip APP_PASSWORD='choose-a-strong-password' bash lakshya/deploy/setup-lightsail.sh
   ```

   The script adds swap, installs Python, clones the repo, creates a systemd
   service that survives reboots, and prints the URL: `http://<static-ip>:8501`.
7. **Optional HTTPS with a free hostname.** Create an account at duckdns.org,
   add a subdomain (e.g. `lakshya`) and set its IP to your static IP. Then
   re-run the script with `DOMAIN=lakshya.duckdns.org REPO_URL=... bash setup.sh`.
   It installs Caddy, which obtains and renews the certificate itself.
   Your URL becomes `https://lakshya.duckdns.org`.

**Updating later:** push (or re-upload) to GitHub, or `scp` a new zip, then SSH
in and re-run the same command; the database under `data/` is kept. **Logs:**
`journalctl -u lakshya -f`. **Restart:** `sudo systemctl restart lakshya`.

### Option C — Google Cloud Run (pay per use, scales to zero)

```bash
gcloud run deploy lakshya --source . --region asia-south1 --allow-unauthenticated
```

Then put Identity-Aware Proxy or Cloud Run's built-in authentication in front
of it, or drop `--allow-unauthenticated` and grant `roles/run.invoker` to the
people who should see it. Low-traffic use typically stays inside Cloud Run's
free tier; confirm current pricing on cloud.google.com before relying on that.

### Any Docker host

```bash
docker build -t lakshya . && docker run -p 8080:8080 lakshya
```

## Project layout

```
app.py                      router (st.navigation), owner selector, password gate
screens/home.py             status per owner, owner management
screens/trading_input.py    Trading Book: trades (upload / form), monthly capital, benchmarks
screens/portfolio_input.py  Investment Book: long-term holdings (upload / form)
screens/benchmarks.py       Benchmarks: shared monthly index returns (grid / upload / reset)
screens/reports.py          Dashboard Reports: Trading and Investments tabs
core/parse.py               header matching, type coercion, derived trade columns, charge detection, templates
core/strategies.py          strategy catalogue: definitions, bias, strike requirement
core/portfolio.py           portfolio parsing, holdings, sector allocation
core/benchmarks.py          monthly benchmark store, FY/CY period labels, comparison tables
core/seed/benchmarks_monthly.csv  built-in monthly returns Apr-2022 → Oct-2026
core/metrics.py             monthly summary, KPIs, capital/brokerage pivots, Excel export
core/store.py               per-owner persistence (SQLAlchemy; SQLite default, MariaDB optional)
core/state.py               Streamlit-side cache and write-through
core/formatting.py          Indian number formatting (37,00,000)
tests/test_core.py          unit tests (pytest -q)
deploy/setup-lightsail.sh   one-shot VM setup (Lightsail or any Ubuntu VM)
deploy/streamlit-config.toml copy of the theme config, restored by the setup script
Dockerfile                  for Cloud Run or any container host
.streamlit/config.toml      theme and upload limit
```

## Renaming

Change `APP_NAME` in `core/__init__.py`; every screen reads it from there.

## Data handling

Uploaded files are parsed in memory and only the cleaned rows are saved, into
the database described under Storage. Nothing is sent anywhere other than the
host you deploy to. On Streamlit Community Cloud and Cloud Run the disk is not
persistent, so a SQLite file disappears on redeploy; there, point
`LAKSHYA_DB_URL` at a managed database or use the Lightsail VM.
