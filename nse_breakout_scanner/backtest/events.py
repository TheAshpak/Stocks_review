"""Event generation and outcome labelling.

The engine walks history bar by bar and, at each candidate date, scores the stock using
**the production rule engine on a truncated price frame**. Reusing `compute_features` and
`rules.py` rather than a parallel implementation is the whole point: it guarantees the
backtest measures the thing the app actually computes.

No-lookahead guarantees:
  * features at date t are computed from `df.iloc[:t+1]` only;
  * the base behind a breakout at t is built from bars strictly before t;
  * the benchmark is reindexed onto the truncated frame, so it is also point-in-time;
  * outcomes are read only from bars after t.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core import features as F
from core import indicators as I
from core import rules as R
from core import structure as S


@dataclass
class BTConfig:
    universe: str = "Nifty 500"
    period: str = "10y"
    warmup: int = 260            # bars needed before the first event can be judged
    window: int = 340            # bars handed to detect_base while scanning
    horizons: tuple = (5, 10, 20)
    max_days: int = 25           # trade-simulation horizon
    min_gap: int = 10            # min bars between two events for the same symbol
    pb_sample_every: int = 3     # sampling cadence for pre-breakout candidates
    pb_trigger_window: int = 20  # bars allowed for a candidate to trigger
    cap_symbols: int = 0         # 0 = all
    stop_first: bool = True      # if a bar touches stop and target, assume stop


# ------------------------------------------------------------------ trade simulation
def simulate(df: pd.DataFrame, t_entry: int, entry: float, stop: float, target: float,
             max_days: int, stop_first: bool = True) -> dict:
    """Walk forward from the bar after entry until stop, target, or timeout.

    Returns the outcome in R multiples, where -1 R is exactly the planned risk. When a
    single bar spans both stop and target the stop is assumed hit first, which is the
    pessimistic convention and the only honest one on daily bars.
    """
    n = len(df)
    if not all(np.isfinite([entry, stop, target])) or entry <= stop:
        return {"R": np.nan, "bars": np.nan, "exit": "invalid"}
    risk = entry - stop
    hi = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    cl = df["Close"].to_numpy(dtype=float)

    last = min(t_entry + max_days, n - 1)
    for i in range(t_entry + 1, last + 1):
        hit_stop = lo[i] <= stop
        hit_target = hi[i] >= target
        if hit_stop and hit_target:
            if stop_first:
                return {"R": -1.0, "bars": i - t_entry, "exit": "stop (same bar as target)"}
            return {"R": (target - entry) / risk, "bars": i - t_entry, "exit": "target"}
        if hit_stop:
            return {"R": -1.0, "bars": i - t_entry, "exit": "stop"}
        if hit_target:
            return {"R": (target - entry) / risk, "bars": i - t_entry, "exit": "target"}
    if last <= t_entry:
        return {"R": np.nan, "bars": np.nan, "exit": "no forward data"}
    return {"R": (cl[last] - entry) / risk, "bars": last - t_entry, "exit": "timeout"}


def forward_returns(df: pd.DataFrame, t: int, bench_rel: pd.Series | None,
                    horizons: tuple) -> dict:
    """Raw and benchmark-excess forward returns, in percent."""
    out = {}
    cl = df["Close"].to_numpy(dtype=float)
    b = bench_rel.to_numpy(dtype=float) if bench_rel is not None else None
    for h in horizons:
        j = t + h
        if j < len(cl) and cl[t] > 0:
            r = (cl[j] / cl[t] - 1.0) * 100.0
            out[f"fwd{h}"] = r
            if b is not None and j < len(b) and np.isfinite(b[t]) and b[t] > 0:
                out[f"exc{h}"] = r - (b[j] / b[t] - 1.0) * 100.0
            else:
                out[f"exc{h}"] = np.nan
        else:
            out[f"fwd{h}"] = np.nan
            out[f"exc{h}"] = np.nan
    return out


def _credits(card: R.ScoreCard) -> dict:
    """Per-factor credit (0..1) keyed by rule id - the design matrix for weight fitting."""
    return {f"c_{sig.id}": (sig.points / sig.weight if sig.weight > 0 else np.nan)
            for sig in card.signals if sig.weight > 0}


# ------------------------------------------------------------------ candidate scans
def breakout_dates(df: pd.DataFrame, s, cfg: BTConfig) -> list:
    """Every bar that closed through a base built strictly before it."""
    cl = df["Close"].to_numpy(dtype=float)
    n = len(df)
    out, last = [], -10 ** 9
    for t in range(cfg.warmup, n - 1):
        if t - last < cfg.min_gap:
            continue
        win = df.iloc[max(0, t - cfg.window):t]           # strictly before t
        b = S.detect_base(win, s.pb_min_base_len, s.pb_max_base_len, s.pb_max_base_depth,
                          tol_pct=s.pb_pivot_tolerance, min_position=0.35,
                          select=getattr(s, "base_select", "longest"))
        if not b.valid or not np.isfinite(b.high) or b.high <= 0:
            continue
        if cl[t] < b.high * (1.0 + s.bo_min_close_above_pivot / 100.0):
            continue
        if cl[t - 1] > b.high:                            # already above earlier
            continue
        out.append(t)
        last = t
    return out


@dataclass
class Prefilter:
    """Cheap vectorised series so most candidate dates are rejected without full features."""
    close: np.ndarray
    sma200: np.ndarray
    rsi: np.ndarray
    volsma20: np.ndarray
    turnover: np.ndarray
    off52w: np.ndarray


def build_prefilter(df: pd.DataFrame) -> Prefilter:
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    return Prefilter(
        close=c.to_numpy(dtype=float),
        sma200=I.sma(c, 200).to_numpy(dtype=float),
        rsi=I.rsi(c, 14).to_numpy(dtype=float),
        volsma20=I.sma(v, 20).to_numpy(dtype=float),
        turnover=((c * v) / 1e7).rolling(20, min_periods=20).median().to_numpy(dtype=float),
        off52w=((h.rolling(250, min_periods=200).max() - c)
                / h.rolling(250, min_periods=200).max() * 100.0).to_numpy(dtype=float),
    )


def prebreakout_dates(df: pd.DataFrame, s, cfg: BTConfig, pre: Prefilter) -> list:
    """Sampled dates where the stock looked like a pre-breakout candidate.

    Sampling (every `pb_sample_every` bars) plus a cheap vectorised prefilter keeps this
    tractable; the same coiled base persists for many sessions, so dense sampling would
    mostly duplicate events anyway.
    """
    n = len(df)
    out, last = [], -10 ** 9
    for t in range(cfg.warmup, n - 1, cfg.pb_sample_every):
        if t - last < cfg.min_gap:
            continue
        c = pre.close[t]
        if not np.isfinite(c) or c < s.min_price:
            continue
        if not (np.isfinite(pre.volsma20[t]) and pre.volsma20[t] >= s.min_avg_volume):
            continue
        if not (np.isfinite(pre.turnover[t]) and pre.turnover[t] >= s.min_turnover_cr):
            continue
        if s.pb_require_above_sma200 and not (np.isfinite(pre.sma200[t]) and c > pre.sma200[t]):
            continue
        if not (np.isfinite(pre.rsi[t]) and pre.rsi[t] >= s.pb_min_rsi):
            continue
        if not (np.isfinite(pre.off52w[t]) and pre.off52w[t] <= s.pb_max_off_52w_high):
            continue

        win = df.iloc[max(0, t - cfg.window):t + 1]
        b = S.detect_base(win, s.pb_min_base_len, s.pb_max_base_len, s.pb_max_base_depth,
                          tol_pct=s.pb_pivot_tolerance, min_position=0.55,
                          exclude_recent=2, select=getattr(s, "base_select", "longest"))
        if not b.valid or not np.isfinite(b.high) or b.high <= 0:
            continue
        dist = (b.high - c) / c * 100.0
        if dist < -0.5 or dist > s.pb_max_dist_to_pivot:
            continue
        out.append(t)
        last = t
    return out


# ------------------------------------------------------------------ dataset builders
def _features_at(df: pd.DataFrame, sym: str, bench: pd.Series | None, s, t: int,
                 bo_lookback: int):
    sub = df.iloc[:t + 1]
    return F.compute_features(
        sub, sym, bench,
        min_bars=s.min_bars,
        base_min_len=s.pb_min_base_len,
        base_max_len=s.pb_max_base_len,
        base_max_depth=s.pb_max_base_depth,
        pivot_tol=s.pb_pivot_tolerance,
        bo_lookback=bo_lookback,
        base_select=getattr(s, "base_select", "longest"),
        min_pivot_age=getattr(s, "min_pivot_age", 10),
    )


def build_breakout_events(prices: dict, bench: pd.Series | None, s, cfg: BTConfig,
                          log=print) -> pd.DataFrame:
    """One row per historical breakout that passed the Tab 2 gates, with its outcome."""
    rows = []
    stats = {"symbols": 0, "dates": 0, "gated_out": 0, "no_event": 0, "scored": 0}
    syms = list(prices)
    for k, sym in enumerate(syms):
        df = prices[sym]
        if len(df) < cfg.warmup + 30:
            continue
        stats["symbols"] += 1
        brel = bench.reindex(df.index).ffill() if bench is not None else None
        for t in breakout_dates(df, s, cfg):
            stats["dates"] += 1
            f = _features_at(df, sym, bench, s, t, bo_lookback=2)
            if f is None or f.get("breakout") is None:
                stats["no_event"] += 1
                continue
            card = R.ScoreCard(sym)
            if not R.breakout_gates(card, f, s):
                stats["gated_out"] += 1
                continue
            R.breakout_signals(card, f, s)
            R.breakout_warnings(card, f, s)
            card.finalise(1.0)                     # regime handled as a covariate, not baked in
            stats["scored"] += 1

            bo = f["breakout"]
            entry = f["close"]
            atr = f["atr"]
            stop = max([x for x in (bo["pivot"] * 0.98,
                                    entry - 2.5 * atr if np.isfinite(atr) else np.nan)
                        if np.isfinite(x)], default=np.nan)
            if np.isfinite(stop) and stop >= entry * 0.995:
                stop = entry * 0.95
            target = S.measured_move_target(bo["base"], bo["pivot"] * 1.005)

            row = {"symbol": sym, "date": df.index[t], "t": t, "kind": "breakout",
                   "score": card.score, "grade": card.grade,
                   "n_warn": len(card.warnings),
                   "pivot": bo["pivot"], "entry": entry, "stop": stop, "target": target,
                   "bo_rvol": bo["rvol"], "bo_days_since": bo["days_since"],
                   "pivot_age": bo["base"].pivot_age,
                   "base_len": bo["base"].length,
                   "base_depth_pct": bo["base"].depth_pct,
                   "atr_pct": f["atr_pct"], "turnover_cr": f["turnover_cr"],
                   "above_pivot_pct": (entry - bo["pivot"]) / bo["pivot"] * 100.0,
                   "rs60": f["rs60"], "off_52w_high_pct": f["off_52w_high_pct"]}
            row.update(_credits(card))
            row.update(forward_returns(df, t, brel, cfg.horizons))
            row.update({f"trade_{k2}": v for k2, v in
                        simulate(df, t, entry, stop, target, cfg.max_days,
                                 cfg.stop_first).items()})
            rows.append(row)
        if log and (k + 1) % 50 == 0:
            log("   breakout scan %d/%d symbols, %d events scored"
                % (k + 1, len(syms), stats["scored"]))
    if log:
        log("   breakout events: %d scored from %d candidate dates "
            "(%d gated out, %d re-detect mismatch)"
            % (stats["scored"], stats["dates"], stats["gated_out"], stats["no_event"]))
    return pd.DataFrame(rows)


def build_prebreakout_events(prices: dict, bench: pd.Series | None, s, cfg: BTConfig,
                             log=print) -> pd.DataFrame:
    """One row per historical pre-breakout candidate that passed the Tab 1 gates.

    The outcome is the expectancy of putting it on a watchlist: did it trigger inside the
    trigger window, and if so what did the resulting trade return? Candidates that never
    trigger score 0 R, which is exactly the cost of watching them.
    """
    rows = []
    stats = {"dates": 0, "gated_out": 0, "scored": 0, "triggered": 0}
    syms = list(prices)
    for k, sym in enumerate(syms):
        df = prices[sym]
        if len(df) < cfg.warmup + 30:
            continue
        pre = build_prefilter(df)
        brel = bench.reindex(df.index).ffill() if bench is not None else None
        cl = df["Close"].to_numpy(dtype=float)
        for t in prebreakout_dates(df, s, cfg, pre):
            stats["dates"] += 1
            f = _features_at(df, sym, bench, s, t, bo_lookback=1)
            if f is None:
                continue
            card = R.ScoreCard(sym)
            if not R.pre_breakout_gates(card, f, s):
                stats["gated_out"] += 1
                continue
            R.pre_breakout_signals(card, f, s)
            R.pre_breakout_warnings(card, f, s)
            card.finalise(1.0)
            stats["scored"] += 1

            pivot = f["pivot"]
            plan_entry = pivot * 1.005
            atr = f["atr"]
            cands = [x for x in (f["low10"] - 0.25 * atr if np.isfinite(atr) else np.nan,
                                 plan_entry - 2.0 * atr if np.isfinite(atr) else np.nan,
                                 f["base"].low - 0.1 * atr if np.isfinite(atr) else np.nan)
                     if np.isfinite(x)]
            stop = max(cands, default=np.nan)
            if np.isfinite(stop) and stop >= plan_entry * 0.995:
                stop = plan_entry - 2.0 * atr if np.isfinite(atr) else plan_entry * 0.95
            target = S.measured_move_target(f["base"], plan_entry)

            # look forward for the trigger
            t_trig, entry_actual = None, np.nan
            end = min(t + cfg.pb_trigger_window, len(df) - 1)
            for j in range(t + 1, end + 1):
                if cl[j] >= plan_entry:
                    t_trig = j
                    entry_actual = cl[j]      # entering on the close of the trigger bar
                    break

            row = {"symbol": sym, "date": df.index[t], "t": t, "kind": "prebreakout",
                   "score": card.score, "grade": card.grade,
                   "n_warn": len(card.warnings),
                   "pivot": pivot, "entry": plan_entry, "stop": stop, "target": target,
                   "dist_to_pivot_pct": f["dist_to_pivot_pct"],
                   "base_len": f["base_len"], "base_depth_pct": f["base_depth_pct"],
                   "pattern": f["pattern"], "atr_pct": f["atr_pct"],
                   "turnover_cr": f["turnover_cr"], "rs60": f["rs60"],
                   "atr_compression": f["atr_compression"], "vol_dryup": f["vol_dryup"]}
            row.update(_credits(card))
            row.update(forward_returns(df, t, brel, cfg.horizons))

            if t_trig is None:
                row.update({"triggered": 0, "bars_to_trigger": np.nan,
                            "R_if_triggered": np.nan, "trade_exit": "never triggered",
                            "trade_bars": np.nan, "R": 0.0})
            else:
                stats["triggered"] += 1
                sim = simulate(df, t_trig, entry_actual, stop, target,
                               cfg.max_days, cfg.stop_first)
                row.update({"triggered": 1, "bars_to_trigger": t_trig - t,
                            "R_if_triggered": sim["R"], "trade_exit": sim["exit"],
                            "trade_bars": sim["bars"],
                            "R": sim["R"] if np.isfinite(sim["R"]) else np.nan})
            rows.append(row)
        if log and (k + 1) % 50 == 0:
            log("   pre-breakout scan %d/%d symbols, %d events scored"
                % (k + 1, len(syms), stats["scored"]))
    if log:
        trg = stats["triggered"] / stats["scored"] * 100 if stats["scored"] else 0
        log("   pre-breakout events: %d scored from %d candidate dates (%d gated out); "
            "%.1f%% triggered" % (stats["scored"], stats["dates"], stats["gated_out"], trg))
    return pd.DataFrame(rows)
