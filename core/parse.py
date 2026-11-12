"""Read a trade log (xlsx / csv upload, or manual entry) into a canonical DataFrame.

Canonical columns (all optional unless noted):
    buy_date, month, stock, strike, type, qty, buy, cost_value, sale_date, sell,
    sale_value, pl, brokerage, gross_profit, margin, lot, inv_amount, roi, capital

Only `gross_profit` (or the columns it can be derived from) and a date to group
by (`month` or `buy_date`) are required to produce the monthly report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import IO

import pandas as pd

# canonical name -> accepted header spellings, compared after normalise_header()
COLUMN_ALIASES: dict[str, list[str]] = {
    "buy_date": ["buy date", "entry date", "open date", "trade date", "date"],
    "month": ["month", "expiry month", "period"],
    "stock": ["stock", "symbol", "scrip", "instrument", "underlying"],
    "strike": ["strike price", "strike"],
    "type": ["type", "strategy", "trade type"],
    "qty": ["qty", "quantity"],
    "buy": ["buy", "buy price", "entry price", "buy avg"],
    "cost_value": ["cost value", "buy value"],
    "sale_date": ["sale date", "sell date", "exit date", "close date"],
    "sell": ["sell", "sell price", "exit price", "sell avg"],
    "sale_value": ["sale value", "sell value"],
    "pl": ["profit /loss", "profit/loss", "profit / loss", "p&l", "pnl", "p/l", "profit"],
    "brokerage": ["brokerage & other charges", "brokerage", "charges", "brokerage and other charges"],
    "gross_profit": ["gross profit", "net p&l", "realised p&l", "realized p&l", "net profit"],
    "margin": ["margin", "margin per lot"],
    "lot": ["lot", "lots"],
    "inv_amount": ["inv amount", "investment", "capital deployed", "margin used"],
    "roi": ["roi", "roi %", "return %"],
    "capital": ["capital", "total capital", "account capital"],
}

NUMERIC_COLUMNS = [
    "strike", "qty", "buy", "cost_value", "sell", "sale_value", "pl",
    "brokerage", "gross_profit", "margin", "lot", "inv_amount", "roi", "capital",
]
DATE_COLUMNS = ["buy_date", "month", "sale_date"]

# Columns shown on the manual-entry grid: canonical -> label the user sees.
MANUAL_COLUMNS: dict[str, str] = {
    "buy_date": "Buy Date",
    "stock": "Stock",
    "strike": "Strike Price",
    "type": "Type",
    "qty": "Qty",
    "buy": "Buy",
    "sale_date": "Sale Date",
    "sell": "Sell",
    "brokerage": "Brokerage & Other Charges",
    "margin": "Margin",
    "lot": "Lot",
}

from .strategies import CHARGE_TYPE, canonical as canonical_type, strategy_names  # noqa: E402

COMMON_TRADE_TYPES = strategy_names()

EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xls")

# Strike-price text that marks a charge entry rather than a trade (case-insensitive).
CHARGE_PATTERN = re.compile(r"BROKERAGE|CHARGE|FEE|\bTAX\b|\bSTT\b|\bGST\b|INTEREST|PENALTY|\bDP\b|\bAMC\b|PLEDGE")


@dataclass
class ParseResult:
    trades: pd.DataFrame
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)  # original header -> canonical
    excluded: pd.DataFrame = field(default_factory=pd.DataFrame)  # rows left out of monthly totals

    @property
    def ok(self) -> bool:
        return not self.errors and not self.trades.empty


def normalise_header(name) -> str:
    """Lower-case, collapse whitespace/newlines, strip trailing punctuation."""
    text = re.sub(r"\s+", " ", str(name)).strip().lower()
    return text.rstrip(":")


def coerce_numeric(series: pd.Series) -> pd.Series:
    """to_numeric that also accepts Indian-formatted text such as '1,08,959' or '₹ 2,500'."""
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        series = series.astype("string").str.replace(r"[₹,\s]", "", regex=True).replace("", pd.NA)
    return pd.to_numeric(series, errors="coerce")


def map_columns(columns, aliases: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Return {original header: canonical name} for every header we recognise."""
    aliases = aliases or COLUMN_ALIASES
    lookup = {alias: canon for canon, aliases_ in aliases.items() for alias in aliases_}
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for col in columns:
        canon = lookup.get(normalise_header(col))
        if canon and canon not in taken:  # first match wins; ignore duplicate headers
            mapping[col] = canon
            taken.add(canon)
    return mapping


def excel_engine() -> str:
    """calamine (fast, low memory, reads .xls too) when installed, else openpyxl."""
    try:
        import python_calamine  # noqa: F401
        return "calamine"
    except ImportError:
        return "openpyxl"


