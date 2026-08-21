# Usage — a daily workflow

For what every individual control does, see **[SETTINGS_GUIDE.md](SETTINGS_GUIDE.md)**.
This file is about how to actually run the thing and read the output.

## Starting up

```bash
cd C:\Users\asus\Desktop\random\nse_breakout_scanner
pip install -r requirements.txt      # first time only
streamlit run app.py
```

Or double-click `run.bat`. The browser opens at http://localhost:8501. Stop the server
with `Ctrl+C` in the terminal.

**When to run it:** after 15:30 IST, once the day's bar is complete. Yahoo's daily bar
updates within a few minutes of the close. Running mid-session gives you a partial bar —
the day's volume will be understated, which distorts every volume rule in the app.

## First scan

1. Leave **Universe** on Nifty 500 and **Strictness** on Balanced.
2. Press **▶ Run scan**.
3. First run downloads two years of daily bars for ~500 symbols — about 25 seconds — then
   caches them. Later scans the same day load from disk in under a second.
4. Next day, press **⟳ Re-download prices** to pull the new bar.

To try it out faster, set **Cap universe size** to 100 first — but note that caps take an
*alphabetical* slice (companies A–C), not the largest 100.

## Reading the header

The regime banner is the first thing to look at, because it tells you how much to trust
everything below it. Expand **"Why the regime is …"** to see the six pieces of evidence.

- 🟢 **Risk-On** — breakouts have tailwinds; normal position sizing is defensible.
- 🟡 **Neutral** — take only the highest-grade setups, size down.
- 🔴 **Risk-Off** — failure rates are elevated. Scores are already cut 15%. Consider
  standing aside entirely; this is when breakout traders lose money in a hurry.

## A workflow that works

### Step 1 — Tab 3 first, not Tab 1

Before looking for anything new, check what you already own. Filter **Stage** to
**Early warning** and look for your holdings. That is the cohort where the chart still
looks fine but distribution and divergences are building underneath — the only point at
which the information is still worth something. Names in `Breaking down` are already
obvious on any chart.

Protecting capital ranks above deploying it, which is why this tab comes first.

### Step 2 — Tab 2 for entries you can take today

Sort is already Fresh → Holding → Extended, then by score.

1. Filter **Status** to `Fresh` only.
2. Ignore anything with `R:R` below ~2 regardless of score — a 90-score stock 14% past its
   pivot is a bad trade with good characteristics.
3. Click the row. Check the chart: did the breakout bar close near its high, is the volume
   bar visibly taller than the orange average line, is the base box a real consolidation?
4. Read the **⚠️ Warnings** section before the ✅ section. The warnings are what will cost
   you money.

Then scroll to **❌ Failed breakouts**. Spend a minute here every day. These broke a level
and fell back below it, and the `Why it failed` column tells you which — usually volume
that never confirmed. After two weeks of this you will recognise a doomed breakout on
sight, which is worth more than any score in the app.

### Step 3 — Tab 1 for the watchlist

These have not triggered yet, so nothing here is a trade today; it is tomorrow's alert
list.

1. Deselect **Range consolidation** in the **Patterns** filter to leave only named
   structures (VCP, flat base, ascending triangle, bull flag, cup with handle, Darvas box).
2. Tick **Hide setups with warnings**.
3. Sort by score, take the top 5–15, click each one.
4. Note the **Pivot** and set a price alert there in your broker or TradingView. Do not
   buy in anticipation — roughly half of these never trigger, and the ones that break down
   from a base instead of up are exactly the ones that hurt.
5. Download the CSV to keep the list.

### Step 4 — when the alert fires

The stock has cleared the pivot. Before buying, confirm the thing the scanner could not
know in advance:

- **Volume.** Is the day's volume tracking at or above 1.5× the 50-day average? On a
  partial session, compare to the same time of day. If volume is ordinary, skip it — this
  single check eliminates most failed breakouts.
- **Close position.** Wait for the close if you can. A break that closes in the bottom
  third of the day's range is a failure in progress.
- **The calendar.** The app does not check earnings dates. A breakout the session before
  results is a coin flip, not a setup.

Then use the `Entry >`, `Stop` and `Target` from the table, sized so the distance to the
stop is a fixed fraction of your capital.

## Position sizing

The app gives you levels, never quantity. The standard method:

```
shares = (capital × risk_per_trade) / (entry − stop)
```

With ₹10,00,000 capital, 1% risk per trade and a stop 5% below a ₹640 entry:

```
risk per share = 640 − 608 = ₹32
shares = (1,000,000 × 0.01) / 32 = 312 shares  (≈ ₹2,00,000 position)
```

The **Risk %** column is the stop distance. When it exceeds 8% the app warns you: either
size down or wait for a tighter entry. Never widen the stop to fit a position you have
already decided to take.

## What to expect

- **Hit rate 40–50%** on good setups, in a decent market. Breakout trading is profitable
  through asymmetry — small stops, winners trailed a long way — not accuracy. A 45% hit
  rate with average winners three times average losers compounds nicely; the same hit rate
  with 1:1 payoff bleeds.
- **Row counts move with the tape.** Zero pre-breakout candidates in a correction is
  correct output, not a bug. Check the rejection log — if everything failed
  "Within striking distance of the pivot", nothing is set up right now.
- **Tab 3 will always have rows.** In any universe of 500, dozens of stocks are
  deteriorating. Use the Stage filter; the count itself is not a signal.

## Keeping a log

The single highest-return habit: download each tab's CSV daily and record, for every trade
you take, the score, the breakout volume multiple, whether it closed strong, and the
outcome in R multiples. After 30–50 trades you will know which pattern and which volume
threshold work *for you*, and you can move the sidebar thresholds on evidence instead of
taste. The scanner's weights are conventional practice, not a fitted edge — your log is
how they become one.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "No price data could be loaded" | No internet, or Yahoo throttling. Wait a minute, press ⟳ Re-download. |
| Universe note says "NSE unreachable … using built-in Nifty 50" | NSE archives blocked the request. The disk cache or the built-in list is being used; press ⟳ later. |
| Last bar is yesterday | You are running before Yahoo published today's bar, or the cache is from earlier. Press ⟳ Re-download prices. |
| Row counts drop to almost nothing | Check the preset — Strict is intentionally severe. Check the regime; in Risk-Off, scores are cut 15% and fewer clear the threshold. |
| A symbol you expect is missing | Look in "🔍 symbols could not be analysed" (fewer than 250 bars — recent listings) and in the tab's rejection log, which names the first gate it failed. |
| Slow after changing a slider | You changed one of the four feature-affecting settings (min base length, max base depth, breakout lookback, base selector). It rebuilds from cached prices — seconds, no download. |
| Charts don't render | `pip install plotly` |

## Data reality check

End-of-day only, from Yahoo Finance — unofficial, and occasionally wrong. Prices are
split/bonus adjusted but volume is not adjusted identically, so relative volume around a
corporate action can mislead. There is no intraday feed, no earnings calendar, and no
backtest behind the weights. Verify anything surprising on a second source before risking
money on it.
