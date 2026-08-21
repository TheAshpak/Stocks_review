# Design plan and rule specification

The plan this tool was built from, the reasoning behind each decision, the complete rule
catalogue with weights, and what to improve next. Read this before changing the analytics.

- **Built:** 20 Aug 2026 · **Data verified against:** NSE close of 20 Aug 2026
- **Companion docs:** [SETTINGS_GUIDE.md](SETTINGS_GUIDE.md) (every UI control) ·
  [USAGE.md](USAGE.md) (workflow) · [BACKTEST.md](BACKTEST.md) (validation) ·
  [DEVELOPING.md](DEVELOPING.md) (how to extend)

---

## 1. The premise

A breakout is tradeable only when four things line up:

1. **A base** — price has consolidated, so there is a level to break.
2. **A level** — resistance that has actually been tested, not a line drawn on one bar.
3. **Contraction** — volatility and volume drying up inside the base. Sellers exhausted.
4. **Confirmation** — a decisive close through the level on expanding volume.

Anything missing one of these is noise. The three tabs are the three states of this
lifecycle: *coiling* (1–3 present, 4 pending), *confirmed* (all four), and *failing* (the
trend that followed is now deteriorating).

Two design commitments follow from that, and they drove most of the implementation:

- **Every verdict must be explainable with numbers.** A rule that cannot state the value
  it judged on is not implemented. This is why the engine returns `Signal` objects
  carrying a `detail` string built from live values, rather than booleans.
- **Nothing is silently dropped.** Every rejected symbol appears in that tab's rejection
  log with the first gate it failed. A screener that only shows survivors cannot be
  debugged or trusted.

---

## 2. Decisions and why

| Decision | Choice | Reasoning |
|---|---|---|
| Data source | yfinance daily OHLCV, `SYMBOL.NS` | Only zero-credential source for NSE. Verified current to the same-day close. Kite/Fyers would need API keys and a broker account. |
| History | 2 years (~500 bars) | SMA200 needs 200, 52-week stats need 250, percentile ranks want more. 2y is the cheapest window that satisfies all three. |
| Adjustment | `auto_adjust=True` | Split/bonus-adjusted OHLC keeps structure continuous. Unadjusted series show phantom gaps a breakout scanner reads as real moves. Cost: volume is not adjusted identically — documented as a limitation. |
| Universe | NSE archive CSVs | Authoritative, free, no key. Cached to disk; the cache doubles as offline fallback, with a built-in Nifty 50 as last resort. |
| Benchmark | `^CRSLDX` (Nifty 500) | Broadest index with clean history — the right yardstick for relative strength across caps. |
| Regime inputs | `^NSEI`, `^INDIAVIX`, universe breadth | Index trend, volatility regime and participation are the three things that actually predict breakout failure rates. |
| Indicators | Hand-rolled on pandas/numpy | TA-Lib needs a C toolchain on Windows; pandas-ta is unmaintained against pandas 3.x. ~170 lines removes a whole class of install failure. |
| Caching | Per-day parquet, keyed by universe + period + date + **symbol-set hash** | The hash is load-bearing — see §6. |
| Scoring | `100 × Σpoints / Σweights` | Normalised, so adding or removing a rule cannot silently rescale scores. Partial credit via `ramp()` avoids cliff-edge behaviour at thresholds. |
| State | `st.session_state`, explicit Run button | Scanning 500 symbols on every widget interaction would be unusable. Features are cached and only rebuilt when a feature-affecting setting changes. |

---

## 3. Architecture

