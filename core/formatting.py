"""Number formatting helpers (Indian digit grouping)."""

from __future__ import annotations

import math
import re

# Excel number format that groups digits the Indian way (12,34,56,789).
EXCEL_INR_FORMAT = r"[>=10000000]##\,##\,##\,##0;[>=100000]##\,##\,##0;##,##0"


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def inr(value, decimals: int = 0, prefix: str = "") -> str:
    """Format a number with Indian grouping: 3700000 -> '37,00,000'.

    Returns an em dash for missing values so tables stay aligned.
    """
    if _is_missing(value):
        return "—"
    sign = "-" if float(value) < 0 else ""
    # Round half away from zero (like Excel), not Python's banker's rounding.
    scale = 10 ** decimals
    value = math.floor(abs(float(value)) * scale + 0.5) / scale
    whole = int(value)
    frac = f"{value - whole:.{decimals}f}"[1:] if decimals else ""
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        digits = f"{head},{tail}"
    return f"{sign}{prefix}{digits}{frac}"


def pct(value, decimals: int = 2) -> str:
    """Format a percentage value already expressed in percent units (2.25 -> '2.25')."""
    if _is_missing(value):
        return "—"
    return f"{float(value):.{decimals}f}"
