"""Column tooltips and display formats for every table in the app.

Pure data - no Streamlit import - so `core` stays UI-agnostic. `app.py` turns these
into `st.column_config` entries, which render HELP as a hover tooltip on the column
header.

Tooltips say what the number *means* and how to read it, not just what it is. A column
whose interpretation is not obvious from its name is a column that needs a sentence.
"""
from __future__ import annotations

# ------------------------------------------------------------------ tooltips
HELP: dict[str, str] = {
    # ---------------- identity ----------------
    "Symbol": "NSE trading symbol. Click any row to open the full reasoning, the rule-by-rule "
              "score breakdown and the chart.",
    "Company": "Registered company name, from the NSE constituent list.",
    "Industry": "NSE industry classification. Breakouts cluster by sector — several names "
                "from one industry appearing together is itself a signal.",

    # ---------------- scoring ----------------
    "Score": "0–100: 100 × (points earned ÷ points available) across all scored factors, "
             "times the market-regime factor. Backtested meaning differs by tab. On the "
             "breakout tab it does rank outcomes (rank correlation +0.077 with the R "
             "multiple, positive in 10 of 10 calendar years, mean R rising 0.21→0.37 "
             "from the lowest to highest quintile). On the pre-breakout tab it ranks how "
             "soon a base will give way, NOT whether the trade pays. Always check R:R "
             "as well — a high score with poor geometry is still a poor trade.",
    "Grade": "Letter band for the score: A+ ≥85, A ≥75, B+ ≥65, B ≥55, C ≥45, D below 45.",
    "Risk score": "Deterioration severity, 0–100: the sum of points from every weighted "
                  "warning signal that fired, capped at 100. Higher = more damage evident.",
    "Severity": "Risk-score band: Watch (<25), Caution (25–44), High risk (45–64), "
                "Exit signal (≥65, or 7+ signals firing).",
    "Stage": "How far the deterioration has progressed. 'Early warning' = still above both "
             "the 20-EMA and 50-SMA, so the chart still looks healthy while distribution "
             "builds underneath — the cohort actually worth acting on. 'Turning' = lost the "
             "20-EMA. 'Breaking down' = below the 50-SMA, and the market has already noticed.",
    "Signals": "How many of the 19 deterioration signals fired. Two is the default minimum; "
               "three or more is a genuinely deteriorating chart.",
    "Key signals": "The four highest-weighted signals that fired, in order. Click the row for "
                   "all of them with the underlying numbers.",
    "Warnings": "Count of warning flags against this setup. A high score with warnings is "
                "worse than a slightly lower score with none — read them before entering.",
    "Status": "Fresh = broke out within the last 2 sessions and not extended (the tradeable "
              "cohort). Holding = older break, still above its pivot. Extended = too far past "
              "the pivot; do not chase, wait for a pullback. Failed = closed back below.",

    # ---------------- price and level ----------------
    "Close": "Latest closing price.",
    "Chg %": "Change versus the previous close, in percent.",
    "Pivot": "The breakout trigger: the resistance level price must close above. It is the "
             "high of the detected consolidation, computed excluding the last two bars so a "
             "fresh spike cannot invent the level it is supposedly breaking.",
    "To pivot %": "How far the pivot sits above the current close, in percent. Smaller = "
                  "closer to triggering. A small negative value means price has just poked "
                  "above the level but has not yet cleared it by the 0.5% margin that would "
                  "move it to the breakout tab.",
    "Above pivot %": "How far price now sits above the level it broke. Small is good — you are "
                     "close to the level, so the stop is tight. Large means the move is "
                     "extended and the entry is late.",
    "Below pivot %": "How far price has fallen back below the level it broke. This is the "
                     "definition of a failed breakout.",
    "Off 52w high %": "Distance below the 52-week high, in percent. Breakouts work best near "
                      "the highs, where there is little trapped supply overhead. 0 means the "
                      "stock is at a new 52-week high.",

    # ---------------- base / structure ----------------
    "Pattern": "The chart structure recognised in the consolidation: VCP (contracting "
               "volatility), cup with handle, flat base, Darvas box, ascending triangle, bull "
               "flag, or a generic range consolidation. Descriptive, not predictive: over 10 "
               "years no pattern reliably beat a plain range consolidation, and bull flag and "
               "flat base underperformed it in both test folds, so the scoring tilt between "
               "patterns was deliberately flattened. Use it to recognise the structure, not "
               "to rank candidates.",
    "Base bars": "Length of the detected consolidation, in trading sessions. Longer bases "
                 "under the same resistance make that level more significant, and the "
                 "eventual break more meaningful.",
    "Base depth %": "Peak-to-trough depth of the consolidation. Deeper is looser, but it does "
                    "not widen your stop — the stop comes from the recent swing low and ATR. "
                    "A deep base does raise the measured-move target.",
    "Touches": "How many separate swing highs have tested this level (within the tolerance "
               "band). More touches = a better-established, more widely-watched level. 2–4 is "
               "the sweet spot.",

    # ---------------- contraction ----------------
    "ATR compr": "Volatility compression: current ATR% divided by ATR% 40 sessions ago. 0.75 "
                 "means the daily range is 25% narrower than two months ago — a coiling "
                 "spring. Below 1.0 is contraction; above 1.0 means the range is widening, "
                 "which is churn rather than coiling.",
    "Vol dryup": "Volume dry-up: 10-day average volume divided by the 50-day average. 0.80 "
                 "means recent volume is 20% below normal — sellers exhausted inside the base. "
                 "Lower is better here.",

    # ---------------- breakout confirmation ----------------
    "BO date": "The session on which price closed decisively through the pivot.",
    "Broke out": "The session on which price closed through the level, before failing.",
    "Days since": "Trading sessions since the breakout bar. 0 = it happened today. Fewer is "
                  "better: you are closer to the level, so the stop is tighter.",
    "BO volume x": "Volume on the breakout bar as a multiple of its own 50-day average. "
                   "Clearing 1.5× is the validated part: over 10 years, breakouts below "
                   "that threshold had negative mean R out-of-sample while gated ones stayed "
                   "positive, and win rate climbs 24%→38% with volume. Above the threshold, "
                   "returns keep improving only to about 3–5×, then flatten — the >5× bucket "
                   "was the weakest out-of-sample (blow-off risk). Treat it as a threshold to "
                   "clear, not a number to maximise.",
    "BO close pos": "Where the breakout bar closed inside its own range: 1.0 = at the high, "
                    "0.0 = at the low. Above ~0.7 means buyers held the highs into the close. "
                    "A weak close on a breakout day is a failure in progress.",
    "Why it failed": "Whether volume never confirmed the break, or price simply closed back "
                     "below the level.",

    # ---------------- momentum / strength ----------------
    "RSI": "Relative Strength Index (14). Roughly 45–70 is healthy for a breakout. Above 85 "
           "is climax territory where mean reversion becomes likely. Note: this is momentum, "
           "unrelated to the 'RS' columns.",
    "ADX": "Average Directional Index (14) — trend strength, not direction. Below 20 means "
           "consolidation (good *before* a breakout); rising through 25+ confirms a trend is "
           "underway (good *after* one).",
    "RS 60d %": "Relative strength: this stock's 60-day return minus the Nifty 500's over the "
                "same window. Positive = outperforming. Leadership shows up here before it "
                "shows up in price.",
    "RS 20d %": "This stock's 20-day return minus the Nifty 500's. Turning negative while the "
                "stock is still in an uptrend is an early tell that institutions are rotating "
                "out.",

    # ---------------- trend distance ----------------
    "vs EMA20 %": "Distance from the 20-day EMA, in percent. Negative means the short-term "
                  "trend support has been lost.",
    "vs SMA50 %": "Distance from the 50-day average, in percent. This is the line most "
                  "institutions watch; losing it is a meaningful change of character.",
    "vs SMA200 %": "Distance from the 200-day average, in percent — the long-term trend line. "
                   "Still positive means the primary uptrend is technically intact.",
    "Days above EMA20": "Consecutive sessions closed above the 20-day EMA. A long streak "
                        "ending at 0 means support was just lost after a sustained run.",
    "Dist days (15)": "Distribution days in the last 15 sessions: heavy-volume sessions "
                      "closing in the bottom quarter of their range. Three or more is the "
                      "classic institutional-selling footprint.",

    # ---------------- trade plan ----------------
    "Entry >": "Suggested trigger: the pivot plus a 0.5% buffer. Buy only once price closes "
               "above this on expanding volume — a small buffer avoids being trapped by a "
               "one-tick poke through the level.",
    "Entry": "Suggested entry at the current price, since the breakout has already happened.",
    "Stop": "Suggested initial stop: the tightest sensible level among the recent swing low "
            "less a quarter ATR, entry less 2 ATR, and the base low. Size the position from "
            "this distance — never widen it to fit a position you have already decided on.",
    "Suggested stop": "A defensive level for an existing position: the higher of the 50-day "
                      "average and the 20-day low.",
    "Trail (EMA20)": "The 20-day EMA, as a trailing reference once the move develops.",
    "Target": "Measured-move projection: the height of the base added to the entry. A "
              "conventional first objective, not a price forecast.",
    "Risk %": "Distance from entry to stop, in percent — your risk per share. Above 8% the app "
              "warns you: either size down or wait for a tighter entry.",
    "R:R": "Reward-to-risk: distance to target divided by distance to stop. Below about 2 the "
           "geometry is poor no matter how high the score, usually because the entry is "
           "already extended past the pivot.",

    # ---------------- liquidity ----------------
    "Turnover cr": "Median daily traded value over 20 sessions, in ₹ crore. Turnover — not "
                   "share count — decides whether your order size moves the price.",

    # ---------------- logs ----------------
    "Failed gate": "The first hard requirement this symbol failed. Gates are checked in order, "
                   "so this is the earliest reason it was excluded, not necessarily the only one.",
    "Why": "The actual numbers behind that rejection.",
    "Gate": "The requirement that was failed.",
    "Symbols rejected": "How many symbols failed at this gate.",
    "Reason": "Why this symbol was excluded from the scan.",
}