```
app.py                 Streamlit UI: sidebar, regime banner, 4 tabs, reason panels
core/config.py         Settings dataclass — every threshold + 3 presets
core/universe.py       NSE constituent CSVs, disk cache, offline fallback
core/data.py           Chunked threaded yfinance download, per-day parquet cache
core/indicators.py     EMA/SMA/Wilder, ATR, RSI, MACD, ADX, Bollinger, OBV,
                       Donchian, stochastic, accumulation/distribution days
core/structure.py      Fractal pivots, base detection, resistance, patterns,
                       breakout event location, regression channel
core/features.py       One OHLCV frame -> flat dict of ~95 scalars
core/rules.py          Signal/ScoreCard + all gates, scores, warnings, risk signals
core/scanners.py       The three scanners + trade-plan maths
core/market.py         Regime scoring and breadth
core/charts.py         Plotly candles with base box, pivot, trade levels
core/columns.py        Column tooltips and display formats (pure data)
core/weights.py        Runtime weight overrides, so a fitted set can be swapped in
backtest/              Walk-forward event engine, factor stats, weight fitting
```

**Data flow, once per scan:**

```
universe CSV ─┐
              ├─> load_prices (parquet cache) ─> {symbol: OHLCV}
benchmark ────┘                                       │
                                                      v
                                        bulk_features -> {symbol: ~95 scalars}
                                                      │
                        ┌─────────────────────────────┼──────────────────────┐
                        v                             v                      v
                 scan_pre_breakout            scan_breakouts           scan_weakening
                        │                             │                      │
                        └──────── market.assess ──────┴──────────────────────┘
                                  (regime multiplier)
```

Features are computed **once** per symbol and shared by all three scanners. That is what
keeps rescans at ~0.07 s and guarantees the three tabs never disagree about the same
stock.

**Measured performance** (Nifty 500, 485 symbols with sufficient history):
download 25 s cold / 0.3 s cached · features 10 s (~21 ms/symbol) · all three scans
0.07 s · full three-preset sweep 32 s.

---

## 4. The two structural algorithms

Everything else is conventional TA. These two are where the real design work went, and
both were corrected after inspecting live output.

### 4.1 Base detection (`structure.detect_base`)

For every window length `L` in `[min_len, max_len]`, take the window's high and low and
compute depth. A window **qualifies** when:

- `depth ≤ max_depth`, and
- price currently sits in the **top 45%** of the range (`min_position = 0.55`).

The position requirement was added after the first version returned nonsense: TCS came
back with a 119-bar "base" whose high was printed 117 bars earlier and where price sat
mid-range at 0.49. That is not a base, it is a stale high with price drifting under it.
Requiring price near the top of the box makes the structure mean what its name says.

Among qualifying windows, `select` decides the winner — `"longest"` (default) or
`"quality"`. See §6 for the measured comparison; the short version is that "longest"
yields median R:R 5.1 versus 1.9, so it ships as the default.

Window extremes use suffix `np.maximum.accumulate` / `minimum.accumulate` scans, making
the whole search O(n) instead of O(n²) — it runs 500+ times per scan.

**`exclude_recent=2`**: the resistance level is computed ignoring the last two bars, so a
fresh spike cannot invent the very level it is supposedly about to break. Tab 1 uses this;
`find_breakout` does not need it because it rebuilds the base from prior bars anyway.

Derived and reported: depth, position, touch count (swing highs within the pivot
tolerance), pivot age, closing tightness, three-thirds contraction sequence (the VCP
test), and the prior advance into the base.

### 4.2 Breakout location (`structure.find_breakout`)

Walking back from the latest bar, for each candidate bar `i`:

1. Rebuild the base from `df.iloc[:i]` — **strictly the bars before it**.
2. Require `close[i]` to clear that base high by `min_clear` (0.5%).
3. Require `close[i-1]` to be *below* the level, so we find the bar that actually broke
   it rather than any bar sitting above an older level.
4. Return the first (most recent) qualifying bar, with its relative volume, close position
   in range, and gap.

Point 1 is the anti-hindsight guarantee: the pivot is the level a trader would have been
watching at the time, not one fitted afterwards to the price that followed. `min_position`
is relaxed to 0.35 here because the defining event is the clearance itself — a gap-up from
mid-range still counts.

---

## 5. Complete rule catalogue

Extracted from the code, not written by hand.

### Tab 1 — pre-breakout

