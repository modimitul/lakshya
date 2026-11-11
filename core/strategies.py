"""Trade types (option strategies and others) with definitions and market bias."""

from __future__ import annotations

import pandas as pd

CHARGE_TYPE = "Brokerages"
OTHER_TYPE = "Other"

# (name, definition, bias)
STRATEGIES: list[tuple[str, str, str]] = [
    ("Naked Call Sell", "SELL 1 CALL", "🐻 Bear"),
    ("Naked Put Sell", "SELL 1 PUT", "🐂 Bull"),
    ("Naked Call Buy", "BUY 1 CALL", "🐂 Bull"),
    ("Naked Put Buy", "BUY 1 PUT", "🐻 Bear"),
    ("Bull Call Spread", "BUY 1 ATM CALL & SELL 1 OTM CALL", "🐂 Mild Bull"),
    ("Bull Call Ratio", "BUY 1 ATM CALL & SELL 2 OTM CALL", "🐂 Mild Bull (limited upside)"),
    ("Bull Put Spread", "BUY 1 OTM PUT & SELL 1 ATM/ITM PUT", "🐂 Mild Bull"),
    ("Bear Put Ratio", "BUY 1 ATM PUT & SELL 2 OTM PUT", "🐻 Mild Bear"),
    ("Bear Call Spread", "BUY 1 OTM CALL & SELL 1 ATM/ITM CALL", "🐻 Mild Bear"),
    ("Bear Put Spread", "BUY 1 ATM/ITM PUT & SELL 1 OTM PUT", "🐻 Mild Bear"),
    ("Iron Condor", "SELL 1 NEAR OTM CALL & SELL 1 NEAR OTM PUT & BUY 1 FAR OTM CALL & BUY 1 FAR OTM PUT", "😐 Neutral"),
    ("Covered Call", "BUY 1 LOT SHARES & SELL 1 OTM CALL", "🐂 Mild Bull / Income"),
    ("Call Ratio Back Spread", "SELL 1 ITM CALL & BUY 2 OTM CALL", "🐂 Bull (benefits from big move up)"),
    ("Bear Call Ladder", "SELL 1 ITM CALL & BUY 1 ATM CALL & BUY 1 OTM CALL", "🐻 Bear / Volatile"),
    ("Put Ratio Back Spread", "SELL 1 ITM PUT & BUY 2 OTM PUT", "🐻 Bear (benefits from big move down)"),
    ("Long Straddle", "BUY 1 ATM CALL & BUY 1 ATM PUT", "📈📉 Volatile (either direction)"),
    ("Short Straddle", "SELL 1 ATM CALL & SELL 1 ATM PUT", "😐 Neutral / Range-bound"),
    ("Long & Short Straddle", "Straddle + Strangle combo", "—"),
    ("Calendar Spread", "BUY 1 ATM CALL (far expiry) & SELL 1 ATM CALL (near expiry), or the same with PUTs", "😐 Neutral (time decay play)"),
    ("Ratio Spreads", "BUY 1 ATM CALL & SELL 2 OTM CALL, or BUY 1 ATM PUT & SELL 2 OTM PUT", "😐 Mild directional + Neutral"),
    ("Iron Butterfly", "SELL 1 ATM CALL & SELL 1 ATM PUT; BUY 1 OTM CALL & BUY 1 OTM PUT", "😐 Neutral"),
    ("Short Iron Condor", "SELL inner strikes (near ATM) & BUY outer strikes (far OTM)", "😐 Neutral"),
    ("Long Strangle", "BUY 1 OTM CALL & BUY 1 OTM PUT", "📈📉 Volatile (either direction)"),
    ("Short Strangle", "SELL 1 OTM CALL & SELL 1 OTM PUT", "😐 Neutral / Range-bound"),
    ("Long Iron Butterfly", "BUY 1 ATM CALL & BUY 1 ATM PUT; SELL 1 OTM CALL & SELL 1 OTM PUT", "📈📉 Volatile"),
    ("Long Iron Condor", "BUY 1 OTM CALL & BUY 1 OTM PUT; SELL 1 NEAR ATM CALL & SELL 1 NEAR ATM PUT", "📈📉 Volatile"),
    ("Collar Strategy", "BUY EQUITY/FUTURE + BUY ITM PUT + SELL OTM CALL", "🐂 Mild Bull / Hedged"),
    ("Protective PUT/Synthetic Call", "BUY EQUITY + BUY ITM PUT", "🐂 Bull / Downside Protected"),
    ("FUTURE Long", "BUY FUTURE", "🐂 Bull"),
    ("FUTURE Short", "SELL FUTURE", "🐻 Bear"),
    ("Debt", "", ""),
    ("Equity", "", ""),
    ("Long Unwinding", "Longs selling their accumulated positions: holders who expected a rise now sell.", "🐻 Bear"),
    ("Short Build Up", "Price falls + open interest rises = fresh shorts being added.", "🐻 Bear"),
    ("Short Covering", "Shorts buying back to close positions (buying to cover).", "🐂 Bull"),
    ("Long Build Up", "Price rises + open interest rises = fresh longs being added.", "🐂 Bull"),
    (CHARGE_TYPE, "Brokerage, DP, AMC, pledge or other charges: a cost entry, not a trade.", ""),
]

# Types where a strike price does not apply (everything else is an option strategy).
NON_OPTION_TYPES = {
    "FUTURE Long", "FUTURE Short", "Debt", "Equity",
    "Long Unwinding", "Short Build Up", "Short Covering", "Long Build Up",
    CHARGE_TYPE, OTHER_TYPE,
}

_BY_NAME = {name: (definition, bias) for name, definition, bias in STRATEGIES}
_BY_KEY = {name.lower(): name for name in _BY_NAME}


def strategy_names() -> list[str]:
    return [name for name, _, _ in STRATEGIES]


def definition(name: str) -> str:
    return _BY_NAME.get(canonical(name), ("", ""))[0]


def bias(name: str) -> str:
    return _BY_NAME.get(canonical(name), ("", ""))[1]


def canonical(name) -> str:
    """Match case-insensitively so 'naked put sell' from a file maps to the catalogue entry."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    return _BY_KEY.get(str(name).strip().lower(), str(name).strip())


def requires_strike(name: str) -> bool:
    return canonical(name) not in NON_OPTION_TYPES


# Opening side of each type: what the FIRST leg does. A "sell"-opening trade
# (short option, short future, fresh shorts) starts with a sale, so its Sale
# date is the mandatory one and the Buy date arrives when it is squared off;
# a "buy"-opening trade is the reverse.
_SIDE_OVERRIDES = {
    "Long Unwinding": "sell",    # holders selling out
    "Short Build Up": "sell",    # fresh shorts
    "Short Covering": "buy",     # buying back to close
    "Long Build Up": "buy",      # fresh longs
}


def opening_side(name) -> str:
    """'sell' when the strategy opens with a sale, else 'buy'."""
    canon = canonical(name)
    if canon in _SIDE_OVERRIDES:
        return _SIDE_OVERRIDES[canon]
    first_leg = _BY_NAME.get(canon, ("", ""))[0].strip().upper()
    if first_leg.startswith("SELL"):
        return "sell"
    if first_leg.startswith("BUY"):
        return "buy"
    n = canon.upper()
    return "sell" if ("SELL" in n or "SHORT" in n) else "buy"


def strategies_frame() -> pd.DataFrame:
    return pd.DataFrame(STRATEGIES, columns=["Strategy", "Definition", "Bull / Bear / Neutral"])
