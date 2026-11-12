"""Stocks Management: the shared instrument list behind the Trading Book's Stock dropdown.

Upload a file (Sector, Stock Name, Marketcap) or maintain the list by hand:
add rows, edit any cell, tick 🗑 to delete — then Save list.
"""

import io

import pandas as pd
import streamlit as st

from core import state, store
from core.parse import MARKETCAP_OPTIONS, Workbook, clean_stock_list, stocklist_template_bytes

SHARED = "_shared"

st.title("Stocks Management")
st.caption("One list for all owners. These names appear as the **Stock dropdown** when adding a trade "
           "manually in the Trading Book; a new name typed there is added here automatically.")

for _flash in st.session_state.pop("stocks_flash", []):
    st.success(_flash)

saved = store.load_frame(SHARED, "stocks")
if saved is None or saved.empty or "stock" not in saved.columns:
    saved = pd.DataFrame(columns=["stock", "sector", "marketcap", "note"])
for col in ("sector", "marketcap", "note"):
    if col not in saved.columns:
        saved[col] = ""

# ------------------------------------------------------------------ upload ----
with st.expander(f"Upload a stock list ({len(saved):,} saved)", expanded=saved.empty):
    st.caption("Excel or CSV with the columns **Sector**, **Stock Name**, **Marketcap** "
               "(Large cap / Mid cap / Small cap). Extra columns are ignored.")
    st.download_button("Download the template (.xlsx)", stocklist_template_bytes(),
                       file_name="stock-list-template.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upload_mode = st.radio("How to apply the file", ["Merge with the current list", "Replace the whole list"],
                           horizontal=True,
                           help="Merge: new names are added and existing names get the file's sector/marketcap. "
                                "Replace: the saved list becomes exactly the file.")
    uploaded = st.file_uploader("Stock list file", type=["xlsx", "xls", "csv"], key="stocks_upload")
    if uploaded is not None and st.button("Import stock list", type="primary"):
        try:
            if uploaded.name.lower().endswith(".csv"):
                raw = pd.read_csv(io.BytesIO(uploaded.getvalue()), dtype=str)
            else:
                wb = Workbook(uploaded.getvalue(), uploaded.name)
                raw = wb.frame(wb.sheet_names[0])
        except Exception as exc:  # noqa: BLE001 - show the reason, keep the app up
            st.error(f"Could not read the file: {exc}")
            raw = None
        if raw is not None:
            cleaned, errors, warns = clean_stock_list(raw)
            for e in errors:
                st.error(e)
            for w in warns:
                st.warning(w)
            if not errors and cleaned is not None:
                if upload_mode.startswith("Merge") and not saved.empty:
                    merged = saved.set_index("stock")
                    incoming = cleaned.set_index("stock")
                    for col in ("sector", "marketcap", "note"):
                        fresh = incoming[col].replace("", pd.NA).dropna()
                        merged.loc[merged.index.intersection(fresh.index), col] = fresh
                    new_rows = incoming[~incoming.index.isin(merged.index)]
                    combined = pd.concat([merged, new_rows]).reset_index()
                else:
                    combined = cleaned
                store.save_frame(SHARED, "stocks", combined)
                state.bump("stocks_version")
                st.session_state["stocks_flash"] = [
                    f"Imported {len(cleaned):,} stock(s) from {uploaded.name} — the list now has {len(combined):,}."]
                st.rerun()

# ---------------------------------------------------------------- edit grid ----
st.subheader("Saved list")
st.caption("Add rows with the ➕ at the bottom, edit any cell (modify), tick 🗑 to delete a row — "
           "then press **Save list**.")
grid = pd.DataFrame({
    "Delete": pd.Series([False] * len(saved), dtype=bool),
    "Stock": pd.Series(saved["stock"].astype(str).str.strip().str.upper().tolist(), dtype="string"),
    "Sector": pd.Series(saved["sector"].fillna("").astype(str).tolist(), dtype="string"),
    "Marketcap": pd.Series(saved["marketcap"].fillna("").astype(str).tolist(), dtype="string"),
    "Note": pd.Series(saved["note"].fillna("").astype(str).tolist(), dtype="string"),
})
edited = st.data_editor(
    grid, hide_index=True, width="stretch", num_rows="dynamic",
    height=min(len(grid) + 2, 18) * 35 + 3,
    key=f"stocks_editor_{state.version('stocks_version')}",
    column_config={
        "Delete": st.column_config.CheckboxColumn("🗑", help="Tick rows to delete, then press Save list"),
        "Stock": st.column_config.TextColumn("Stock Name", help="e.g. NIFTY, BANKNIFTY, TCS"),
        "Sector": st.column_config.TextColumn("Sector", help="e.g. IT, BANK, CHEMICALS"),
        "Marketcap": st.column_config.SelectboxColumn("Marketcap", options=MARKETCAP_OPTIONS,
                                                      help="Large cap / Mid cap / Small cap"),
        "Note": st.column_config.TextColumn("Note (optional)"),
    },
)

if st.button("Save list", type="primary"):
    keep = edited[~edited["Delete"].fillna(False).astype(bool)]
    rows, seen = [], set()
    for _, r in keep.iterrows():
        name = str(r.get("Stock") or "").strip().upper()
        if name and name not in seen:
            seen.add(name)
            rows.append({"stock": name,
                         "sector": str(r.get("Sector") or "").strip().upper(),
                         "marketcap": str(r.get("Marketcap") or "").strip(),
                         "note": str(r.get("Note") or "").strip()})
    frame = pd.DataFrame(rows) if rows else None
    store.save_frame(SHARED, "stocks", frame)
    state.bump("stocks_version")
    removed = len(edited) - len(rows)
    st.session_state["stocks_flash"] = [f"Saved {len(rows):,} stock(s)"
                                        + (f" ({removed} removed or merged)" if removed > 0 else "") + "."]
    st.rerun()

if saved.empty:
    st.info("The list is empty. Upload a file above or add rows by hand and press **Save list** — "
            "the Trading Book's manual entry then offers these names as a dropdown.")

st.page_link("screens/trading_input.py", label="Go to Trading Book", icon="📒")