**Hard gates** (fail = rejected, reason logged): `LIQ_PRICE`, `LIQ_VOL`, `LIQ_TURN`,
`PB_BASE` (a base exists), `PB_BELOW` (still below the pivot), `PB_NEAR` (within striking
distance), `PB_LEN`, `PB_DEPTH`, `PB_SMA200`, `PB_52W`, `PB_LEG` (prior advance),
`PB_RSI`.

**Scored factors — total weight 122:**

| ID | Category | Factor | Wt |
|---|---|---|---|
| `PB_ATR` | Volatility | Volatility contracting (ATR% now vs 40 bars ago) | 12 |
| `PB_RS` | Relative strength | Outperforming Nifty 500 + RS line at 60-day high | 12 |
| `PB_DRYUP` | Volume | Volume drying up in the base (10d vs 50d) | 10 |
| `PB_ACC` | Volume | Accumulation: acc vs dist days, up/down volume, OBV slope | 10 |
| `PB_STACK` | Trend | Moving averages aligned and rising | 10 |
| `PB_TIGHT` | Volatility | Tight closes + NR7/inside-day count | 8 |
| `PB_TOUCH` | Structure | Resistance level well established (touch count) | 8 |
| `PB_PROX` | Structure | Close to the trigger | 8 |
| `PB_TEMPLATE` | Trend | Minervini 8-point trend template | 8 |
| `PB_SQUEEZE` | Volatility | Bollinger bandwidth percentile (250d) | 6 |
| `PB_VCP3` | Volatility | Successive contractions (three thirds) | 6 |
| `PB_HL` | Structure | Higher lows into resistance | 6 |
| `PB_LEGQ` | Trend | Strong prior advance | 6 |
| `PB_POS` | Structure | Price at the top of the base | 4 |
| `PB_ADX` | Momentum | ADX coiled with DI+ > DI− | 4 |
| `PB_PATTERN` | Structure | Recognised chart pattern | 4 |

**Warnings** (shown, never hidden): `W_ATR_EXP` volatility expanding · `W_DISTRIB`
distribution inside the base · `W_DOWNVOL` down-day volume dominant · `W_EMA20` below
20-EMA · `W_SMA50` below 50-SMA · `W_SUPPLY` heavy overhead supply · `W_DEEP` wide and
still choppy · `W_DEATH` death cross approaching · `W_GAPDN` recent gap down · `W_RSDOWN`
lagging the market · `W_DIVERGE` bearish RSI divergence · `W_STALE` resistance level old.

### Tab 2 — confirmed breakout

**Hard gates:** `LIQ_*`, `BO_EVENT` (a breakout occurred), `BO_CLEAR` (cleared
decisively), `BO_HOLD` (still above the pivot), `BO_VOL` (volume confirmed — optional),
`BO_TREND` (above SMA50 and SMA200).

**Scored factors — total weight 102:**

| ID | Category | Factor | Wt |
|---|---|---|---|
| `BO_RVOL` | Volume | Volume surge on the breakout bar | 18 |
| `BO_RS` | Relative strength | Leading the market | 12 |
| `BO_FOLLOW` | Structure | Holding and following through | 10 |
| `BO_POSTVOL` | Volume | Healthy volume behaviour since the break | 10 |
| `BO_CLOSE` | Structure | Closed strong on the breakout bar | 8 |
| `BO_FRESH` | Structure | Entry still timely | 8 |
| `BO_HIGH` | Trend | Breaking into new-high territory | 8 |
| `BO_STACK` | Trend | Moving averages aligned | 8 |
| `BO_ADX` | Momentum | Trend strength expanding | 6 |
| `BO_MOM` | Momentum | Momentum confirming, not exhausted | 6 |
| `BO_GAP` | Structure | Not a runaway gap | 4 |
| `BO_TURN` | Volume | Participation expanding | 4 |

