"""Benchmarks: monthly returns (%) of indices and ETFs, shared by all owners."""

import pandas as pd
import streamlit as st

from core import state
from core.benchmarks import (
    DEFAULT_COLUMNS,
    get_monthly,
    load_monthly_file,
    merge_monthly,
    normalise_monthly,
    save_monthly,
    seed_frame,
    template_bytes,
)

st.title("Benchmarks")
st.caption("Monthly returns in % for market indices and ETFs. Shared by every owner; used on the Dashboards "
           "to compare each owner's ROI against the market, by calendar or financial year.")

monthly = get_monthly()
span = f"{monthly['month'].min():%b-%y} to {monthly['month'].max():%b-%y}" if not monthly.empty else "no data"
st.write(f"**{len(monthly)} months** on file ({span}), **{len(monthly.columns) - 1} series**.")

tab_edit, tab_upload = st.tabs(["Edit in a grid", "Upload a sheet"])

with tab_upload:
    c1, c2 = st.columns([3, 1])
    with c2:
        st.download_button("Download blank template (.xlsx)", template_bytes(), "benchmarks_template.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with c1:
        upload = st.file_uploader("Month in the first column (dates or text like Apr-22); one column per index",
                                  type=["xlsx", "xlsm", "xls", "csv"], key="bench_month_upload")
    if upload is not None:
        wb = state.cached_workbook(upload, "bench_wb")
        if wb:
            sheet = wb.sheet_names[0]
            if len(wb.sheet_names) > 1:
                sheet = st.selectbox("Tab", wb.sheet_names, key="bench_sheet")
            incoming, errors = normalise_monthly(wb.frame(sheet))
            for e in errors:
                st.error(e)
            if incoming is not None:
                new_months = len(set(incoming["month"]) - set(monthly["month"]))
                st.caption(f"{len(incoming)} months in the sheet, {new_months} new; columns: {', '.join(c for c in incoming.columns if c != 'month')}.")
                st.dataframe(incoming.head(12), hide_index=True, width="stretch")
                how = st.radio("How to apply", ["Merge (sheet values overwrite matching months)", "Replace everything"],
                               horizontal=True, key="bench_how")
                if st.button("Apply", type="primary", key="bench_apply"):
                    result = incoming if how.startswith("Replace") else merge_monthly(monthly, incoming)
                    save_monthly(result)
                    state.bump("bench_grid_version")
                    st.success(f"Saved {len(result)} months.")
                    st.rerun()

with tab_edit:
    st.caption("Type or paste values; add rows with the + at the bottom. Month accepts any day in the month. "
               "Press **Save changes** when done.")
    grid = monthly.copy()
    for extra in st.session_state.get("bench_extra_cols", []):
        if extra not in grid:
            grid[extra] = pd.Series([pd.NA] * len(grid), dtype="Float64")
    grid.insert(0, "Month", grid["month"])
    grid = grid.drop(columns=["month"])
    value_cols = [c for c in grid.columns if c != "Month"]
    edited = st.data_editor(
        grid, hide_index=True, width="stretch", num_rows="dynamic",
        height=min(len(grid) + 2, 20) * 35 + 3,
        key=f"bench_grid_{state.version('bench_grid_version')}",
        column_config={"Month": st.column_config.DateColumn("Month", format="MMM YYYY", required=True),
                       **{c: st.column_config.NumberColumn(c, format="%.2f") for c in value_cols}},
    )
    b1, b2, b3 = st.columns([1, 1, 2])
    if b1.button("Save changes", type="primary", key="bench_save"):
        to_save = edited.rename(columns={"Month": "month"})
        try:
            save_monthly(to_save)
            state.bump("bench_grid_version")
            st.success("Saved.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    new_col = b2.text_input("Add a series", placeholder="e.g. MIDCAP 150", key="bench_new_col", label_visibility="collapsed")
    if b2.button("Add column", key="bench_add_col") and new_col.strip():
        if new_col.strip() in value_cols:
            st.warning("That series already exists.")
        else:
            # the column is saved once it has at least one value (empty columns are dropped on save)
            st.session_state["bench_extra_cols"] = st.session_state.get("bench_extra_cols", []) + [new_col.strip()]
            state.bump("bench_grid_version")
            st.rerun()
    with b3.popover("Reset to built-in data"):
        st.write(f"Replaces everything with the {len(seed_frame())} months shipped with the app.")
        if st.button("Yes, reset", key="bench_reset"):
            save_monthly(seed_frame())
            state.bump("bench_grid_version")
            st.rerun()

st.page_link("screens/reports.py", label="Go to Dashboards", icon="📊")