def _blank_cell(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        t = v.strip()
        return not t or t.startswith("#")          # '' or Excel error text such as #DIV/0!
    if isinstance(v, (int, float)):
        return v == 0                               # formulas on empty rows evaluate to 0
    return False


def _blank_row(row) -> bool:
    return all(_blank_cell(v) for v in row)


def _header_row_index(rows: list[list]) -> int:
    """First row with at least 3 text cells is the header; title rows above it are skipped."""
    for i, row in enumerate(rows[:20]):
        if sum(isinstance(v, str) and v.strip() != "" for v in row) >= 3:
            return i
    return 0


def _rows_to_frame(header: list, body: list[list]) -> pd.DataFrame:
    width = len(header)
    cols = [str(h).strip() if h is not None and str(h).strip() else f"col_{i}" for i, h in enumerate(header)]
    def norm(v):
        return None if (isinstance(v, str) and not v.strip()) else v  # '' behaves like an empty cell

    fixed = [[norm(v) for v in r[:width]] + [None] * (width - len(r)) for r in body]
    return pd.DataFrame(fixed, columns=cols)


class Workbook:
    """Low-memory access to an uploaded workbook.

    Holds only the file bytes. Sheet names and header rows are read cheaply;
    `frame(sheet)` streams ONE sheet, dropping the formatted-but-empty rows that
    broker exports carry by the tens of thousands, before any DataFrame exists.
    """

    def __init__(self, data: bytes, filename: str):
        self.data = data
        self.filename = filename
        lower = filename.lower()
        self.is_csv = lower.endswith(".csv")
        if not self.is_csv and not lower.endswith(EXCEL_EXTENSIONS):
            raise ValueError(f"Unsupported file type: {filename}. Upload .xlsx, .xlsm, .xls or .csv.")
        self.engine = "csv" if self.is_csv else excel_engine()
        if self.engine == "openpyxl" and lower.endswith(".xls"):
            raise ValueError("Legacy .xls needs the 'python-calamine' package; or save the file as .xlsx.")
        self._book = None
        self.sheet_names: list[str] = self._load_sheet_names()

    # -- backends ---------------------------------------------------------
    def _open(self):
        if self._book is None:
            import io
            if self.engine == "calamine":
                from python_calamine import CalamineWorkbook
                self._book = CalamineWorkbook.from_filelike(io.BytesIO(self.data))
            elif self.engine == "openpyxl":
                import openpyxl
                self._book = openpyxl.load_workbook(io.BytesIO(self.data), read_only=True, data_only=True)
        return self._book

    def _load_sheet_names(self) -> list[str]:
        if self.is_csv:
            return ["CSV"]
        book = self._open()
        return list(book.sheet_names) if self.engine == "calamine" else list(book.sheetnames)

    def _iter_rows(self, sheet: str):
        book = self._open()
        if self.engine == "calamine":
            yield from book.get_sheet_by_name(sheet).iter_rows()
        else:
            yield from book[sheet].iter_rows(values_only=True)

    # -- public -----------------------------------------------------------
    def headers(self, sheet: str) -> list[str]:
        if self.is_csv:
            import io
            return list(pd.read_csv(io.BytesIO(self.data), nrows=0).columns)
        first_rows = []
        for row in self._iter_rows(sheet):
            first_rows.append(list(row))
            if len(first_rows) >= 20:
                break
        if not first_rows:
            return []
        idx = _header_row_index(first_rows)
        return [str(h).strip() for h in first_rows[idx] if h is not None and str(h).strip()]

    def frame(self, sheet: str) -> pd.DataFrame:
        """One sheet as a DataFrame with blank rows already removed."""
        if self.is_csv:
            import io
            df = pd.read_csv(io.BytesIO(self.data))
            return df.dropna(how="all")
        header, body, pending = None, [], []
        for row in self._iter_rows(sheet):
            row = list(row)
            if header is None:
                pending.append(row)
                if len(pending) >= 20 or (sum(isinstance(v, str) and v.strip() != "" for v in row) >= 3):
                    idx = _header_row_index(pending)
                    header = pending[idx]
                    body.extend(r for r in pending[idx + 1:] if not _blank_row(r))
                    pending = []
                continue
            if not _blank_row(row):
                body.append(row)
        if header is None:
            if not pending:
                return pd.DataFrame()
            header = pending[0]
            body = [r for r in pending[1:] if not _blank_row(r)]
        return _rows_to_frame(header, body)


def open_workbook(file: IO[bytes] | bytes, filename: str) -> Workbook:
    """Wrap uploaded bytes (or a file object) in a Workbook."""
    if isinstance(file, (bytes, bytearray)):
        data = bytes(file)
    else:
        try:
            file.seek(0)
        except AttributeError:
            pass
        data = file.read()
    return Workbook(data, filename)


def read_workbook(file: IO[bytes] | str, filename: str) -> dict[str, pd.DataFrame]:
    """Every sheet as {name: DataFrame} (blank rows dropped). Convenience for small files and tests."""
    if isinstance(file, str):
        with open(file, "rb") as fh:
            wb = open_workbook(fh, filename)
    else:
        wb = open_workbook(file, filename)
    return {name: wb.frame(name) for name in wb.sheet_names}


def looks_like_trade_header(headers: list[str]) -> bool:
    mapped = set(map_columns(headers).values())
    return "stock" in mapped and bool(mapped & {"gross_profit", "pl", "sell", "sale_value"})


def looks_like_trade_frame(frame: pd.DataFrame) -> bool:
    mapped = set(map_columns(frame.columns).values())
    return "stock" in mapped and bool(mapped & {"gross_profit", "pl", "sell", "sale_value"})


def list_sheets(file: IO[bytes] | str) -> list[str]:
    """Sheet names of an Excel upload (empty list for CSV)."""
    try:
        file.seek(0)
    except AttributeError:
        pass
    return pd.ExcelFile(file).sheet_names


def read_any(file: IO[bytes] | str, filename: str, sheet_name=0) -> pd.DataFrame:
    """Read csv/xlsx/xlsm/xls. Excel formulas come back as their cached values."""
    try:
        file.seek(0)
    except AttributeError:
        pass
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(file)
    if lower.endswith(".xls"):
        try:
            return pd.read_excel(file, sheet_name=sheet_name, engine="xlrd")
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ValueError("Legacy .xls needs the 'xlrd' package; save the file as .xlsx instead.") from exc
    if lower.endswith(EXCEL_EXTENSIONS[:2]):
        return pd.read_excel(file, sheet_name=sheet_name, engine="openpyxl")
    raise ValueError(f"Unsupported file type: {filename}. Upload .xlsx, .xlsm, .xls or .csv.")


MONTH_FORMATS = ("%b-%y", "%b-%Y", "%b %y", "%b %Y", "%B-%y", "%B %Y", "%m/%Y", "%m-%Y", "%Y-%m",
                 "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%y", "%d-%b-%Y")


def _to_month_start(series: pd.Series) -> pd.Series:
    """Coerce dates or labels like 'Apr-26' / 'Jul 2023' to the first day of that month."""
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce")
    else:
        text = series.astype("string").str.strip()
        parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
        # Explicit formats first: the generic parser reads 'Jul-23' as the 23rd of July.
        for fmt in MONTH_FORMATS:
            if parsed.isna().any():
                parsed = parsed.fillna(pd.to_datetime(text.where(parsed.isna()), format=fmt, errors="coerce"))
        if parsed.isna().any():  # real datetime objects mixed into an object column, etc.
            rest = series.where(parsed.isna())
            with_dt = rest[rest.map(lambda v: hasattr(v, "year"))]
            if not with_dt.empty:
                parsed = parsed.fillna(pd.to_datetime(with_dt, errors="coerce"))
    return parsed.dt.to_period("M").dt.to_timestamp()


def clean(raw: pd.DataFrame) -> ParseResult:
    """Map headers, coerce types, derive missing columns, drop blank rows."""
    mapping = map_columns(raw.columns)
    df = raw[list(mapping)].rename(columns=mapping).copy()
    result = ParseResult(trades=df, mapping=mapping)

    # Non-numeric strike text (BROKERAGE, FUTURE, EQUITY, MF ...) is kept as a label.
    if "strike" in df:
        as_text = df["strike"].astype("string").str.strip()
        numeric = coerce_numeric(df["strike"])
        df["strike_label"] = as_text.where(numeric.isna() & as_text.notna() & (as_text != ""), pd.NA).str.upper()

    # Excel error cells (#NUM!, #DIV/0!) arrive as text; coerce them to NaN.
    for col in NUMERIC_COLUMNS:
        if col in df:
            df[col] = coerce_numeric(df[col])
    for col in DATE_COLUMNS:
        if col in df and col != "month":  # keep raw Month so text periods can be reported
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "month" in df:
        df["period_label"] = df["month"].astype("string")

    # Drop the formatted-but-empty rows Excel sheets usually carry.
    # Formula columns often evaluate to 0 on empty rows, so judge blankness on
    # identity columns (stock / dates) rather than on numbers.
    before = len(df)
    identity = [c for c in ("stock", "buy_date", "sale_date") if c in df]
    key_cols = identity or [c for c in ("gross_profit", "pl", "sell") if c in df]
    if "stock" in df:
        df["stock"] = df["stock"].astype("string").str.strip().replace("", pd.NA)
    if key_cols:
        df = df.dropna(subset=key_cols, how="all")
    dropped = before - len(df)
    if dropped:
        result.notes.append(f"Skipped {dropped:,} blank rows.")

    # Derive values the same way the sheet's formulas do.
    if "cost_value" not in df and {"qty", "buy"} <= set(df):
        df["cost_value"] = df["qty"] * df["buy"]
    if "sale_value" not in df and {"qty", "sell"} <= set(df):
        df["sale_value"] = df["qty"] * df["sell"]
    if "pl" not in df and {"sale_value", "cost_value"} <= set(df):
        df["pl"] = df["sale_value"] - df["cost_value"]
    if "brokerage" in df:
        df["brokerage"] = df["brokerage"].fillna(0)
    if "gross_profit" not in df and "pl" in df:
        df["gross_profit"] = df["pl"] - df.get("brokerage", 0)
    if "inv_amount" not in df and {"margin", "lot"} <= set(df):
        df["inv_amount"] = df["margin"] * df["lot"]
    if "roi" not in df and {"pl", "inv_amount"} <= set(df):
        inv = df["inv_amount"].where(df["inv_amount"] > 0)
        df["roi"] = df["pl"] / inv * 100

    # Charge entries (brokerage, DP/AMC/pledge charges ...) are costs, not trades:
    # they count in Net Profit and Brokerage but not in trade counts or win rate.
    df["entry_kind"] = pd.Series(["trade"] * len(df), index=df.index, dtype="string")
    if len(df):
        label_hit = df["strike_label"].fillna("").str.contains(CHARGE_PATTERN, regex=True) if "strike_label" in df else pd.Series(False, index=df.index)
        zero = lambda c: (df[c].fillna(0) == 0) if c in df else pd.Series(True, index=df.index)
        structural = zero("pl") & zero("buy") & zero("sell") & (df["brokerage"].fillna(0) > 0 if "brokerage" in df else False)
        charge = label_hit | structural
        df.loc[charge, "entry_kind"] = "charge"
        if "type" not in df:
            df["type"] = pd.Series([pd.NA] * len(df), index=df.index, dtype="string")
        df["type"] = df["type"].astype("string").map(lambda v: canonical_type(v) if pd.notna(v) else v)
        df.loc[charge, "type"] = CHARGE_TYPE
        if "strike" in df:
            df.loc[charge, "strike"] = pd.NA
        n_charges = int(charge.sum())
        if n_charges:
            result.notes.append(f"{n_charges} rows are charge entries (brokerage, DP/AMC charges …): counted in net profit, not as trades.")

    # Month to group by: an explicit Month column wins; the buy date only fills
    # blanks. Text periods such as "YEAR 2026" are not months and are set aside.
    month = None
    if "month" in df:
        month = _to_month_start(df["month"])
        blank_month = df["month"].isna()
        if "buy_date" in df and blank_month.any():
            filled = _to_month_start(df["buy_date"]).where(blank_month)
            month = month.fillna(filled)
            n_filled = int((blank_month & month.notna()).sum())
            if n_filled:
                result.notes.append(f"{n_filled} rows had no Month; their Buy Date month was used.")
        if "sale_date" in df and month.isna().any():
            month = month.fillna(_to_month_start(df["sale_date"]).where(month.isna()))
    elif "buy_date" in df:
        month = _to_month_start(df["buy_date"])
        if "sale_date" in df and month.isna().any():
            # Sell-first trades may carry only a sale date; group those by it.
            month = month.fillna(_to_month_start(df["sale_date"]).where(month.isna()))
    elif "sale_date" in df:
        month = _to_month_start(df["sale_date"])

    if month is None:
        result.errors.append("No date column found. The file needs a 'Month' or 'Buy Date' column.")
    else:
        df["month"] = month
        excluded = df[df["month"].isna()].drop(columns=["month"])
        if len(excluded):
            total = float(pd.to_numeric(excluded.get("gross_profit"), errors="coerce").fillna(0).sum()) if "gross_profit" in excluded else 0.0
            result.warnings.append(
                f"{len(excluded)} rows have a period that is not a month (or no date) and are excluded "
                f"from the monthly totals; their profit sums to {total:,.0f}. See 'Excluded rows' below."
            )
            result.excluded = excluded.reset_index(drop=True)
            df = df[df["month"].notna()]
        df = df.drop(columns=["period_label"], errors="ignore")

    if "gross_profit" not in df:
        result.errors.append(
            "Could not find or derive profit. Provide 'Gross Profit', or 'Profit /Loss', "
            "or Qty + Buy + Sell so it can be calculated."
        )
    elif df["gross_profit"].isna().any():
        n = int(df["gross_profit"].isna().sum())
        result.warnings.append(f"{n} rows have no profit value and count as 0.")
        df["gross_profit"] = df["gross_profit"].fillna(0)

    if "stock" not in df:
        result.warnings.append("No 'Stock' column found; the per-stock breakdown will be unavailable.")

    if df.empty and not result.errors:
        result.errors.append("The file has headers but no trade rows.")

    result.trades = df.reset_index(drop=True)
    return result


def load_trades(file: IO[bytes], filename: str, sheet_name=0) -> ParseResult:
    """Read an uploaded file and return a ParseResult."""
    try:
        raw = read_any(file, filename, sheet_name)
    except ValueError as exc:
        return ParseResult(trades=pd.DataFrame(), errors=[str(exc)])
    except Exception as exc:  # corrupt / password-protected files
        return ParseResult(trades=pd.DataFrame(), errors=[f"Could not read the file: {exc}"])
    if raw.empty:
        return ParseResult(trades=pd.DataFrame(), errors=["The selected sheet is empty."])
    return clean(raw)


def empty_manual_frame(rows: int = 5) -> pd.DataFrame:
    """Typed, empty grid for the manual-entry editor."""
    frame = pd.DataFrame({label: [None] * rows for label in MANUAL_COLUMNS.values()})
    frame["Buy Date"] = pd.to_datetime(frame["Buy Date"])
    frame["Sale Date"] = pd.to_datetime(frame["Sale Date"])
    for canon, label in MANUAL_COLUMNS.items():
        if canon in NUMERIC_COLUMNS:
            frame[label] = pd.to_numeric(frame[label])
    frame["Stock"] = frame["Stock"].astype("string")
    frame["Type"] = frame["Type"].astype("string")
    return frame


def from_manual(grid: pd.DataFrame) -> ParseResult:
    """Convert the manual-entry grid (labelled columns) into a ParseResult."""
    label_to_canon = {label: canon for canon, label in MANUAL_COLUMNS.items()}
    raw = grid.rename(columns=label_to_canon)
    raw = raw.dropna(how="all")
    if raw.empty:
        return ParseResult(trades=pd.DataFrame(), errors=["Add at least one trade row."])
    # Re-label to the alias form clean() recognises.
    raw = raw.rename(columns={canon: COLUMN_ALIASES[canon][0] for canon in raw.columns if canon in COLUMN_ALIASES})
    return clean(raw)


def trade_from_form(**fields) -> ParseResult:
    """Build a one-row ParseResult from the Add-a-trade form.

    Accepts canonical names (buy_date, stock, type, strike, qty, buy, sale_date,
    sell, brokerage, margin, lot) and runs them through the same clean() path as
    an uploaded file, so derived columns match exactly.
    """
    raw = pd.DataFrame([{COLUMN_ALIASES[k][0]: v for k, v in fields.items() if k in COLUMN_ALIASES}])
    return clean(raw)


def template_bytes() -> bytes:
    """Blank Excel template with the headers the upload route expects (and one example row)."""
    import io

    headers = ["Buy Date", "Month", "STOCK", "Strike Price", "TYPE", "QTY", "Buy", "Sale Date", "Sell",
               "Brokerage & Other Charges", "Margin", "Lot"]
    example = ["2026-04-06", "2026-04-01", "TCS", 3400, "Naked Put Sell", 175, 52.13, "2026-04-24", 58.88, 48.5, 48000, 1]
    from .strategies import strategies_frame

    frame = pd.DataFrame([example], columns=headers)
    instructions = pd.DataFrame({
        "Column": headers,
        "Required": ["Yes", "Yes (or Buy Date)", "Yes", "Yes for option strategies; leave blank for Brokerages, Equity, Debt, Futures and OI types",
                     "Yes: a name from the Strategies sheet, or Brokerages for a charge entry", "Yes", "Yes", "Optional", "Yes",
                     "Optional (for Brokerages rows: the charge amount)", "Optional (used for ROI = P&L ÷ Margin × Lots)", "Optional"],
        "Notes": ["Date of entry", "First day of the month to report under", "Underlying / scrip, e.g. TCS", "Numeric strike",
                  "Strategy name", "Quantity", "Buy price", "Date of exit", "Sell price",
                  "Brokerage & other charges", "Margin per lot", "Number of lots"],
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Trades")
        instructions.to_excel(writer, index=False, sheet_name="Instructions")
        strategies_frame().to_excel(writer, index=False, sheet_name="Strategies")
        for name, widths in (("Trades", None), ("Instructions", [28, 60, 40]), ("Strategies", [30, 90, 36])):
            ws = writer.sheets[name]
            cols = list(frame.columns) if name == "Trades" else (list(instructions.columns) if name == "Instructions" else ["a", "b", "c"])
            for idx, col in enumerate(cols, start=1):
                ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = (widths[idx - 1] if widths else max(12, len(str(col)) + 2))
    return buffer.getvalue()


# ------------------------------------------------------- multi-sheet import --
TRADE_KEY_COLUMNS = ["buy_date", "month", "stock", "type", "strike", "qty", "buy", "sell", "gross_profit"]


def sheet_headers(file: IO[bytes], filename: str, sheet_name) -> list[str]:
    """Header row of one sheet without reading the data."""
    try:
        file.seek(0)
    except AttributeError:
        pass
    if filename.lower().endswith(".csv"):
        return list(pd.read_csv(file, nrows=0).columns)
    return list(pd.read_excel(file, sheet_name=sheet_name, nrows=0).columns)


def looks_like_trade_sheet(file: IO[bytes], filename: str, sheet_name) -> bool:
    """True when the sheet's headers map to a stock column and some profit/price column."""
    try:
        mapped = set(map_columns(sheet_headers(file, filename, sheet_name)).values())
    except Exception:
        return False
    return "stock" in mapped and bool(mapped & {"gross_profit", "pl", "sell", "sale_value"})


def dedupe_trades(trades: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop exact duplicate trades (same date, stock, type, strike, qty, prices, profit)."""
    keys = [c for c in TRADE_KEY_COLUMNS if c in trades]
    before = len(trades)
    out = trades.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)
    return out, before - len(out)


def load_trades_frames(frames: dict[str, pd.DataFrame], sheets: list[str]) -> ParseResult:
    """Import several already-read sheets (e.g. one tab per year) into one ParseResult.

    Each sheet is cleaned independently; a `source_sheet` column records where
    each row came from. Sheets that fail are reported as warnings unless all fail.
    """
    parts, excluded, mapping = [], [], {}
    result = ParseResult(trades=pd.DataFrame())
    for sheet in sheets:
        label = f"Sheet '{sheet}'"
        raw = frames.get(str(sheet))
        if raw is None or raw.empty:
            result.warnings.append(f"{label}: empty or missing.")
            continue
        part = clean(raw)
        if part.errors:
            result.warnings.append(f"{label}: " + " ".join(part.errors))
            continue
        part.trades["source_sheet"] = str(sheet)
        parts.append(part.trades)
        if not part.excluded.empty:
            part.excluded["source_sheet"] = str(sheet)
            excluded.append(part.excluded)
        mapping.update(part.mapping)
        result.notes.append(f"{label}: {len(part.trades):,} trades" + (f", {len(part.excluded)} excluded" if len(part.excluded) else ""))
        for w in part.warnings:
            result.warnings.append(f"{label}: {w}")
    if not parts:
        result.errors.append("None of the selected sheets could be read as a trade log.")
        return result
    result.trades = pd.concat(parts, ignore_index=True)
    result.excluded = pd.concat(excluded, ignore_index=True) if excluded else pd.DataFrame()
    result.mapping = mapping
    return result


def load_trades_workbook(wb: Workbook, sheets: list[str]) -> ParseResult:
    """Import selected sheets one at a time (low memory); same output as load_trades_frames."""
    import gc

    parts, excluded, mapping = [], [], {}
    result = ParseResult(trades=pd.DataFrame())
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
        part = clean(raw)
        del raw
        if part.errors:
            result.warnings.append(f"{label}: " + " ".join(part.errors))
            continue
        part.trades["source_sheet"] = str(sheet)
        parts.append(part.trades)
        if not part.excluded.empty:
            part.excluded["source_sheet"] = str(sheet)
            excluded.append(part.excluded)
        mapping.update(part.mapping)
        result.notes.append(f"{label}: {len(part.trades):,} trades" + (f", {len(part.excluded)} excluded" if len(part.excluded) else ""))
        for w in part.warnings:
            result.warnings.append(f"{label}: {w}")
        gc.collect()
    if not parts:
        result.errors.append("None of the selected sheets could be read as a trade log.")
        return result
    result.trades = pd.concat(parts, ignore_index=True)
    result.excluded = pd.concat(excluded, ignore_index=True) if excluded else pd.DataFrame()
    result.mapping = mapping
    return result


def load_trades_multi(file: IO[bytes], filename: str, sheets: list) -> ParseResult:
    """File-based convenience wrapper around load_trades_frames (reads the workbook once)."""
    try:
        frames = read_workbook(file, filename)
    except Exception as exc:
        return ParseResult(trades=pd.DataFrame(), errors=[f"Could not read the file: {exc}"])
    return load_trades_frames(frames, [str(s) if not isinstance(s, int) else list(frames)[s] for s in sheets])


# ------------------------------------------------------------ capital sheet --
CAPITAL_ALIASES: dict[str, list[str]] = {
    "month": ["month", "row labels", "period", "date"],
    "capital": ["capital", "average of capital", "avg capital", "average capital", "capital deployed", "sum of capital"],
}


def load_capital_sheet(file: IO[bytes], filename: str, sheet_name=0) -> tuple[pd.DataFrame | None, list[str]]:
    """File-based wrapper around load_capital_frame."""
    try:
        raw = read_any(file, filename, sheet_name)
    except Exception as exc:
        return None, [f"Could not read the file: {exc}"]
    return load_capital_frame(raw)


def load_capital_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    """Read a Month / Capital table (the 'Average of Capital' pivot works as-is).

    Returns a frame with columns month (month start) and Capital, Grand Total rows dropped.
    """
    raw = raw.copy()
    mapping = map_columns(raw.columns, CAPITAL_ALIASES)
    if not {"month", "capital"} <= set(mapping.values()):
        # Pivot exports often have no header row: try the first two columns.
        if raw.shape[1] >= 2:
            raw = raw.iloc[:, :2]
            raw.columns = ["month", "capital"]
            mapping = {"month": "month", "capital": "capital"}
        else:
            return None, ["Need a Month (or Row Labels) column and a Capital (or Average of Capital) column."]
    df = raw[list(mapping)].rename(columns=mapping)
    df = df[~df["month"].astype(str).str.contains("total", case=False, na=False)]
    df["Capital"] = coerce_numeric(df["capital"])
    df["month"] = _to_month_start(df["month"])
    df = df.dropna(subset=["month", "Capital"])[["month", "Capital"]]
    if df.empty:
        return None, ["No rows with both a month and a capital figure were found."]
    df = df.groupby("month", as_index=False)["Capital"].mean().sort_values("month").reset_index(drop=True)
    df["Capital"] = df["Capital"].astype("Float64")
    return df, []


def replace_covered_months(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> tuple[pd.DataFrame, int, list]:
    """Drop existing rows whose month appears in `incoming`, then append `incoming`.

    Returns (merged, rows_removed, months_replaced). Months not present in the
    file are left untouched, so re-uploading a corrected year replaces only that year.
    """
    months = sorted(pd.to_datetime(incoming["month"]).dropna().unique()) if "month" in incoming else []
    if existing is None or existing.empty:
        return incoming.reset_index(drop=True), 0, months
    covered = existing["month"].isin(months)
    kept = existing[~covered]
    merged = pd.concat([kept, incoming], ignore_index=True)
    return merged, int(covered.sum()), months


# ----------------------------------------------------------- manual edits --
def cell_changed(old, new) -> bool:
    """True when an edited grid cell differs from the stored value (NaN/NaT-safe)."""
    def is_na(v):
        try:
            return v is None or bool(pd.isna(v))
        except (TypeError, ValueError):
            return False
    if is_na(old) and is_na(new):
        return False
    if is_na(old) != is_na(new):
        return True
    if hasattr(old, "year") or hasattr(new, "year"):
        try:
            return pd.Timestamp(old) != pd.Timestamp(new)
        except (TypeError, ValueError):
            return str(old) != str(new)
    try:
        return abs(float(old) - float(new)) > 1e-9
    except (TypeError, ValueError):
        return str(old) != str(new)


def apply_grid_edits(base: pd.DataFrame, order, edited: pd.DataFrame, columns: list[str]):
    """Copy edited values from a data_editor grid back onto base.loc[order].

    `edited` row i corresponds to base.loc[order[i]]. Returns (updated, changed index labels).
    """
    updated = base.copy()
    changed = []
    for pos, idx in enumerate(list(order)):
        row_changed = False
        for col in columns:
            if col not in edited.columns:
                continue
            new = edited.iloc[pos][col]
            old = base.at[idx, col] if col in base.columns else None
            if cell_changed(old, new):
                if col in base.columns and pd.api.types.is_datetime64_any_dtype(base[col]):
                    new = pd.NaT if new is None or pd.isna(new) else pd.Timestamp(new)
                try:
                    updated.at[idx, col] = new
                except (TypeError, ValueError):
                    # e.g. a decimal typed into an integer column: widen the column first
                    if col in updated.columns and pd.api.types.is_integer_dtype(updated[col]) and isinstance(new, (int, float)):
                        updated[col] = updated[col].astype("float64")
                    else:
                        updated[col] = updated[col].astype("object")
                    updated.at[idx, col] = new
                row_changed = True
        if row_changed:
            changed.append(idx)
    return updated, changed


def recompute_trades(df: pd.DataFrame, rows: list) -> pd.DataFrame:
    """Recalculate derived columns for the given rows after manual grid edits:
    cost/sale value, P&L, gross profit (P&L − brokerage), investment, ROI, month
    (from Buy date when blank) and charge classification."""
    import math

    from .strategies import CHARGE_TYPE, canonical as canonical_type

    out = df.copy()

    def num(col, idx):
        if col not in out.columns:
            return float("nan")
        try:
            v = out.at[idx, col]
            return float("nan") if pd.isna(v) else float(v)
        except (TypeError, ValueError):
            return float("nan")

    for idx in rows:
        qty, buy, sell = num("qty", idx), num("buy", idx), num("sell", idx)
        brokerage = num("brokerage", idx)
        brokerage = 0.0 if math.isnan(brokerage) else brokerage
        cost = qty * buy if not math.isnan(qty) and not math.isnan(buy) else float("nan")
        sale = qty * sell if not math.isnan(qty) and not math.isnan(sell) else float("nan")
        if "cost_value" in out.columns and not math.isnan(cost):
            out.at[idx, "cost_value"] = cost
        if "sale_value" in out.columns and not math.isnan(sale):
            out.at[idx, "sale_value"] = sale
        if math.isnan(sale) and math.isnan(cost):
            pl = float("nan")
        else:
            pl = (0.0 if math.isnan(sale) else sale) - (0.0 if math.isnan(cost) else cost)
        if "pl" in out.columns and not math.isnan(pl):
            out.at[idx, "pl"] = pl
        if "gross_profit" in out.columns:
            out.at[idx, "gross_profit"] = (0.0 if math.isnan(pl) else pl) - brokerage
        margin, lot = num("margin", idx), num("lot", idx)
        inv = margin * lot if not math.isnan(margin) and not math.isnan(lot) else float("nan")
        if "inv_amount" in out.columns and not math.isnan(inv):
            out.at[idx, "inv_amount"] = inv
        if "roi" in out.columns:
            out.at[idx, "roi"] = pl / inv * 100 if (not math.isnan(pl) and not math.isnan(inv) and inv > 0) else float("nan")
        if "type" in out.columns and pd.notna(out.at[idx, "type"]):
            out.at[idx, "type"] = canonical_type(out.at[idx, "type"])
        if "month" in out.columns and "buy_date" in out.columns:
            if pd.isna(out.at[idx, "month"]) and pd.notna(out.at[idx, "buy_date"]):
                out.at[idx, "month"] = pd.Timestamp(out.at[idx, "buy_date"]).to_period("M").to_timestamp()
        if "month" in out.columns and pd.notna(out.at[idx, "month"]):
            # an edited Month may be any day of the month; store its month start
            out.at[idx, "month"] = pd.Timestamp(out.at[idx, "month"]).to_period("M").to_timestamp()
        if "entry_kind" in out.columns:
            typ = str(out.at[idx, "type"]) if "type" in out.columns and pd.notna(out.at[idx, "type"]) else ""
            zero_trade = (math.isnan(pl) or pl == 0) and (math.isnan(buy) or buy == 0) and (math.isnan(sell) or sell == 0)
            out.at[idx, "entry_kind"] = "charge" if (typ == CHARGE_TYPE or (zero_trade and brokerage > 0)) else "trade"
    return out


def open_positions_mask(trades: pd.DataFrame) -> pd.Series:
    """True for trades still open: one leg has neither a price nor a date.

    Works for both directions — a long bought and not yet sold (Sell and Sale date
    blank) and a sold option not yet bought back (Buy and Buy date blank). A leg
    closed at price 0 counts as closed when its date is filled (e.g. expiry).
    Charge entries are never open positions.
    """
    if trades is None or trades.empty:
        return pd.Series(False, index=trades.index if trades is not None else [])

    def col_num(name):
        return pd.to_numeric(trades[name], errors="coerce") if name in trades.columns else pd.Series(float("nan"), index=trades.index)

    def col_date(name):
        return pd.to_datetime(trades[name], errors="coerce") if name in trades.columns else pd.Series(pd.NaT, index=trades.index)

    buy, sell = col_num("buy"), col_num("sell")
    buy_leg_open = (buy.isna() | (buy == 0)) & col_date("buy_date").isna()
    sell_leg_open = (sell.isna() | (sell == 0)) & col_date("sale_date").isna()
    is_trade = trades["entry_kind"].fillna("trade").eq("trade") if "entry_kind" in trades.columns else pd.Series(True, index=trades.index)
    # a row with BOTH legs fully blank is not a position at all; require one real leg
    has_any_leg = (buy.fillna(0) > 0) | (sell.fillna(0) > 0)
    return is_trade & has_any_leg & (buy_leg_open | sell_leg_open)
