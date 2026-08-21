"""Price-structure detection: swing pivots, the consolidation base, the breakout
pivot (resistance) level, and named chart patterns.

Everything here is deliberately explicit and inspectable - each detector returns
the numbers it used so the UI can explain *why* a stock was flagged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ swing pivots
def pivot_flags(series: pd.Series, k: int = 5, kind: str = "high") -> np.ndarray:
    """Fractal pivots: bar i is a pivot when it is the extreme of the +/-k window."""
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return out
    for i in range(k, n - k):
        w = arr[i - k:i + k + 1]
        if np.isnan(w).any():
            continue
        if kind == "high":
            if arr[i] == w.max() and int(w.argmax()) == k:
                out[i] = True
        else:
            if arr[i] == w.min() and int(w.argmin()) == k:
                out[i] = True
    return out


def recent_pivots(df: pd.DataFrame, k: int = 5, lookback: int = 160):
    """Return (pivot_highs, pivot_lows) as lists of (position, price), oldest first."""
    w = df.tail(lookback)
    hi = pivot_flags(w["High"], k, "high")
    lo = pivot_flags(w["Low"], k, "low")
    base_pos = len(df) - len(w)
    phs = [(base_pos + i, float(w["High"].iloc[i])) for i in np.flatnonzero(hi)]
    pls = [(base_pos + i, float(w["Low"].iloc[i])) for i in np.flatnonzero(lo)]
    return phs, pls


# ------------------------------------------------------------------ the base / box
@dataclass
class Base:
    """A consolidation box ending at the most recent bar."""
    length: int = 0
    high: float = float("nan")      # the breakout pivot
    low: float = float("nan")
    depth_pct: float = float("nan")
    position: float = float("nan")  # 0 = at box low, 1 = at box high
    touches: int = 0                # pivot highs clustered at the box top
    pivot_age: int = 0              # bars since the box high was printed
    tightness_pct: float = float("nan")
    contractions: list = field(default_factory=list)
    vcp: bool = False
    prior_leg_pct: float = float("nan")
    valid: bool = False
    reason: str = ""


def detect_base(df: pd.DataFrame, min_len: int = 15, max_len: int = 120,
                max_depth: float = 25.0, tol_pct: float = 2.0,
                min_position: float = 0.55, exclude_recent: int = 0,
                select: str = "longest") -> Base:
    """Find the recent window that behaves like a consolidation under resistance.

    Candidate windows are every length in [min_len, max_len]. A window qualifies when
    its depth stays inside `max_depth` **and** price currently sits in the upper
    `min_position` of it - otherwise the "base" is really just a stale high with price
    languishing mid-range, which is not a setup.

    Which qualifying window wins depends on `select`:
      "quality" - balance length against tightness. Length alone always saturates the
                  depth limit, which produces wide boxes, distant stops and poor
                  reward:risk. Tightness is weighted slightly higher than length.
      "longest" - the longest qualifying window, i.e. the oldest level still capping
                  price.

    `exclude_recent` keeps the last N bars out of the resistance calculation, so a
    fresh spike cannot define the very level it is supposedly about to break.

    Window extremes are computed with suffix-accumulate scans, so the whole search is
    O(n) rather than O(n^2) - this runs 500 times per scan.
    """
    b = Base()
    n = len(df)
    if n < min_len + 20:
        b.reason = "not enough history to define a base"
        return b

    max_len = int(min(max_len, n - 10))
    e = int(max(0, exclude_recent))
    if max_len < min_len or max_len <= e:
        b.reason = "not enough history to define a base"
        return b

    highs = df["High"].to_numpy(dtype=float)[::-1]
    lows = df["Low"].to_numpy(dtype=float)[::-1]
    close = float(df["Close"].iloc[-1])
    if not np.isfinite(close):
        b.reason = "no valid close"
        return b

    # suffix extremes: cmax[i] = highest high of the last i+1 bars
    cmin = np.minimum.accumulate(lows)
    pmax = np.maximum.accumulate(highs[e:])   # resistance, ignoring the last e bars

    chosen = None
    best_q = -1.0
    span = float(max(max_len - min_len, 1))
    for L in range(max_len, min_len - 1, -1):
        if L - 1 - e < 0 or L - 1 >= len(cmin):
            continue
        hi = float(pmax[L - 1 - e])
        lo = float(cmin[L - 1])
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= 0 or hi <= lo:
            continue
        depth = (hi - lo) / hi * 100.0
        if depth > max_depth:
            continue
        pos = (close - lo) / (hi - lo)
        if pos < min_position:
            continue
        if select == "longest":
            chosen = (L, hi, lo, depth)
            break
        q = 0.40 * ((L - min_len) / span) + 0.60 * (1.0 - depth / max_depth)
        if q > best_q:
            best_q, chosen = q, (L, hi, lo, depth)

    if chosen is None:
        b.reason = ("no window of >=%d bars is within %.0f%% deep with price in the "
                    "top %.0f%% of it" % (min_len, max_depth, (1 - min_position) * 100))
        return b

    L, hi, lo, depth = chosen
    w = df.iloc[-L:]

    b.length = L
    b.high = hi
    b.low = lo
    b.depth_pct = depth
    rng = hi - lo
    b.position = float((close - lo) / rng) if rng > 0 else float("nan")

    # how many swing highs sit within tolerance of the box top -> level quality
    wr = w.iloc[:L - e] if e else w          # the sub-window that defines resistance
    tol = hi * tol_pct / 100.0
    ph = pivot_flags(wr["High"], k=3, kind="high")
    touch_pivots = [float(wr["High"].iloc[i]) for i in np.flatnonzero(ph)
                    if float(wr["High"].iloc[i]) >= hi - tol]
    b.touches = max(1, len(touch_pivots))   # the level's own high always counts as one
    b.pivot_age = int((L - e) - 1 - int(np.argmax(wr["High"].to_numpy())) + e)

    tail = df["Close"].tail(10)
    tmean = float(tail.mean())
    b.tightness_pct = float(tail.std(ddof=0) / tmean * 100.0) if tmean else float("nan")

    # volatility contraction: three successive thirds of the base, each narrower
    thirds = np.array_split(np.arange(L), 3)
    rngs = []
    for ix in thirds:
        seg = w.iloc[ix]
        sh, sl = float(seg["High"].max()), float(seg["Low"].min())
        rngs.append((sh - sl) / sh * 100.0 if sh > 0 else float("nan"))
    b.contractions = [round(r, 2) for r in rngs]
    b.vcp = bool(len(rngs) == 3 and not any(np.isnan(rngs))
                 and rngs[0] > rngs[1] > rngs[2])

    # prior advance into the base (the "flagpole") - breakouts need a trend behind them
    pre = df.iloc[max(0, n - L - 130):n - L]
    if len(pre) >= 20:
        pre_low = float(pre["Low"].min())
        b.prior_leg_pct = (hi - pre_low) / pre_low * 100.0 if pre_low > 0 else float("nan")

    b.valid = True
    return b


# ------------------------------------------------------------------ resistance
def overhead_supply_pct(df: pd.DataFrame, pivot: float, span: float = 8.0,
                        lookback: int = 250) -> float:
    """Share of recent volume transacted in the band just above the pivot.

    Heavy volume parked overhead is trapped supply - holders waiting to exit at
    breakeven - and it is the most common reason a clean-looking breakout stalls.
    """
    w = df.tail(lookback)
    if w.empty or not np.isfinite(pivot) or pivot <= 0:
        return float("nan")
    hi = pivot * (1.0 + span / 100.0)
    typical = (w["High"] + w["Low"] + w["Close"]) / 3.0
    band = float(w["Volume"].where((typical > pivot) & (typical <= hi), 0.0).sum())
    total = float(w["Volume"].sum())
    return float(band / total * 100.0) if total > 0 else float("nan")


def higher_lows(pivot_lows: list, count: int = 3) -> bool:
    """True when the last `count` swing lows are strictly ascending."""
    pts = [p for _, p in pivot_lows][-count:]
    return len(pts) == count and all(pts[i] < pts[i + 1] for i in range(count - 1))


def lower_highs(pivot_highs: list, count: int = 2) -> bool:
    """True when the last `count` swing highs are strictly descending."""
    pts = [p for _, p in pivot_highs][-count:]
    return len(pts) == count and all(pts[i] > pts[i + 1] for i in range(count - 1))


# ------------------------------------------------------------------ named patterns
def classify_pattern(df: pd.DataFrame, base: Base, pivot_lows: list):
    """Return (primary pattern name, list of all matching pattern names)."""
    names = []
    if not base.valid:
        return "None", names

    L, depth = base.length, base.depth_pct
    asc = higher_lows(pivot_lows, 3)

    if base.vcp and L >= 20:
        names.append("VCP (contracting volatility)")
    if depth <= 10.0 and L >= 20 and base.touches >= 2:
        names.append("Darvas box")
    if depth <= 15.0 and L >= 25:
        names.append("Flat base")
    if asc and base.touches >= 2 and depth <= 25.0:
        names.append("Ascending triangle")
    if 10 <= L <= 30 and depth <= 12.0 and np.isfinite(base.prior_leg_pct) \
            and base.prior_leg_pct >= 20.0:
        names.append("Bull flag")

    # cup-with-handle: deep rounded recovery, then a shallow drift near the old high
    n = len(df)
    if n >= 160:
        cup = df.iloc[-160:]
        left = float(cup["High"].iloc[:30].max())
        bottom_idx = int(np.argmin(cup["Low"].to_numpy()))
        bottom = float(cup["Low"].iloc[bottom_idx])
        drop = (left - bottom) / left * 100.0 if left > 0 else 0.0
        recovered = float(df["Close"].iloc[-1]) >= left * 0.93
        rounded = 40 <= bottom_idx <= 120
        if drop >= 15.0 and recovered and rounded and L <= 40 and depth <= 15.0:
            names.append("Cup with handle")

    if not names:
        names.append("Range consolidation")
    return names[0], names


def measured_move_target(base: Base, entry: float) -> float:
    """Classic projection: add the base height to the breakout point."""
    if not base.valid or not np.isfinite(base.high) or not np.isfinite(base.low):
        return float("nan")
    return float(entry + (base.high - base.low))


# ------------------------------------------------------------------ breakout event
def find_breakout(df: pd.DataFrame, lookback: int = 10, min_clear: float = 0.5,
                  base_min_len: int = 15, base_max_len: int = 120,
                  max_depth: float = 25.0, select: str = "longest",
                  min_pivot_age: int = 10):
    """Locate the most recent bar that cleared a consolidation formed *before* it.

    For each candidate bar the base is rebuilt from the bars preceding it, so the
    pivot is the level a trader would actually have been watching at the time -
    not a level fitted with hindsight.
    """
    n = len(df)
    room = n - base_min_len - 25
    if room <= 0:
        return None
    lookback = int(max(1, min(lookback, room)))

    for back in range(0, lookback):
        i = n - 1 - back
        if i < base_min_len + 20:
            break
        hist = df.iloc[:i]                    # strictly before the candidate bar
        # min_position is relaxed here: the defining event is the clearance itself, so
        # a base that was mid-range the day before (gap-up break) still counts.
        b = detect_base(hist, base_min_len, base_max_len, max_depth,
                        min_position=0.35, select=select)
        if not b.valid:
            continue
        bar = df.iloc[i]
        clear = (float(bar["Close"]) - b.high) / b.high * 100.0
        if clear < min_clear:
            continue

        # The level must be ESTABLISHED before it can be broken. Without this, any
        # uptrend registers a "breakout" every time it closes above the prior window's
        # highest high - even when that high was set the previous session. The old
        # `prev_close > b.high` guard could never fire: b.high is the max High over bars
        # < i, so it is by construction >= High[i-1] >= Close[i-1].
        if b.pivot_age < min_pivot_age:
            continue

        # and today must be the session that crossed it, not a later one still above
        prev_close = float(df["Close"].iloc[i - 1])
        if prev_close > b.high * (1.0 + min_clear / 100.0):
            continue
        vol_sma = float(bar.get("VolSMA50", np.nan))
        rvol = (float(bar["Volume"]) / vol_sma
                if np.isfinite(vol_sma) and vol_sma > 0 else float("nan"))
        hl = float(bar["High"]) - float(bar["Low"])
        rp = (float(bar["Close"]) - float(bar["Low"])) / hl if hl > 0 else float("nan")
        gap = (float(bar["Open"]) - prev_close) / prev_close * 100.0 if prev_close else float("nan")
        return dict(
            index=i, days_since=back, date=df.index[i], base=b, pivot=b.high,
            clear_pct=clear, rvol=rvol, close_range_pos=rp, gap_pct=gap,
            bar_close=float(bar["Close"]), bar_volume=float(bar["Volume"]),
        )
    return None


def regression_channel(close: pd.Series, n: int = 60):
    """Linear-regression channel over the last n bars.

    Returns (fitted_last, lower_band, upper_band, slope_pct_per_bar). A close below
    the lower band after a sustained uptrend is an early trend-break tell.
    """
    y = close.tail(n).to_numpy(dtype=float)
    y = y[~np.isnan(y)]
    if len(y) < 20:
        return (float("nan"),) * 4
    x = np.arange(len(y), dtype=float)
    b, a = np.polyfit(x, y, 1)
    fit = a + b * x
    resid = y - fit
    sd = float(resid.std(ddof=0))
    last_fit = float(fit[-1])
    mean = float(y.mean())
    slope_pct = float(b / mean * 100.0) if mean else float("nan")
    return last_fit, last_fit - 2.0 * sd, last_fit + 2.0 * sd, slope_pct
