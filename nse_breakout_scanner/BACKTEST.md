# Backtest — method, results, and what it changed

Roadmap item #1 from [PLAN.md](PLAN.md) was a backtest, because until one existed the
rule weights were *asserted* rather than measured. This document records the harness, the
results, and the honest verdict — including the parts that did not work.

**Headline:** the Tab 2 (confirmed breakout) score has real, stable ranking power —
IC +0.077, monotone across quintiles, positive in **10 of 10 calendar years**. The Tab 1
score does **not** rank profitability at all; it ranks *imminence*. And **fitting the
weights did not survive out-of-sample validation in either scanner**, so the conventional
weights were kept.

Four findings did survive out-of-sample testing. Two changed the code (the chase-risk
threshold tightened from 15% to 8% past the pivot; the chart-pattern scoring tilt
flattened), one validated an existing default that had until now been received wisdom
(the 1.5× volume gate — breakouts below it had *negative* expectancy out-of-sample), and
one changed what the app claims (the Tab 1 score is now labelled a readiness ranking).

---

## 1. The harness

```
backtest/events.py           walk-forward event generation + outcome labelling
backtest/stats.py            Spearman IC, bootstrap CI, quantile tables, non-negative ridge
backtest/optimize.py         conventional-weight extraction, factor report, 3-way-split fit
backtest/collect.py          build the datasets -> backtest_out/*.parquet
backtest/collect_novol.py    variant with the volume gate disabled
backtest/analyze.py          the full report; --save installs weights if they earn it
core/weights.py              runtime weight overrides (so a fitted set can be swapped in)
```

Run it:

```bash
python -m backtest.collect          # ~17 min for Nifty 500 x 10y (one-off)
python -m backtest.analyze          # seconds; add --save to install fitted weights
python -m backtest.collect_novol    # optional volume-gate experiment
```

### Data
500 Nifty 500 constituents, 10 years of daily bars (median 2,473 per symbol),
2016-08 → 2026-08. After a 260-bar warm-up this leaves ~2,200 testable sessions per name.

### What counts as an event
- **Breakout (Tab 2):** every bar that closed ≥0.5% through a base built *strictly from
  bars before it*, then scored by the production Tab 2 gates and rules. 5,847 events
  passed the gates, from 11,308 candidate dates.
- **Pre-breakout (Tab 1):** dates (sampled every 3 bars, ≥10 bars apart) where the stock
  passed the Tab 1 gates. 13,313 events, from 14,191 candidate dates.

### No-lookahead guarantees
1. Features at date *t* come from `df.iloc[:t+1]` only.
2. The base behind a breakout at *t* is rebuilt from bars `< t` — the same
   hindsight-free path the live app uses.
3. The benchmark is reindexed onto the truncated frame, so relative strength is also
   point-in-time.
4. Outcomes read only bars after *t*.
5. **The backtest calls the production `compute_features` and `rules.py` directly.** There
   is no parallel re-implementation that could drift from what the app computes.

### Labels
- `trade_R` — R multiple of the *planned* trade: entry, stop and target exactly as the app
  publishes them, simulated forward up to 25 sessions. If one bar spans both stop and
  target, the stop is assumed hit first.
- `exc5 / exc10 / exc20` — return minus the Nifty 500 over the same window.

Both matter, for different questions — see §4, which is the most important section here.

---

## 2. Realised statistics

| | Tab 2 breakouts | Tab 1 candidates |
|---|---|---|
| Events | 5,847 | 13,313 |
| Symbols | 443 | 448 |
| Mean `trade_R` | **+0.315** | +0.132 |
| Median `trade_R` | −1.000 | 0.000 |
| Win rate | 34.1% | 32.2% |
| Mean excess 20d | +1.60% | +1.06% |
| Exits | 3,674 stop · 916 target · 1,255 timeout | 3,879 stop · 1,383 target · 3,852 timeout · 4,192 never triggered |
| Trigger rate | — | 68.5% |

A 34% win rate with positive expectancy is exactly the asymmetric profile breakout
trading is supposed to have, and it matches the 40–50% figure quoted in the README closely
enough (that figure counts *any* gain; this counts hitting a measured-move target before a
2.5-ATR stop, a harder test).

