import os

# AgGrid (custom component) cannot render in AppTest; excel_table falls back to st.dataframe.
os.environ.setdefault("LAKSHYA_PLAIN_TABLES", "1")
