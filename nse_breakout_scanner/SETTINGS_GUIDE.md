# Settings Guide — every control in the web app

This is the reference for every option in the UI: what it means, which rule it feeds,
and what happens when you move it. Presets are shown as **S**trict / **B**alanced /
**L**oose.

**Column definitions live in the app itself:** hover any column header in any table and
a tooltip explains what the number means and how to read it. The definitions are in
`core/columns.py`, so this doc covers the *controls* and the app covers the *columns*.

Two practical notes before the tables:

- **Rescan vs rebuild.** Most controls only re-run the scoring, which is instant. Four
  of them feed the *feature engine* and force a rebuild from cached prices (a few
  seconds, no download): **Min base length**, **Max base depth**, **Breakout within last
  N sessions**, and the **base selector** radio. Nothing except the two buttons ever
  re-downloads data.
- **Gates vs scores.** A *gate* is pass/fail — fail it and the stock never appears, and
  the reason lands in that tab's rejection log. A *scored factor* only moves the number.
  Loosening a gate adds rows; lowering a score threshold adds rows *of lower quality*.
  They are not interchangeable.

---

## 1. Top of the sidebar

### Universe
Which NSE list to scan, pulled live from the NSE archives (cached to disk, with an
offline fallback).

| Option | Symbols | First-run download | Notes |
|---|---|---|---|
| Nifty 50 | 50 | ~5 s | Large caps only. Few breakouts — these move slowly. |
| Nifty 100 | 100 | ~8 s | |
| Nifty 200 | 200 | ~12 s | Good quality/opportunity balance. |
| **Nifty 500** (default) | 500 | ~25 s | Recommended. Where most clean setups live. |
| Nifty Midcap 150 | 150 | ~10 s | Higher volatility, more breakouts, more failures. |
| Nifty Smallcap 250 | 250 | ~15 s | Most breakouts *and* most false breakouts. Keep the liquidity floors high here. |
| All NSE equity | ~2,000+ | 3–8 min | Maximum coverage including microcaps. The liquidity gates do the heavy lifting; expect many rejections. |

Switching universe requires pressing **▶ Run scan** again.

### Cap universe size (0 = no cap)
`0–2500`, default `0`. Scans only the first N symbols.

**Important:** the NSE constituent file is sorted **alphabetically by company name**, so
`cap = 100` scans roughly companies A–C — *not* the 100 largest. It is a speed knob for
trying the app out, not a sampling method. Leave it at `0` for real work.

### Strictness preset
`Strict` / **`Balanced`** / `Loose`. Sets every threshold at once; you can then override
any individual control below it. Real measured output on Nifty 500 (20 Aug 2026 close,
485 symbols analysed):

| Preset | Pre-breakout | Breakouts | Failed breakouts | Weakening |
|---|---|---|---|---|
| Strict | 4 | 8 | 10 | 179 |
| Balanced | 36 | 21 | 27 | 150 |
| Loose | 127 | 48 | 44 | 223 |

What each preset actually changes versus Balanced:

| Setting | Strict | Balanced | Loose |
|---|---|---|---|
| Min turnover (₹ cr) | 10.0 | 5.0 | 2.0 |
| Min price (₹) | 30 | 30 | 20 |
| Max distance to pivot | 3.0% | 4.0% | 7.0% |
| Min base length | 25 | 15 | 10 |
| Max base depth | 20% | 25% | 32% |
| Max below 52w high | 15% | 25% | 35% |
| Min prior advance | 25% | 20% | 10% |
| Require above SMA200 | yes | yes | **no** |
| ATR compression target | 0.70 | 0.75 | 0.90 |
| Volume dry-up target | 0.75 | 0.80 | 0.95 |
| Max tightness | 2.5% | 3.0% | 4.5% |
| Min RSI | 50 | 45 | 40 |
| Min setup score | 70 | 50 | 35 |
| Breakout lookback | 7 d | 10 d | 15 d |
| Min breakout volume | 2.0× | 1.5× | 1.2× |
| Volume a hard gate | yes | yes | **no** |
| Max % above pivot | 6% | 8% | 12% |
| Min breakout close position | 0.70 | 0.60 | 0.50 |
| Min breakout score | 70 | 50 | 35 |
| Min deterioration signals | 2 | 2 | 1 |
| Min risk score | 20 | 25 | 15 |

Note the deliberate quirk: **Strict lowers the Tab 3 risk threshold** (20 vs 25). Being
strict about entries means being *more* sensitive about exits, not less.

---

## 2. Liquidity filters (apply to all three tabs)

These are hard gates. An unfillable breakout is not a breakout — if you cannot get in
and out at the price on the chart, the setup is fiction.