## 3. Does the score rank outcomes?

**Tab 2 — yes, and stably.**

```
pooled IC (score vs trade_R) = 0.0766   (90% CI 0.0563 .. 0.0969)

quintile   n     mean R   win %
lowest    1170   0.213    28.9
2         1169   0.307    30.8
3         1169   0.328    34.0
4         1169   0.352    36.9
highest   1170   0.373    39.9
```

Monotone in both mean R and win rate, and the IC is **positive in all ten calendar years**
(range +0.038 to +0.159). Ten-for-ten is the part that matters: a curve-fitted score does
not do that.

**Tab 1 — no.**

```
pooled IC (score vs R)     = -0.0060  (90% CI -0.0194 .. 0.0081)
quintile mean R: 0.096, 0.120, 0.149, 0.124, 0.171   (win % flat at 30-34%)
IC by year: 5 of 10 positive, from -0.129 to +0.065
```

Indistinguishable from zero, and unstable year to year.

## 4. Why Tab 1 looked like it worked — and what it actually measures

Splitting the Tab 1 label apart is the single most useful thing the backtest produced:

| Target | IC vs Tab 1 score |
|---|---|
| Did it trigger at all? | **+0.063** |
| How fast did it trigger? | **−0.085** (higher score → triggers sooner) |
| R once triggered | **−0.0003** |

So the Tab 1 score is a **readiness detector, not a quality detector**. It is genuinely
good at "this base is about to give way, and soon", and carries no information about
whether the resulting breakout will pay. That is a coherent thing for a watchlist score to
be — but it is not what a user would assume from a number labelled "Score", so it is now
labelled and documented as such in the app.

### A label trap worth recording

`BO_FOLLOW` showed IC +0.138 and `BO_FRESH` −0.137 against `trade_R`, which reads as "the
app's chase-risk penalty is backwards". It is not. Both factors are driven by extension
past the pivot, and:

```
IC(extension, trade_R) = +0.138        IC(extension, exc20) = -0.001
```

The target is fixed at the pivot while the stop trails 2.5 ATR below the *entry*, so
entering further above the pivot mechanically shortens the distance to target. Win rate
duly climbs from 25% to 51% across extension buckets — while mean R does not improve and
excess return is flat. The correlation was an artifact of the plan's geometry, not
forecasting power.

**Consequence for method:** `trade_R` is the right label for judging the strategy end to
end, and the wrong label for ranking factors. Factor fitting was redone on `exc20`.

This is not a hypothetical. The harness itself was initially wired to fit on `trade_R`,
and on that label it reported *"fitted weights improve out-of-sample IC 0.057 → 0.107 —
ADOPT"* and wrote a weight file. The improvement was entirely the extension artifact: the
fit had discovered it could raise the apparent hit rate by loading weight onto factors
that reward entering late. Switching the fit to `exc20` — and only the fit; the descriptive
statistics still use `trade_R` — turned the same code's verdict into *"keep conventional"*
for both scanners. A backtest that reports an improvement is not evidence until you can
say what mechanism produced it.

## 5. Weight optimisation — and why it was rejected

Fitting used non-negative ridge (a factor the UI presents as bullish must not receive a
negative weight, or the score stops meaning what the interface claims), with weights
rescaled to the original total so scores stay comparable.

Hyper-parameters were chosen on a **three-way chronological split** — fit on the earliest
50%, select alpha/transform/shrinkage on the next 20%, and report once on the final 30%.
An earlier two-way version chose shrinkage on the same fold it reported, which would have
leaked; with a 56-point grid that leak is more than large enough to manufacture a result.

| Scanner | Validation IC (fitted) | Validation IC (conventional) | **Test IC (fitted)** | **Test IC (conventional)** |
|---|---|---|---|---|
| Breakout | 0.098 | 0.033 | **0.020** | **0.032** |
| Pre-breakout | 0.098 | 0.033 | **−0.010** | **0.002** |

The fit found large gains on validation and **lost** on the untouched fold, in both
scanners. That is the textbook non-transfer signature, and the pure fit (λ=1) won
validation in both cases — a strong hint the "gains" were period-specific noise.

