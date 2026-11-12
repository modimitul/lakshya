"""Stocks: one shared list of instruments, used as the Stock dropdown when adding trades manually."""

import pandas as pd
import streamlit as st

from core import state, store

SHARED = "_shared"

st.title("Stocks")
st.caption("One list for all owners. These names appear as the **Stock dropdown** when adding a trade "
           "manually in the Trading Book. Add rows with the ➕ at the bottom of the table, edit any cell, "
           "tick 🗑 to delete a row — then press **Save list**. A new name typed while adding a trade is "
           "also added here automatically.")


saved = store.load_frame(SHARED, "stocks")
if saved is None or saved.empty or "stock" not in saved.columns:
    saved = pd.DataFrame(columns=["stock", "note"])
existing = saved["stock"].astype(str).str.strip().str.upper().tolist()
grid = pd.DataFrame({
    "Delete": pd.Series([False] * len(saved), dtype=bool),
    "Stock": pd.Series(existing, dtype="string"),
    "Note": pd.Series(saved["note"].fillna("").astype(str).tolist() if "note" in saved.columns
                      else [""] * len(saved), dtype="string"),
})

edited = st.data_editor(
    grid, hide_index=True, width="stretch", num_rows="dynamic",
    height=min(len(grid) + 2, 18) * 35 + 3,
    key=f"stocks_editor_{state.version('stocks_version')}",
    column_config={
        "Delete": st.column_config.CheckboxColumn("🗑", help="Tick rows to delete, then press Save list"),
        "Stock": st.column_config.TextColumn("Stock / instrument", help="e.g. NIFTY, BANKNIFTY, TCS", required=False),
        "Note": st.column_config.TextColumn("Note (optional)", help="Anything useful — lot size, segment …"),
    },
)

c1, c2 = st.columns([1, 3])
if c1.button("Save list", type="primary"):
    keep = edited[~edited["Delete"].fillna(False).astype(bool)]
    names = keep["Stock"].fillna("").astype(str).str.strip().str.upper()
    notes = keep["Note"].fillna("").astype(str).str.strip()
    rows, seen = [], set()
    for name, note in zip(names, notes):
        if name and name not in seen:
            seen.add(name)
            rows.append({"stock": name, "note": note})
    frame = pd.DataFrame(rows) if rows else None
    store.save_frame(SHARED, "stocks", frame)
    state.bump("stocks_version")
    removed = len(edited) - len(rows)
    st.success(f"Saved {len(rows)} stock(s)" + (f" ({removed} removed or merged)" if removed > 0 else "") + ".")
    st.rerun()

if not existing:
    st.info("The list is empty. Add your instruments above (one per row) and press **Save list** — "
            "the Trading Book's manual entry then offers them as a dropdown.")

st.page_link("screens/trading_input.py", label="Go to Trading Book", icon="📒")