**Warnings:** `BW_WEAKVOL` · `BW_WICK` · `BW_EXT` chase risk · `BW_ATREXT` stretched from
20-EMA · `BW_CLIMAX` · `BW_DIST` · `BW_SUPPLY` · `BW_DIVERGE`.

**Status:** `Fresh` ≤2 sessions · `Holding` · `Extended` past the limit · `Failed` closed
back below (routed to its own table).

### Tab 3 — deterioration

Gated to stocks still above SMA50 or SMA200. Risk score = capped sum of triggered points
(186 if every signal fired; capped at 100).

| ID | Signal | Pts |
|---|---|---|
| `WK_DIST` | Institutional distribution (heavy-volume down closes) | 14 |
| `WK_FAILBO` | Failed breakout | 14 |
| `WK_RSIDIV` | Bearish RSI divergence | 12 |
| `WK_SMA50` | Below the 50-day average | 12 |
| `WK_CLIMAX` | Parabolic / exhaustion move | 12 |
| `WK_OBVDIV` | Bearish OBV divergence | 10 |
| `WK_MACD` | MACD rolled over | 10 |
| `WK_EMA20` | Lost the 20-day EMA | 10 |
| `WK_DEATH` | Death-cross risk | 10 |
| `WK_RS` | Relative strength breaking down | 10 |
| `WK_DONCHIAN` | Broke the 20-day low | 10 |
| `WK_CHANNEL` | Broke the rising regression channel | 10 |
| `WK_SMA50SLOPE` | 50-day average turning down | 8 |
| `WK_LH` | Lower swing highs | 8 |
| `WK_UDVOL` | Down days carrying the volume | 8 |
| `WK_ADX` | Trend strength fading / DI− above DI+ | 8 |
| `WK_CANDLE` | Bearish reversal bar at the highs | 8 |
| `WK_GAPDN` | Gap down on volume | 8 |
| `WK_MACDFADE` | MACD histogram fading while price holds | 4 |

**Severity:** Watch <25 · Caution 25–44 · High risk 45–64 · Exit signal ≥65 or ≥7 signals.
**Stage:** Early warning (above 20-EMA and 50-SMA) · Turning (lost 20-EMA) · Breaking down
(below 50-SMA).

---

## 6. Corrections made after seeing live output

Recorded because the reasoning matters more than the code, and because each one is a trap
worth not falling into twice.

**Stale bases.** First version took the longest window inside the depth limit, full stop.
TCS returned a 119-bar base with a 117-bar-old high and price mid-range. Fixed by
requiring price in the top 45% of the box.

**Self-defined resistance.** A stock spiking to a new high had that same bar define the
level it was "about to break", so distance-to-pivot was trivially ~0. Fixed with
`exclude_recent=2`.

**Base selection A/B test.** A "quality" selector balancing length against tightness
produced prettier structures — 20 bull flags instead of 25 range consolidations, bases
9.8% deep instead of 24%, and warnings per row down from 1.28 to 0.52. It was still the
wrong default, because **median R:R fell from 5.1 to 1.9**. The stop comes from the recent
swing low and ATR, not the base low, so a tighter base does not tighten the stop — it only
shrinks the measured-move target. Kept "longest" as default, shipped "quality" as an
option. *Lesson: judge a structural change by the trade geometry it produces, not by how
clean the labels look.*

**Miscalibrated wide-base warning.** With "longest" selected, nearly every row reported
21–25% depth and tripped a "base is wide and loose" warning — noise on every row is the
same as no warning at all. Re-aimed at what actually hurts: depth >20% **and** closing
tightness >2.5%, i.e. deep *and still choppy*. Warnings-per-row fell to 0 on the test run
while the genuine cases still fire.

**Cache poisoning (real bug).** The parquet cache key was universe + period + date. A
capped 100-symbol scan wrote a cache that a later full 500-symbol scan happily read back,
silently scanning a subset. Now keyed by a SHA1 of the sorted symbol set, with the date
first so pruning stays chronological.