**Decision: conventional weights retained.** `backtest/analyze.py --save` refuses to write
a weight file unless the test-fold IC clears the conventional set's own bootstrap
confidence interval, so this outcome is enforced in code, not just in judgement. The
override machinery (`core/weights.py`, plus a sidebar selector that appears only when a
fitted file exists) stays in place for when there is more data or a better feature set.

### Why fitting failed, concretely

Several heavily-weighted factors are near-constant *after* the gates have run, so they
carry almost no information to reweight:

| Factor | Weight | Mean credit | Share at >0.9 credit |
|---|---|---|---|
| `PB_STACK` (MA alignment) | 10 | 0.955 | 85% |
| `PB_TEMPLATE` (Minervini) | 8 | 0.925 | 64% |
| `PB_POS` (position in base) | 4 | 0.837 | 42% |
| `BO_TURN` (participation) | 4 | 0.980 | — |
| `BO_GAP` | 4 | 0.930 | — |
| `BO_MOM` | 6 | 0.920 | — |

The gates already require an intact uptrend, so asking again inside the score adds nothing
— 22 of Tab 1's 122 points (18%) go to factors that are effectively constants. This is a
**feature-design** problem, not a weighting problem, and no reweighting can fix it. It is
the most promising direction for the next iteration.

## 6. Findings tested out-of-sample

Each finding was re-checked on a 70/30 chronological split before any code changed. Note
the out-of-sample fold was a weaker tape overall (mean excess 20d +0.97% vs +1.86%), which
depresses every number in it.

### ✅ Extension beyond ~8% past the pivot is harmful — HOLDS

| Extension | In-sample mean R | Out-of-sample mean R | OOS excess 20d |
|---|---|---|---|
| 0–2% | +0.385 | +0.164 | +1.10% |
| 2–4% | +0.433 | +0.137 | +1.29% |
| 4–8% | +0.444 | +0.053 | +0.80% |
| **8–15%** | +0.157 | **−0.170** | **−1.09%** |
| **>15%** | −0.116 | **−0.149** | **−5.01%** |

Consistent and clearly negative out-of-sample. **Acted on:** the default
`bo_max_extension` moved from 15% to 8%, so the chase-risk warning and the `Extended`
status now fire where the data says they should.

### ✅ The 1.5× volume gate earns its keep — HOLDS, and strongly

This needed its own dataset: the main one only contains breakouts that already passed the
gate, so it cannot say anything about the ones the gate rejected. `collect_novol.py`
rebuilds with the gate disabled — 8,165 events instead of 5,847.

| | n | Mean R | Win % | Excess 20d |
|---|---|---|---|---|
| Below 1.5× | 2,318 | +0.251 | 26.7% | +0.89% |
| At/above 1.5× | 5,847 | **+0.315** | **34.1%** | **+1.60%** |

And the gate matters *more* in the harder recent period, which is when a filter has to
earn its place:

| Fold | Mean R below 1.5× | Mean R at/above | Lift |
|---|---|---|---|
| In-sample (2017–2024) | +0.373 | +0.391 | +0.019 |
| **Out-of-sample (2024–2026)** | **−0.013** | **+0.130** | **+0.143** |

Out-of-sample, breakouts on sub-threshold volume had **negative** expectancy (and the
below-1.0× bucket −0.144R), while gated ones stayed positive. Win rate also rises
monotonically with volume across the whole range, 24.4% → 37.8%.

**Not acted on — it is already the default** (`bo_require_volume=True`), but it is no
longer a matter of received wisdom. Note that the **Loose preset turns this gate off**,
and is now known to admit a negative-expectancy cohort.

### ⚠️ …but the volume *gradient* saturates

| Volume | In-sample excess 20d | Out-of-sample excess 20d |
|---|---|---|
| 1.5–2× | +1.20% | +0.40% |
| 2–3× | +1.46% | +1.21% |
| 3–5× | +1.99% | +1.43% |
| >5× | +2.93% | +0.83% |

