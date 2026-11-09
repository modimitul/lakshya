# Lakshya

Trading and long-term-investment dashboards for up to any number of portfolio
owners, built from Excel uploads or simple entry forms. Python + Streamlit.

**Screens**

| Screen | What it does |
|---|---|
| Home | Status card per owner, owner names, how the numbers are calculated |
| Trading Book | Trades by upload or an *Add trade* form; monthly capital; annual ROI vs benchmarks (Nifty, Bank Nifty, NASDAQ, …) |
| Investment Book | Holdings by upload or an *Add entry* form: month, sector, stock, qty, buy, gift |
| Dashboards → Trading | KPIs, monthly table (capital, net profit, brokerage, ROI, win rate), capital and brokerage pivots with Grand Total, annual ROI vs benchmarks, breakdown by stock/strategy, trade log, Excel download |
| Dashboards → Investments | Year / sector / month filters; asset-class overview (Equity, ETF, Equity MF, Debt) with a sub-tab per class: holdings by stock with % Investment, sector allocation, gifts; Excel download |

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
| Monthly ROI | Net Profit ÷ Average of Capital × 100. Grand Total and yearly `Z ROI%` = sum of monthly ROI. |
| Benchmarks (Nifty ROI%, …) | Entered per year by the user or uploaded; not derivable from a trade log. Grand Total = sum of years. |
| % Investment | Stock cost ÷ total cost of the holdings currently shown × 100 (inside a class tab, the class total). |
| Asset class | From the SECTORS label, then the stock name: ETF/BEES → ETF; MF/MUTUAL/FUND → Equity MF; DEBT/BOND/SGB/GILT/LIQUID/FD/NCD → Debt; otherwise Equity. Adjust per owner under *Asset class rules* on the Investments tab. |

Rows whose period is not a calendar month (e.g. `YEAR 2026`) are shown under
"Excluded rows" and left out of monthly totals. Formatted-but-empty Excel rows,
`#NUM!` / `#DIV/0!` cells, text months like `Jul-23` and Indian-formatted numbers
like `1,08,959` are all handled.

## Sign-in and owners

Set `APP_PASSWORD` in the environment (the Lightsail setup script passes it into
the service) and the app shows one sign-in screen: a typed **Username** and the
single shared **Password**. A new username creates a new portfolio owner; an
existing one opens theirs. The sidebar shows who is signed in, lets you switch
owner, and has *Rename or add owner*. There are no per-user passwords: anyone
with the shared password can view every owner's data. If you need strict
separation, ask for per-user passwords; it is a small change.

Without `APP_PASSWORD` (for example when running locally) there is no sign-in
screen and a single owner called "Owner" is used.

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
pre-selected; untick pivot or summary tabs. Choose **Replace** (first load) or
**Add to existing** (later years or corrections); exact duplicate trades are
skipped, so re-importing a tab is safe. Each row remembers its tab in
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
screens/reports.py          Dashboards: Trading and Investments tabs
core/parse.py               header matching, type coercion, derived trade columns, templates
core/portfolio.py           portfolio parsing, holdings, sector allocation
core/benchmarks.py          annual ROI table, fill Z ROI% from trades, grand total
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