| Control | Default | Range | What it means | Effect |
|---|---|---|---|---|
| **Minimum price (₹)** | 30 (L: 20) | 1–5000 | Rejects sub-₹30 stocks | Penny stocks have spreads that swallow the edge and tick sizes that distort ATR. Lowering below ~20 pulls in noise. |
| **Min 20d average volume** | 200,000 | 0–10M | Shares traded per day | Crude but catches dead counters. |
| **Min 20d median turnover (₹ cr)** | 5.0 (S: 10, L: 2) | 0–500 | Median of `close × volume` over 20 days | **The one that matters.** Turnover, not share count, decides whether your order size moves the price. A ₹40 stock trading 500k shares is ₹2 cr/day — thin. Raise to 10–25 if you trade size; drop to 2 to hunt smallcaps. |

Median (not mean) is used deliberately so one spike day cannot make an illiquid stock
look tradeable.

---

## 3. Tab 1 — about to break out

### The gates

| Control | Default | Range | What it means | Raise it → | Lower it → |
|---|---|---|---|---|---|
| **Max distance to pivot (%)** | 4.0 (S: 3, L: 7) | 0.5–12 | How far below the trigger price may still be | More candidates, earlier — but you wait longer and some never trigger | Fewer, more imminent candidates |
| **Min base length (bars)** | 15 (S: 25, L: 10) | 8–60 | Minimum consolidation, in trading sessions | Only long, mature bases — fewer but stronger levels | Short coils and flags qualify; more noise. *Rebuilds features.* |
| **Max base depth (%)** | 25 (S: 20, L: 32) | 8–45 | Peak-to-trough allowed inside the base | Loose, wide ranges qualify | Only tight boxes; can reject a genuinely good long base in a volatile stock. *Rebuilds features.* |
| **Max % below 52-week high** | 25 (S: 15, L: 35) | 5–60 | Excludes deep-basing wrecks | Includes recovery plays that may still have overhead supply | Only names near their highs (where breakouts work best) |
| **Min prior advance into base (%)** | 20 (S: 25, L: 10) | 0–60 | Size of the leg *before* the base | Only continuation setups | Allows bases with no trend behind them — breakouts continue trends, they rarely start them |
| **Min RSI(14)** | 45 (S: 50, L: 40) | 20–70 | Momentum floor | Excludes anything sluggish | Lets weakening names through |
| **Require close above SMA200** | on (L: off) | — | Long-term trend filter | — | Turning this off is the single biggest quality change in the whole app. Only do it deliberately, hunting early turnarounds. |

### The score threshold

| Control | Default | Range | Effect |
|---|---|---|---|
| **Min setup score** | 50 (S: 70, L: 35) | 0–95 | Filters on the 0–100 quality score. Grades: A+ ≥85, A ≥75, B+ ≥65, B ≥55, C ≥45, D below. Setting 70+ typically leaves single digits on Nifty 500. |

### The two contraction targets

These are the heart of the pre-breakout logic, and they are **scored, not gated** — a
stock missing the target still appears, just with fewer points, and the detail line shows
you the actual number.

| Control | Default | Range | What it means |
|---|---|---|---|
| **ATR compression target (now ÷ 40 bars ago)** | 0.75 (S: 0.70, L: 0.90) | 0.40–1.20 | Current ATR% divided by ATR% 40 sessions ago. `0.75` means "today's daily range is 25% narrower than it was two months ago". Full credit is awarded at `target − 0.15`, zero credit at `1.00`. Volatility contraction is the most reliable pre-breakout tell — a spring coiling. |
| **Volume dry-up target (10d ÷ 50d)** | 0.80 (S: 0.75, L: 0.95) | 0.40–1.20 | 10-day average volume over 50-day average. `0.80` means recent volume is 20% below normal — sellers exhausted inside the base. Full credit at `target − 0.15`, zero at `1.10`. |

Lowering either number demands *more* contraction and makes the score harder to earn;
raising it toward 1.0 makes contraction nearly free and dilutes the ranking.

### In-tab filters (above the table)

| Control | What it does |
|---|---|
| **Min score** | Filters the already-computed table without rescanning |
| **Max % to pivot** | Narrow to the most imminent triggers |
| **Hide setups with warnings** | Shows only rows with zero warning flags — a fast quality cut |
| **Patterns** | Multi-select: VCP, Darvas box, Flat base, Ascending triangle, Bull flag, Cup with handle, Range consolidation. Deselecting "Range consolidation" leaves only named structures — but note the backtest found **no pattern reliably beat a plain range consolidation**, and bull flag / flat base underperformed it in both folds, so the scoring tilt between patterns has been flattened. Filter by pattern to match your own style, not for an expected edge. |

### Columns you will read most