`IC(volume, exc20)` within the gated set: +0.037 in-sample, **−0.015 out-of-sample**.
Returns improve up to roughly 3–5×, then flatten, and the >5× bucket is the weakest
out-of-sample — consistent with blow-off exhaustion. So volume is best read as a
**threshold to clear rather than a quantity to maximise**. `BO_RVOL` keeps its weight and
its ramp; changing it would be exactly the kind of reweighting §5 showed does not
transfer.

### ❌ The chart-pattern tilt is not supported — REVERSED

| Pattern | In-sample mean R | Out-of-sample mean R |
|---|---|---|
| Range consolidation | +0.186 | **+0.022** |
| VCP | +0.215 | −0.032 |
| Ascending triangle | +0.144 | +0.012 |
| Bull flag | +0.108 | −0.031 |
| Flat base | +0.149 | −0.097 |

Bull flag and flat base underperform plain range consolidation in **both** folds, yet the
app scored them 0.75–0.80 against range's 0.25. **Acted on:** the pattern credits were
flattened to near-neutral, removing an unsupported tilt rather than adding a new claim.
The pattern name is still shown — it is descriptive, not predictive.

### The gates themselves carry the edge
Mean excess 20-day return is +1.60% for gated breakouts and +1.06% for gated pre-breakout
candidates. Combined with §3 and §5, the picture is that **most of this tool's value is in
its gates, and comparatively little in its scoring** — which is worth knowing, and is not
what the design assumed.

## 7. Limitations — read before trusting any number here

- **Survivorship bias.** The universe is *today's* Nifty 500 over ten years. Names that
  were delisted or dropped from the index are absent, and current members are there partly
  because they did well. This inflates the absolute figures (mean R, excess returns)
  materially. It affects *cross-sectional ranking* — the ICs, which is what the weight work
  rests on — far less, because the bias applies to the whole cohort rather than to the
  high-score tail specifically. Absolute numbers here should be read as optimistic; the
  relative conclusions are the reliable part.
- **Overlapping events.** Events cluster in time and share market moves, so a pooled IC
  looks more precise than it is. This is why per-year ICs and bootstrap intervals are
  reported rather than a single number.
- **No costs.** No brokerage, STT, slippage or impact. A stop is assumed to fill at the
  stop price, which on a gap-down it will not.
- **One market, one decade.** 2016–2026 in India is largely a bull regime with two sharp
  corrections. Anything fitted here is fitted to that.
- **Daily bars only.** Intraday stop/target sequencing within a bar is unknowable, hence
  the pessimistic stop-first convention.
- **The pre-breakout sample is not exhaustive** — dates were sampled every 3 bars, ≥10
  apart, so a candidate coiling for months contributes several events rather than one per
  session.

## 8. What to do next

Ordered by expected value, informed by the above:

1. **Fix the feature set, not the weights.** Replace the near-constant factors (§5) with
   ones that actually vary after gating. That is where the ranking power has to come from.
2. **Score Tab 1 on trigger probability**, which it demonstrably predicts, and stop
   implying it forecasts profit. Fit that label directly — it is far less noisy than R.
3. **Rebuild the trade plan.** The measured-move target is geometrically unsound for
   extended entries (§4) and produced 8 degenerate plans with the target below entry. A
   risk-multiple target, or a pure trailing exit, would be measurable and honest.
4. **Test the remaining gates individually**, the way the volume gate was tested in §6 —
   rebuild with one gate disabled and compare the cohort it rejects. The SMA200
   requirement and the 25%-off-52-week-high limit are the two most restrictive and the
   two most worth checking. A gate that cannot be shown to add value is only costing you
   candidates.
5. **Add costs** and re-check that the expectancy survives them.
6. **Point-in-time index membership** to remove survivorship bias — the only fix for the
   absolute-level distortion.

## 9. Reproducing

```bash
python -m backtest.collect        # writes backtest_out/events_*.parquet
python -m backtest.analyze        # prints everything in §2-§5
```

The parquet files carry one row per event with the score, every factor's credit, the trade
plan and all labels — so new hypotheses can be tested in seconds without rescanning.
`--save` writes `fitted_weights.json` only when the fit earns it; when a file exists, a
**Rule weights** selector appears in the app sidebar to switch between conventional and
fitted.