**Stale features on setting change.** The UI re-ran only the scanners when settings
changed, but several settings feed the *feature* engine (base length, depth, breakout
lookback, base selector). Changing them produced results computed against stale features.
Fixed with an explicit `FEATURE_KEYS` fingerprint that triggers a rebuild from cached
prices.

---

## 7. Roadmap

Ordered by value per unit of effort.

### Done
1. ~~**Backtest harness.**~~ **Built** — see [BACKTEST.md](BACKTEST.md). 10 years, 500
   symbols, 5,847 breakout and 13,313 pre-breakout events, all scored through the
   production rule engine on truncated frames. Verdict: the Tab 2 score ranks outcomes
   (IC +0.077, positive in 10/10 years); the Tab 1 score ranks imminence, not
   profitability; and fitted weights **failed** out-of-sample so the conventional set was
   kept. The next iteration should fix the *feature set* — 18% of Tab 1's weight sits on
   factors that are near-constant once the gates have run — rather than the weights.

### High value
2. **Earnings-date awareness.** A breakout the session before results is a coin flip. Even
   a scraped calendar with a "results within 5 sessions" flag would prevent real losses.
3. **Sector/industry context.** `industry` is already carried through from the NSE CSV but
   unused in scoring. Breakouts cluster by sector; a stock breaking out while its sector
   leads is a materially better bet. Add a sector-strength score and a rule that rewards it.
4. **Replace the near-constant factors.** Measured: `PB_STACK` averages 0.955 credit
   (85% of candidates at full credit), `PB_TEMPLATE` 0.925, `BO_TURN` 0.980. The gates
   already select for these, so re-asking inside the score cannot rank anything. This is
   the binding constraint on score quality — not the weights, which have now been shown
   not to be improvable by fitting on this feature set.

### Medium value
5. **Watchlist persistence.** Save pivots to a small SQLite/JSON store and, on the next
   run, report which triggered, which failed, and which are still coiling. This turns the
   tool from a daily snapshot into a tracked process — and generates the trade log that
   §USAGE recommends keeping by hand.
6. **Weekly-timeframe confirmation.** Resample to weekly and require the weekly structure
   to agree. Cheap to add, historically a strong filter.
7. **Alternative data source.** A Kite/Fyers adapter behind the existing `data.py`
   interface would give official NSE data, real intraday relative volume, and delivery
   percentage (a genuine accumulation signal Yahoo cannot provide).
8. **Volume-profile resistance.** `overhead_supply_pct` is a crude proxy. A real volume
   profile would locate high-volume nodes precisely and pick better pivots.

### Lower value / polish
9. Intraday mode for live relative volume during market hours.
10. Multi-pivot support — report the next two levels above, not just the nearest.
11. Portfolio view: paste holdings, get Tab 3 filtered to them automatically.
12. Email/Telegram alert on pivot trigger.
13. Relative-strength *rank* (percentile within the universe) rather than raw excess
    return — closer to how RS is conventionally used.

### Explicitly rejected
- **Machine-learned scoring.** Without the backtest it cannot be validated, and it would
  destroy the explainability that is the point of this tool.
- **Intraday breakout alerts on Yahoo data.** The feed is not reliable enough intraday to
  act on.
- **More patterns for their own sake.** Six named patterns already cover the tradeable
  vocabulary; adding head-and-shoulders variants adds surface area, not edge.

---

## 8. Invariants — do not break these

1. **Every rule states its numbers.** New rules must build `detail` from live values.
2. **No hindsight.** Any level used to judge bar `i` must be computable from bars `< i`.
3. **Rejections are visible.** Nothing gets filtered without a logged reason.
4. **Features are computed once.** Scanners read features; they never recompute
   indicators. If a scanner needs a new number, it belongs in `features.py`.
5. **Score normalisation holds.** Always `Σpoints / Σweights` — never a hand-tuned
   constant denominator.
6. **Thresholds live in `config.py`.** No magic numbers in scanner or rule bodies; a rule
   that needs a threshold gets a `Settings` field.
