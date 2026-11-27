"""Options Greeks — a plain-language guide, organised one Greek at a time."""

from __future__ import annotations

import streamlit as st

st.title("Options Greeks")
st.caption("The four numbers every option quote carries, in plain words — and how option **sellers** "
           "use them. Greeks change constantly with the market; the values on your broker's option "
           "chain are always the live ones.")

st.markdown("""
**What is an \"Option Greek\"?** In simple words: when you buy or sell an option, its price (the
*premium*) moves for several different reasons — the stock moving, time passing, the market getting
nervous or calm. The **Greeks** are just four numbers that tell you *how much* each of those reasons
moves your premium. Think of them as the dials on the option's dashboard.

| Greek | What it measures (layman's words) |
|---|---|
| **Delta (Δ)** | How much the premium moves per ₹1 move in the underlying stock/index |
| **Theta (Θ)** | Time decay — how much premium the option loses **per day** just by the calendar moving |
| **Vega (V)** | Sensitivity to IV (volatility) changes — how much premium moves when the market's fear/expectation changes |
| **Gamma (Γ)** | Rate of change of Delta — how fast Delta itself speeds up when the stock moves |
""")

st.divider()

# ------------------------------------------------------------------ Delta ----
st.header("Delta (Δ)")
st.markdown("""
**In plain words:** if the stock moves ₹1, Delta tells you how many paise the option premium moves.
A Delta of 0.20 means a ₹1 move in the stock moves the premium about ₹0.20. Calls have positive
Delta (0 to 1), puts negative (0 to −1).

**The handy shortcut:** Delta is also a rough *probability that the option expires in the money*.
A 0.15-Delta put has roughly a 15% chance of finishing in the money — which means about an **85%
chance it expires worthless**, exactly what a seller wants.

**Selling with Delta — sell options with Delta around 0.15 to 0.30:**

| Option | What the Delta is telling you |
|---|---|
| 0.15 Put | ≈ 85% chance it expires worthless |
| 0.20 Call | ≈ 80% chance you keep the premium |

**Higher Delta = more premium but more risk.** A 0.40-Delta option pays you more upfront, but it
sits closer to the stock price and gets breached far more often. The 0.15–0.30 band is the sweet
spot between earning something and sleeping at night.
""")

st.divider()

# ------------------------------------------------------------------ Theta ----
st.header("Theta (Θ) — time decay works in your favour")
st.markdown("""
**In plain words:** an option is like an ice cube — every day that passes, a little of it melts,
even if the stock goes nowhere. Theta is the melt rate: a Theta of −12 means the option loses about
₹12 of premium per day. When you have **sold** the option, that melting is money flowing to you.

**How sellers use it:**
- **Sell options with high Theta** — they decay faster as expiry approaches. Decay is not a straight
  line: it accelerates in the final 2–3 weeks and is steepest in the last few days.
- **Choose weekly options on Monday/Tuesday**, so you capture the whole week's melt, **or monthly
  options mid-cycle** (around 20–30 days to expiry), where decay is picking up but there is still
  enough premium worth collecting.
- Remember Theta only works if the move stays small — it pays you for *waiting*, not for being wrong
  on direction.
""")

st.divider()

# ------------------------------------------------------------------- Vega ----
st.header("Vega (V) — sell when IV is high")
st.markdown("""
**In plain words:** IV (implied volatility) is the market's fear gauge — how big a move traders
*expect*. Vega tells you how much the premium changes when IV moves by 1 point. When fear is high,
options are expensive; when fear cools off, they deflate — even with the stock standing still.

**How sellers use it:**
- **Check IV Rank or IV Percentile** on your platform: they show where today's IV sits inside its own
  1-year range (IV Rank 80% = near the top of its range).
- **If IV Rank > 60%, it's a great time to sell** — you are selling inflated premium, and you profit
  twice: once from time decay and once when IV falls back to normal ("IV crush", most visible right
  after results/events).
- Avoid *buying* options when IV Rank is high — you'd be paying the inflated price.
""")

st.divider()

# ------------------------------------------------------------------ Gamma ----
st.header("Gamma (Γ) — the accelerator on Delta")
st.markdown("""
**In plain words:** Delta is the speed of the premium; Gamma is its *acceleration*. A high Gamma
means a small stock move makes Delta itself jump, so the premium starts moving much faster than you
expected.

**Why sellers care:** Gamma is highest **at the money and near expiry**. That's why a sold option
that sat quietly for weeks can suddenly turn violent in the last days before expiry — a small move
flips its Delta from 0.2 to 0.6 in hours. Sellers call this **gamma risk**: either book the profit
and get out when most of the premium is earned, or keep positions small as expiry nears.
""")

st.divider()

# ------------------------------------------------------- summary + checklist ----
st.header("Summary rules for selling options using Greeks")
st.markdown("""
| Rule | Tip |
|---|---|
| 🎯 Sell Delta 0.15–0.30 | Gives good odds of profit (≈ 70–85% chance the option expires worthless) |
| ⏳ Sell high Theta | Maximise time decay — the melt is your income |
| 📈 Prefer high IV Rank | Get inflated premiums, plus a tailwind when IV cools off |
| 🛡️ Use spreads or stop-loss | Avoid blow-ups — one runaway month can undo many good ones |
""")

st.header("Ideal conditions for selling options")
st.markdown("""
| Condition | Why it's good |
|---|---|
| High Implied Volatility (IV) | Options are overpriced — sell them for a higher premium |
| OTM strikes with high Theta | You collect the decay without sitting on top of the stock price |
| Neutral to mildly bullish/bearish view | Perfect for strangles, credit spreads and similar — you win if the market does *nothing dramatic* |
| IV > HV (implied > historical volatility) | The market is paying for a bigger move than the stock actually makes — the premium is inflated versus reality |

**A few more that help:**

| Condition | Why it's good |
|---|---|
| Clear support/resistance to hide behind | Place the sold strike beyond a level the market respects — the move has to break the level *and* your strike |
| No big event before expiry | Results, RBI/Fed meetings and budgets spike IV and gap prices; sellers prefer quiet calendars (or exit before the event) |
| Liquid strikes (tight bid–ask, high OI) | You can enter and exit near fair price; wide spreads silently eat the premium you earned |
| Position sized so one breach can't hurt | Margin for a short option can balloon when the market turns; keep each position small enough that a 2–3× adverse move is survivable |

**Where this ties into Lakshya:** the Strategy Guide lists which strategies are sell-opening
(Naked Call/Put Sell, Short Strangle, Iron Condor…). When you log such trades in the Trading Book,
the dashboard's win rate shows you whether your Delta band is doing its job.
""")

st.caption("Educational notes, not investment advice — numbers like \"Delta 0.15 ≈ 85%\" are "
           "approximations that hold best near expiry and move with volatility.")