---

## 10. Capital-level check: ₹1,000 on a 5-stock basket since 2010

Per-trade expectancy says nothing about what an account does, so
`backtest/run_basket.py` walks the calendar day by day with real position sizing,
concurrency limits, costs and mark-to-market. Basket chosen by rule, not by hand: the
highest-turnover name in each NSE cap bucket with clean history back to 2009 and no
repeated industry.

| Symbol | Bucket | Industry |
|---|---|---|
| HDFCBANK | Large cap | Financial Services |
| RELIANCE | Large cap | Oil, Gas & Consumable Fuels |
| ASHOKLEY | Mid cap | Capital Goods |
| AUROPHARMA | Mid cap | Healthcare |
| KEC | Small cap | Construction |

143 signals, Mar 2010 → Aug 2026. ₹1,000 start, 2% risk per trade, max 3 concurrent
positions, 40% position cap, 0.4% round-trip costs.

| Scenario | Trades | Final | CAGR | Max DD |
|---|---|---|---|---|
| All years | 122 | **₹1,303** | 1.62% | −17.8% |
| Excl. COVID crash + recovery (Feb–Dec 2020) | 114 | ₹1,255 | 1.39% | −17.8% |
| Excl. all of 2020–2021 | 103 | ₹1,151 | 0.86% | −18.3% |

**Against the benchmarks it is not close:**

| | Final | CAGR | Max DD |
|---|---|---|---|
| Strategy | ₹1,303 | 1.6% | −17.8% |
| **Equal-weight buy & hold, same 5 stocks** | **₹11,594** | **15.9%** | −49.9% |
| Nifty 500 buy & hold | ₹5,383 | 10.7% | −38.3% |
| Nifty 50 buy & hold | ₹4,631 | 9.7% | −38.4% |

Excluding COVID does not rescue it — it makes it slightly worse, because 2021 was one of
the strategy's better years (+12.8%).

### Why, arithmetically

- **Only 33% of the time invested.** The other two-thirds sit in cash while a basket
  compounding at 15.9% runs away.
- **The edge is real but small in rupees:** +0.228R per trade × 2% risk = +0.46% of equity
  per trade × 7.4 trades/year ≈ **+3.4%/year gross**, before costs.
- **Costs eat a fifth of it:** 122 trades × 0.4% on ~40% positions ≈ 19.5% cumulative.
- **The exit truncates the winners.** Only 13 of 122 trades reached the measured-move
  target; 71 stopped out and 38 timed out at 25 days. A 25-day cap cannot capture the
  multi-year compounding that makes holding these names work.

### Nothing in the parameter space fixes it

| Change | Best result |
|---|---|
| Risk/trade 2% → 30% | no change (the 40% position cap binds) |
| Position cap 40% → 80% | ₹1,488, CAGR 2.4%, DD −32% |
| Drop the weak small cap (KEC) | ₹1,440, CAGR 2.2% |
| Zero costs | ₹1,623, CAGR 3.0% |
| **Hold limit 25 → 60 days** | **₹2,005, CAGR 4.3%** (best found) |
| Hold limit 120–500 days | worse again (₹1,048–1,286) |

Also verified scale-invariant: whole-shares-only at ₹1,000 gives 1.32× (53 signals
unaffordable), at ₹1 lakh 1.38×, at ₹10 lakh 1.30× — so this is the strategy, not the
capital.

### What it means

The entry signal has positive expectancy (profit factor 1.38, +0.23R) — it is a
**legitimate screener**. But the *packaged trade plan* around it destroys compounding, and
on a basket of quality names that compounded at 15.9%, a system in the market a third of
the time with 25-day holds cannot win. The honest conclusion is that this tool should be
used to **time entries into positions you intend to hold**, not as a complete mechanical
system — and that the trade-plan redesign in §8 item 3 is the highest-value fix in the
whole roadmap.

**Caveats:** 5 stocks and 122 trades is statistically thin — treat this as mechanics, not
proof. All five are *current* index members, so survivorship flatters the buy-and-hold
comparison too (arguably more than it flatters the strategy).

