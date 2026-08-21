# Developing — how to change this safely

Read the invariants in [PLAN.md §8](PLAN.md) first. Everything below assumes them.

## Module map — where does my change go?

| I want to… | Edit |
|---|---|
| Change a threshold or add a tunable | `core/config.py` (+ a sidebar widget in `app.py`) |
| Change a rule weight | `core/rules.py` literal — but read [BACKTEST.md](BACKTEST.md) first; fitted weights failed out-of-sample once already |
| Validate a change against history | `backtest/` — `python -m backtest.collect` then `python -m backtest.analyze` |
| Change a column tooltip or number format | `core/columns.py` |
| Add an indicator | `core/indicators.py`, then expose it in `core/features.py` |
| Change how bases / pivots / patterns are found | `core/structure.py` |
| Add a number the rules can read | `core/features.py` |
| Add or reweight a rule | `core/rules.py` |
| Change table columns, sorting, or the trade plan | `core/scanners.py` |
| Change the regime formula | `core/market.py` |
| Change the chart | `core/charts.py` |
| Change layout, filters, or the reason panel | `app.py` |

The dependency order is strict and one-way:

```
config -> indicators -> structure -> features -> rules -> scanners -> app
                                        market ----^
```

Never import backwards. `features.py` must not know about rules; `rules.py` must not
recompute indicators.

## Recipe: add a scored rule to Tab 1

1. **Add the number to features** (`core/features.py`, inside `compute_features`):

```python
d["my_metric"] = _f(some_series.iloc[-1])
```

Always route through `_f()` — it converts to float and maps inf/None to NaN, which every
rule helper already handles.

2. **Add a threshold** (`core/config.py`) if the rule needs one:

```python
pb_my_threshold: float = 1.5
```

3. **Add the scored signal** (`core/rules.py`, in `pre_breakout_signals`):

```python
scored(card, "PB_MYRULE", "Volume", "My factor reads well",
       ramp(f["my_metric"], 1.0, 3.0),          # 0..1 credit
       8.0,                                      # weight
       "my metric is %.2f versus the %.2f target"
       % (f["my_metric"], s.pb_my_threshold) if fin(f["my_metric"])
       else "metric unavailable")
```

`ramp(x, at0, at1)` gives partial credit: `at0` scores nothing, `at1` scores full, and
`at0 > at1` inverts it (for metrics where lower is better). Prefer it over hard booleans —
cliff edges at thresholds cause identical stocks to score far apart.

The score denominator updates automatically. No other change is needed; the UI reads
`card.passes` / `card.misses` and renders your detail string.

4. **Verify** with the smoke test in the next section.

## Recipe: add a gate

```python
ok &= gate(card, "PB_MYGATE", "Structure", "Human-readable requirement",
           condition_bool,
           "close %s%.2f vs limit %s%.2f" % ("₹", f["close"], "₹", limit))
```

Gates return a bool and must be `&=`-accumulated so `pre_breakout_gates` returns False on
any failure. The **first** failing gate is what shows in the rejection log, so order them
cheapest-and-most-common first.

## Recipe: add a Tab 3 risk signal

```python
risk("WK_MYSIGNAL", "Momentum", "My deterioration signal", 10.0,
     bool(condition),
     "detail when it fires" if condition else "detail when healthy")
```

Provide a detail string for **both** branches — the UI shows non-triggered signals in the
"still healthy" expander, and a blank line there looks broken. Points are absolute (the
score is a capped sum, not normalised), so pick a value comparable to existing signals:
14 = severe and specific, 8–10 = standard, 4 = mild confirmation.

## Recipe: add a chart pattern

In `core/structure.py`, `classify_pattern` — append to `names` in priority order (the
first match becomes the primary label). Then add it to the credit table in the
`PB_PATTERN` rule in `core/rules.py`, or it will score the 0.3 default.

## Recipe: add a table column

1. Add the key to the row dict in `core/scanners.py` and to that tab's `cols` list in
   `app.py`.
2. **Add a tooltip in `core/columns.py`** (`HELP`), and a printf format in `FORMAT` if it
   is numeric. A column with no `HELP` entry silently renders without a tooltip.
3. Check coverage — this should print nothing:

```python
from core import columns as COL
print([c for c in df.columns if c not in COL.HELP])
```

Tooltips are rendered by `column_config()` in `app.py`, which is applied by both
`result_table()` (selectable tables) and `plain_table()` (logs, failed breakouts). Any new
`st.dataframe` call should go through one of those two, not be written raw.

## Recipe: swap the data source

Implement the same two functions in a new module and point `app.py` at it:

```python
load_prices(universe_key, symbols, period, refresh, progress_cb) -> (dict[str, DataFrame], info)
load_index(ticker, period, refresh) -> DataFrame
```

Frames need a `DatetimeIndex` ascending and columns `Open, High, Low, Close, Volume`.
`clean_frame()` in `core/data.py` is reusable for normalisation. Nothing downstream knows
where the data came from, so this is a genuinely contained change — the payoff is official
NSE data, intraday relative volume, and delivery percentage.

## Validating an analytics change against history

Any change to a weight, threshold or scoring rule should be checked against the backtest
before it ships, because the obvious-looking change frequently does not survive:

