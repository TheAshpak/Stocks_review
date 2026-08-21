# NSE Breakout Scanner

A local Streamlit app that screens Indian (NSE) equities for three things:

| Tab | What it finds |
|---|---|
| 🔥 **About to break out** | Bases coiling under established resistance, with volatility and volume contracting |
| 🚀 **Broken out & bullish** | Confirmed breakouts on expanding volume that are still holding their pivot |
| ⚠️ **Turning non-bullish** | Uptrends showing early deterioration — divergences, distribution, lost averages |

Every row can be clicked to see **every rule that fired, with the actual numbers it
judged on**, plus the warnings against the setup and a chart with the base box, pivot
line and trade levels drawn on it. **Hovering any column header** shows what that column
means and how to read it. Nothing is a black box, and nothing is silently
dropped — each tab carries a rejection log showing what was filtered out and why.

## Documentation

| Doc | Read it for |
|---|---|
| **[USAGE.md](USAGE.md)** | The daily workflow: when to run, which tab first, how to size a position, what to expect, troubleshooting |
| **[SETTINGS_GUIDE.md](SETTINGS_GUIDE.md)** | Every control in the web app — what it means, which rule it feeds, and what happens when you move it |
| **[PLAN.md](PLAN.md)** | Design plan, architecture, the two structural algorithms, the complete rule catalogue with weights, corrections made after seeing live output, and the improvement roadmap |
| **[BACKTEST.md](BACKTEST.md)** | The 10-year walk-forward backtest: method, what the scores were measured to predict, why fitted weights were rejected, and which findings changed the code |
| **[DEVELOPING.md](DEVELOPING.md)** | How to add a rule, an indicator or a pattern; how to swap the data source; how to test; and the gotchas |

## Install and run

```bash
cd nse_breakout_scanner
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 (Streamlit opens it for you).

On Windows you can just double-click **`run.bat`**.

Pick a universe in the sidebar and press **▶ Run scan**.

- First run on Nifty 500 downloads 2 years of daily bars for ~500 symbols — roughly a
  minute. After that the day's data is cached in `data_cache/` and rescans are instant.
- Changing any sidebar threshold re-applies the rules **without re-downloading**.
- **⟳ Re-download prices** forces a fresh pull (use it after the market closes to pick
  up the day's bar).
- To try it quickly, set **Cap universe size** to 100 before the first scan.

## How a stock qualifies

A breakout is only tradeable when four things line up: **a base** (price consolidated),
**a level** (resistance that has been tested), **contraction** (volatility and volume
drying up inside the base) and **confirmation** (a decisive close through the level on
expanding volume). Each tab enforces its own hard gates, then scores what survives:

```
score = 100 × Σ points / Σ weights     × market-regime multiplier
```

The in-app **📖 Method & rules** tab documents every gate, every scored factor with its
weight, and every warning and rejection rule. A summary:

**Tab 1 gates** — a valid base exists (depth-limited window *with price in the top 45%
of it*) · still below the pivot · within the distance-to-pivot limit · base long enough
and not too deep · above SMA200 · near the 52-week high · a prior advance leads into the
base · RSI not broken · liquidity floors.

The pivot is computed **excluding the last two bars**, so a fresh spike cannot invent
the level it is supposedly about to break.

**Tab 1 top-weighted factors** — volatility contraction (ATR% now vs 40 bars ago),
relative strength vs Nifty 500 including the RS line at a 60-day high, volume dry-up,
accumulation footprint (accumulation vs distribution days, up/down volume, OBV slope),
moving-average alignment, tight closes / NR7 / inside days, resistance touch count,
proximity to trigger, and the Minervini trend template.

**Tab 2 gates** — a bar in the lookback cleared a base built *strictly before it* ·
cleared by the minimum margin · still above that pivot · breakout volume ≥ the volume
multiple · above SMA50 and SMA200. Status is labelled `Fresh` / `Holding` / `Extended`
(chase risk) / `Failed`, and failed breakouts get their own table because they are the
cheapest lesson available.

**Tab 3** is restricted to stocks *still* in an uptrend — the point is to catch the turn
while there is profit to protect. 19 weighted deterioration signals (RSI and OBV
divergence, distribution days, lost EMA20, SMA50 break, death-cross risk, lower highs,
RS breakdown, parabolic exhaustion, failed breakout, channel break, reversal bars, …)
sum into a risk score, and a **Stage** column separates `Early warning` (chart still
looks fine, damage building underneath — the actionable cohort) from `Turning` and
`Breaking down`.

## Layout

```
app.py                 Streamlit UI: sidebar controls, regime banner, 4 tabs
core/config.py         Every threshold + Strict / Balanced / Loose presets
core/universe.py       NSE constituent lists (live CSV, disk cache, offline fallback)
core/data.py           Chunked yfinance download + per-day parquet cache
core/indicators.py     EMA/SMA, ATR, RSI, MACD, ADX, Bollinger, OBV, Donchian, …
core/structure.py      Swing pivots, base detection, pivot level, chart patterns
core/features.py       One OHLCV frame -> flat dict of ~90 scalars
core/rules.py          The rule engine: gates, scored signals, warnings, risk signals
core/scanners.py       The three scanners + trade-plan maths
core/market.py         Market regime and breadth
core/charts.py         Plotly candles with base box, pivot and trade levels
data_cache/            Parquet price cache + cached universe CSVs (gitignored)
```

## Limitations — please read

- **End-of-day data only**, from Yahoo Finance. Not official NSE data, and not live:
  intraday relative volume during market hours is unavailable.
- Prices are split/bonus adjusted; volume is not adjusted identically, so relative
  volume around a corporate action can mislead.
- **Earnings dates are not checked.** A breakout the day before results is a coin flip.
- Pattern detection is heuristic — it flags candidates for *your* eyes.
- **Weights are not fitted.** A 10-year walk-forward backtest ([BACKTEST.md](BACKTEST.md))
  found that optimising them did not survive out-of-sample validation, so the
  conventional weights were deliberately kept. Two findings that *did* hold were applied:
  the chase-risk threshold tightened to 8% past the pivot, and the chart-pattern scoring
  tilt was flattened.
- **The breakout score ranks outcomes; the pre-breakout score ranks imminence.** Measured
  over 5,847 historical breakouts, score quintiles produce mean +0.21R to +0.37R with the
  rank correlation positive in 10 of 10 calendar years. The pre-breakout score predicts
  whether and how soon a base gives way, not whether the resulting trade pays.
- Measured hit rate is ~34% at +0.32R average on the strict target-before-stop test.
  Breakout trading pays through asymmetry (small stops, trailed winners), not accuracy.

This tool screens and explains. It is not investment advice; position sizing and risk
management remain yours.