All column definitions are available as header tooltips in the app; the essentials:

`Pivot` is the trigger price. `To pivot %` is how far away it is (negative means price has
just poked above the level but not yet cleared it by the 0.5% margin that would move it to
Tab 2). `Entry >` is the pivot plus a 0.5% buffer — a small buffer beats a one-tick poke.
`Stop` is the highest (tightest) of: the 10-day low less 0.25 ATR, entry less 2 ATR, and
the base low. `Target` is the measured move — base height projected from entry. `R:R` is
reward over risk; anything under ~2 means the geometry is poor even if the score is high.

---

## 4. Tab 2 — broken out & bullish

| Control | Default | Range | What it means | Effect |
|---|---|---|---|---|
| **Breakout within last N sessions** | 10 (S: 7, L: 15) | 1–30 | How far back to search for the breakout bar | Higher = more names but staler entries; you are further from the level and the stop is wider. *Rebuilds features.* |
| **Min breakout volume (× 50d avg)** | 1.5 (S: 2.0, L: 1.2) | 1.0–4.0 | Volume on the breakout bar relative to its 50-day average | The most important single filter in this tab. A break on average volume is the commonest failure mode. |
| **Volume confirmation is a hard requirement** | on (L: off) | — | Whether the above is a gate or just a scored penalty | Turning it **off** lets unconfirmed breakouts into the table with a warning instead of rejecting them. Useful for studying failures; risky for trading. |
| **Max % above pivot before 'extended'** | 8 (S: 6, L: 12) | 3–40 | Where the `Extended` label and chase-risk warning start | Lower = stricter about entry timing. The 8% default is backtested: out-of-sample, mean R goes **negative** beyond 8% past the pivot (−0.17 in the 8–15% band, −0.15 above 15%) with excess returns collapsing too. Raising it past ~10% re-admits trades the data says lose money. |
| **Min breakout score** | 50 (S: 70, L: 35) | 0–95 | Score threshold | Same grade bands as Tab 1 |

### In-tab filters
**Min score** · **Status** (multi-select) · **Min breakout volume ×** (0–6, filters the
displayed table more aggressively than the gate) · **Max % above pivot**.

### The Status column

| Status | Meaning | What to do |
|---|---|---|
| `Fresh` | Broke out ≤2 sessions ago and not extended | The actionable cohort |
| `Holding` | Older break, still above the pivot | Fine, but the stop is further away |
| `Extended` | More than the extension limit past the pivot | Do not chase. Wait for a pullback toward the 20-EMA. |
| `Failed` | Closed back below the pivot | Routed to the separate failed-breakout table |

### Failed breakouts table
Always shown, never filtered by score. This is deliberate — it is the cheapest lesson
available, and a failed breakout often precedes a sharp reversal. The `Why it failed`
column distinguishes "volume never confirmed" from "closed back below the level".

### Trade-plan columns
`Entry` is the current close (you are buying an already-broken-out stock). `Stop` is the
higher of pivot × 0.98 and close − 2.5 ATR — the pivot should now act as support.
`Trail (EMA20)` is the trailing reference once the move develops.

---

## 5. Tab 3 — turning non-bullish

This tab only considers stocks **still in an uptrend** (above the 50- or 200-day
average). The point is to catch the turn while there is profit to protect. Names already
below both averages are excluded and listed separately — those are downtrends, not turns.

| Control | Default | Range | What it means | Effect |
|---|---|---|---|---|
| **Min deterioration signals** | 2 (L: 1) | 1–8 | How many of the 19 signals must fire | 1 is very noisy; 3–4 gives a short, high-conviction list |
| **Min risk score** | 25 (S: 20, L: 15) | 0–90 | Threshold on the summed risk score | See severity bands below |
| **Distribution days that count as heavy** | 3 | 1–8 | How many heavy-volume down-closes in 15 sessions trigger the "institutional distribution" signal (worth 14 points, the joint-highest) | Lowering to 2 makes the tab much more sensitive |

### Severity bands
`Watch` <25 · `Caution` 25–44 · `High risk` 45–64 · `Exit signal` ≥65 **or** ≥7 signals.

### The Stage column — read this one first
Severity tells you *how much* is wrong; Stage tells you *how early* you are.

| Stage | Meaning | Value |
|---|---|---|
| **Early warning** | Still above both the 20-EMA and 50-SMA — the chart looks fine while divergences and distribution build underneath | **The actionable cohort.** This is what "about to turn" means. |
| `Turning` | Lost the 20-EMA, still above the 50-SMA | Damage starting to show |
| `Breaking down` | Below the 50-SMA | The market has already noticed; you are late |

On the Balanced Nifty 500 run this split 46 / 36 / 68. Filter to **Early warning** to use
this tab as intended.