```bash
python -m backtest.collect     # once - ~17 min, writes backtest_out/events_*.parquet
python -m backtest.analyze     # seconds, re-runs the whole report
```

The saved parquet carries one row per historical event with the score, every factor's
credit and all outcome labels, so a new hypothesis is a few lines of pandas rather than a
rescan. Two rules learned the hard way (both in [BACKTEST.md](BACKTEST.md)):

- **Pick the label carefully.** `trade_R` is contaminated by the trade plan's geometry —
  entering further above the pivot mechanically shortens the distance to target, which
  made the chase-risk penalty look backwards. Use benchmark-excess return (`exc20`) to
  rank *factors*, and `trade_R` to judge the *strategy*.
- **Never select on the fold you report.** Use the three-way split in
  `optimize.walk_forward`: fit on the earliest 50%, choose hyper-parameters on the next
  20%, report once on the last 30%.

## Testing

There is no test suite; this is how the tool was actually validated, and it is enough.

**1. Module smoke test** — every file parses as UTF-8 (the source contains ₹ and the
Windows default codec is cp1252, so always pass `encoding="utf-8"`):

```bash
python -c "import ast,io,glob; [ast.parse(io.open(p,encoding='utf-8').read()) for p in ['app.py']+glob.glob('core/*.py')]; print('OK')"
```

**2. Analytics on real data** — run the pipeline outside Streamlit and eyeball the numbers.
Print base length, depth, pivot, distance, and the rule card for a few known names; a
structural bug shows up immediately as an absurd base or a stale pivot.

```python
from core import universe as U, data as D, features as F, config as C, market as M, scanners as SC
syms, meta, _ = U.get_universe("Nifty 500")
px, info = D.load_prices("Nifty 500", syms, period="2y")
bench = D.load_index(U.BENCHMARK)["Close"]
s = C.preset("Balanced")
feats, skipped = F.bulk_features(px, bench, s)
reg = M.assess(feats, s)
pb, cards, rejects = SC.scan_pre_breakout(feats, s, reg, meta)
print(len(pb), reg["state"])
for sig in cards[pb.iloc[0]["Symbol"]].passes:
    print("%5.1f/%2.0f  %-42s %s" % (sig.points, sig.weight, sig.label, sig.detail))
```

Set `PYTHONIOENCODING=utf-8` when printing to a Windows terminal.

**3. UI smoke test** — Streamlit's own harness catches every exception on every code path
without a browser:

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=900)
at.run();                                    assert not at.exception
at.sidebar.slider[0].set_value(120)          # cap the universe for speed
at.sidebar.button[0].click().run();           assert not at.exception
at.sidebar.radio[0].set_value("Strict").run() ; assert not at.exception
at.sidebar.radio[-1].set_value("Tightest recent base").run(); assert not at.exception
print([t.label for t in at.tabs])
```

Exercise both paths: a scanner-only change (preset radio) and a feature-rebuild change
(base selector radio). They take different branches in `main()`.

**4. Chart test** — figures fail at render time, not build time, so force serialisation:

```python
fig = CH.price_chart(px[sym], feats[sym], plan=SC._plan_prebreakout(feats[sym]))
fig.to_html(include_plotlyjs=False)   # raises if anything is malformed
```

## Gotchas discovered the hard way

- **`use_container_width` is deprecated** in this Streamlit version — use
  `width="stretch"`. It still works but spams warnings.
- **Windows console encoding.** Any `print` of a string containing ₹ dies with
  `UnicodeEncodeError` under cp1252. Streamlit itself is fine; only terminal scripts break.
  Use `PYTHONIOENCODING=utf-8`.
- **Long heredocs through the shell get truncated.** Write files with an editor/`Write`
  tool rather than a 300-line `cat <<EOF`.
- **pandas 3.x**: `fillna` downcasting behaviour changed and copy-on-write is default.
  Assign columns explicitly (`df = df.assign(...)`) rather than chaining in place.
- **yfinance shapes are inconsistent.** With one ticker you get flat columns; with many, a
  `MultiIndex`. `clean_frame()` handles both — always route through it.
- **Delisted/renamed symbols return empty frames** (TATAMOTORS did, post-demerger). They
  are dropped and reported in "symbols could not be analysed"; never assume every
  requested symbol comes back.
- **Adding a `Settings` field that feeds features** means adding it to `FEATURE_KEYS` in
  `app.py`, or changing it will silently score against stale features. This was a real bug.
- **`st.dataframe` selection returns positional indices**, so use `.iloc`, not `.loc` — the
  filtered frames have non-contiguous indices.
- **Widget keys must be unique across tabs.** Chart keys are namespaced as
  `chart_{kind}_{symbol}`; keep that pattern or Streamlit raises duplicate-key errors when
  the same stock appears in two tabs.

## Cache management

`data_cache/` holds per-day parquet price files, per-day index files, and universe CSVs.
It is gitignored and safe to delete wholesale — everything re-downloads. Price caches are
pruned to the newest 4 per universe automatically. A full Nifty 500 day is ~10 MB.

To force fresh data in code, pass `refresh=True` to `load_prices` / `load_index` /
`get_universe`; in the UI, press **⟳ Re-download prices**.