---

## 11. Detection recall: how many real breakouts did we actually catch?

Everything above judges the signals the scanner *produced*. This section asks the harder
question — **what did it never see?** `backtest/recall.py` builds a ground-truth set of
breakouts using a definition that does not touch the app's own base detector, then pushes
each one through the real pipeline and records the exact stage at which it was lost.

Ground truth: the close makes a new 60-bar high, the prior 60 bars were range-bound
(≤30% range), deduplicated to one event per 10 sessions. Same 5-stock basket, 2010–2026.

### The definition of "a new high" matters enormously

| Ground truth | Events | Caught | Recall | Recall on breakouts that worked |
|---|---|---|---|---|
| close > highest **close** of prior 60 bars | 433 | 58 | **13.4%** | 13.0% |
| close > highest **intraday high** of prior 60 bars | 317 | 99 | **31.2%** | 33.6% |

The first row is the wrong comparison, and it was my first attempt. A resistance level is
drawn across the *highs*, so the app requires a close above the prior intraday high; a
"new closing high" is typically ~1% below that and is simply not a level break yet. That
single definitional gap accounts for most of the apparent shortfall. **The like-for-like
recall is 31%, not 13%.**

### Where the other 69% went — funnel on the like-for-like set (n=317)

| Stage lost at | n | % | of which worked | mean forward move |
|---|---|---|---|---|
| **Caught** | 99 | 31.2% | 42.4% | +11.6% |
| Cleared pivot by too little | 156 | 49.2% | 32.1% | +9.2% |
| Gate: breakout volume | 54 | 17.0% | 50.0% | +12.0% |
| Gate: turnover | 5 | 1.6% | 60.0% | +25.3% |
| Gate: trend structure / avg volume | 2 | 0.6% | 100% | +27% |
| No base detected | 1 | 0.3% | 100% | +24.0% |

Almost nothing is lost to accident. The base detector failed exactly **once in 317**, and
the 10-bar dedup suppressed **zero**. The misses are two deliberate design choices:

**1. We track a longer level than 60 days (49% of misses).** `pb_max_base_len` is 120, so
the pivot is often a 4–6 month high that price has not yet reached even while it clears
its 60-day high. Confirmed by shortening the horizon:

| App max base length | Recall | Recall on worked | Lost to level mismatch |
|---|---|---|---|
| 120 (default) | 31.2% | 33.6% | 156 |
| 90 | 33.1% | 33.6% | 141 |
| 60 | **39.1%** | **41.6%** | 104 |

This is the same trade-off measured in §6 of the base-selector A/B: longer levels mean
fewer, higher-conviction signals with better geometry. The recall cost is now quantified —
about 8 percentage points of recall for the 120 vs 60 horizon.

**2. The volume gate (17% of misses).** Deliberate, and the one genuinely open question
here: 50% of the breakouts it rejected went on to advance ≥10%, a *higher* rate than the
42.4% of the ones we caught. That does not contradict the §6 finding that sub-1.5×
breakouts have negative mean R out-of-sample — "advanced 10% at some point within 40
sessions" ignores the path, and a low-volume breakout can reach +10% while still stopping
you out first. But the two metrics disagree, and that is worth resolving properly rather
than assuming the gate is free.

### Is the filtering selective, or just thinning?

On the closing-high ground truth, recall on breakouts that worked (13.0%) was
indistinguishable from recall on those that fizzled (13.7%) — pure thinning. On the
like-for-like set it does discriminate, but weakly: caught breakouts worked 42.4% of the
time versus 32.1% for those lost to the level test. So the level discipline adds real
selectivity; it is not merely reducing the count.

### What this means

The scanner sees roughly **one in three** genuine 60-day-level breakouts, and the ones it
sees are meaningfully better than the ones it drops. It is a *high-conviction, low-recall*
screen by construction. If the goal is to miss less, the single highest-leverage knob is
`pb_max_base_len` (120 → 60 buys ~8 points of recall at the cost of shorter, less
significant levels), not the gates — and certainly not the base detector, which failed
once in 317 attempts.