`Suggested stop` is the higher of the SMA50 and the 20-day low.

---

## 6. Market regime

| Control | Default | What it does |
|---|---|---|
| **Let the market regime scale scores** | on | Multiplies every Tab 1 and Tab 2 score by the regime multiplier |

The regime is scored from six pieces of evidence: Nifty 50 versus its 20-, 50- and
200-DMA (1 point each), universe breadth (+1 if >55% of scanned stocks are above their
50-DMA, −1 if <35%), and India VIX (+0.5 below 15, −1 above 20).

| Total | State | Multiplier |
|---|---|---|
| ≥3.0 | 🟢 Risk-On | ×1.05 |
| 1.5–2.5 | 🟡 Neutral | ×1.00 |
| ≤1.0 | 🔴 Risk-Off | ×0.85 |

Breakout failure rates rise sharply when the index is under its own averages and
participation narrows, which is why this exists. Turn it off only when you want raw,
market-blind scores. The banner's expander always shows the evidence, so you can see
exactly why the tape was labelled the way it was.

The header metrics — Nifty 50, India VIX, % above 50-DMA, % above 200-DMA, % advancing —
are computed across *your scanned universe*, so they change with the universe selection.

---

## 7. Advanced — how the base is chosen

Radio: **Most significant level** (default) / **Tightest recent base**. Rebuilds features.

Both find every window whose depth is within the limit and where price sits in the top
45% of the range. They differ in which one wins:

| | Most significant level | Tightest recent base |
|---|---|---|
| Picks | The longest qualifying window | Best blend of length and tightness (60/40 toward tightness) |
| Typical base | 57–120 bars, 21–25% deep | 15–36 bars, 4–13% deep |
| Pivot is | A major multi-month high | A recent short-term high |
| Patterns found | Mostly range consolidations, some VCP/triangles | Mostly bull flags, flat bases, Darvas boxes |
| Measured **median R:R** | **5.1** | **1.9** |
| Rows (Nifty 500, Balanced) | 36 | 46 |

The R:R gap is why "longest" is the default, and it is not obvious: the stop is set from
the recent swing low and ATR, *not* the base low, so a deeper base does **not** widen your
stop — but it does raise the measured-move target. A tight 15-bar base gives you a small
target against the same ~5% risk.

Use **Tightest recent base** when you specifically want short continuation patterns and
intend to trail rather than target.

---

## 8. The two buttons

| Button | What it does |
|---|---|
| **▶ Run scan** | Loads the universe, loads prices (from today's disk cache if present), computes features, assesses the regime, runs all three scanners |
| **⟳ Re-download prices (slow)** | Same, but forces a fresh download of prices, index data *and* the constituent list, ignoring all caches. Use it after the market closes to pick up the day's bar, or if data looks stale or wrong. |

Between runs, changing any sidebar control re-applies the rules automatically — you do
not need to press Run again.

---

## 9. Settings that exist only in `core/config.py`

Not exposed in the UI, but editable — every one is a named field on the `Settings`
dataclass, and changing the default there changes it everywhere.

| Field | Default | Meaning |
|---|---|---|
| `min_bars` | 250 | Minimum history to analyse a symbol at all |
| `pb_max_base_len` | 120 | Longest consolidation window considered |
| `pb_max_tightness` | 3.0 | Closing-range tightness target (%) for the "closes are tight" score |
| `pb_pivot_tolerance` | 2.0 | % band around the level within which a swing high counts as a "touch" |
| `bo_min_close_above_pivot` | 0.5 | % clearance required to count as a break |
| `bo_min_close_range_pos` | 0.60 | Close position in the breakout bar's range before the weak-close warning |
| `bo_max_atr_extension` | 2.5 | ATRs above the 20-EMA before the stretched warning |
| `bo_max_rsi` | 85 | RSI above which climax risk is flagged |
| `bo_max_distribution_days` | 3 | Distribution days in 10 that trigger the post-breakout warning |
| `wk_distribution_window` | 15 | Lookback for distribution-day counting |
| `wk_divergence_lookback` | 40 | Bars searched for RSI/OBV divergence |
| `wk_death_cross_gap` | 2.0 | % SMA50–SMA200 gap that counts as death-cross risk |
| `wk_parabolic_move` | 25.0 | 10-day % gain that counts as parabolic |
| `wk_parabolic_atr` | 3.0 | ATRs above the 20-EMA for exhaustion |
| `wk_updown_vol_ratio` | 0.90 | Up/down volume ratio below which down days dominate |
| `breadth_riskon` / `breadth_riskoff` | 55 / 35 | Breadth thresholds for the regime |

Rule *weights* live in `core/rules.py`, not here — see `DEVELOPING.md`.