# ------------------------------------------------------------------ display formats
# printf-style, applied only to numeric columns.
_PCT = "%.2f%%"
_PCT1 = "%.1f%%"
_RS = "₹%.2f"

FORMAT: dict[str, str] = {
    "Close": _RS,
    "Pivot": _RS,
    "Entry": _RS,
    "Entry >": _RS,
    "Stop": _RS,
    "Suggested stop": _RS,
    "Trail (EMA20)": _RS,
    "Target": _RS,
    "To pivot %": _PCT,
    "Above pivot %": _PCT,
    "Below pivot %": _PCT,
    "Chg %": _PCT,
    "Risk %": _PCT,
    "Base depth %": _PCT1,
    "Off 52w high %": _PCT1,
    "RS 60d %": _PCT1,
    "RS 20d %": _PCT1,
    "vs EMA20 %": _PCT,
    "vs SMA50 %": _PCT,
    "vs SMA200 %": _PCT,
    "Score": "%.1f",
    "Risk score": "%.0f",
    "RSI": "%.1f",
    "ADX": "%.1f",
    "ATR compr": "%.2f",
    "Vol dryup": "%.2f",
    "BO volume x": "%.2fx",
    "BO close pos": "%.2f",
    "R:R": "%.2f",
    "Turnover cr": "₹%.1f cr",
}

# Columns worth keeping visible while scrolling a wide table sideways.
PINNED = ("Symbol",)
