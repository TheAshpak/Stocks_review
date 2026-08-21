"""Detection recall: of all the breakouts that actually happened, how many did we flag?

The event study asks "were the signals we produced any good?". This asks the opposite and
more uncomfortable question: **what did we never see at all?**

Ground truth is deliberately defined WITHOUT the app's own base detector, so it cannot
flatter itself. A ground-truth breakout is a bar where:
  * the close is a new N-day closing high (default 60),
  * the preceding N bars were range-bound (range <= max_range, default 30%), so this is a
    breakout out of a range rather than one more day of an established vertical run,
  * and it is the first such bar in `dedup` sessions.

Each ground-truth bar is then pushed through the real pipeline and we record the exact
stage at which it dropped out. Every bar ends up in exactly one bucket, so the funnel
adds up.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core import features as F
from core import indicators as I
from core import rules as R
from core import structure as S


@dataclass
class RecallConfig:
    lookback: int = 60          # window defining "new high" and "was range-bound"
    max_range: float = 30.0     # % range over the lookback to count as range-bound
    dedup: int = 10             # min bars between ground-truth breakouts
    warmup: int = 260
    win_horizon: int = 40       # bars over which we judge whether the breakout "worked"
    win_threshold: float = 10.0  # % advance that counts as a breakout that went somewhere
    window: int = 340           # bars handed to detect_base
    # Which definition of "a new high" counts as a breakout:
    #   "close" - close exceeds the highest CLOSE of the lookback (a common screen)
    #   "high"  - close exceeds the highest INTRADAY HIGH of the lookback (a level break,
    #             which is what a resistance line drawn across the highs actually means)
    # The two differ by the typical close-to-high gap, ~1% on these names, and that gap
    # alone accounts for most of the apparent recall shortfall - see BACKTEST.md s11.
    level: str = "close"


def ground_truth(df: pd.DataFrame, cfg: RecallConfig) -> list:
    """Breakout bars by an independent definition. Returns list of dicts."""
    cl = df["Close"].to_numpy(dtype=float)
    hi = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    n = len(df)
    out, last = [], -10 ** 9
    L = cfg.lookback
    for t in range(max(cfg.warmup, L + 1), n - 1):
        if t - last < cfg.dedup:
            continue
        ref = cl[t - L:t] if cfg.level == "close" else hi[t - L:t]
        if len(ref) < L:
            continue
        if cl[t] <= ref.max():
            continue                                    # not a new N-day high
        ph, pl = hi[t - L:t].max(), lo[t - L:t].min()
        if ph <= 0:
            continue
        rng = (ph - pl) / ph * 100.0
        if rng > cfg.max_range:
            continue                                    # already running vertically
        # did the breakout go anywhere?
        j = min(t + cfg.win_horizon, n - 1)
        fwd_max = (hi[t + 1:j + 1].max() / cl[t] - 1) * 100.0 if j > t else np.nan
        fwd_close = (cl[j] / cl[t] - 1) * 100.0
        out.append({"t": t, "date": df.index[t], "close": cl[t],
                    "prior_range_pct": rng, "fwd_max_pct": fwd_max,
                    "fwd_close_pct": fwd_close,
                    "worked": bool(np.isfinite(fwd_max) and fwd_max >= cfg.win_threshold)})
        last = t
    return out


def diagnose(df: pd.DataFrame, sym: str, bench, s, cfg: RecallConfig,
             gt: list) -> pd.DataFrame:
    """For each ground-truth breakout, find the stage at which the pipeline lost it."""
    rows = []
    volsma50 = I.sma(df["Volume"], 50)
    work = df.assign(VolSMA50=volsma50)
    last_flagged = -10 ** 9

    for g in gt:
        t = g["t"]
        rec = dict(g)
        rec["symbol"] = sym
        stage, detail = None, ""

        # --- stage 1: does the base detector see a consolidation before this bar?
        win = df.iloc[max(0, t - cfg.window):t]
        b = S.detect_base(win, s.pb_min_base_len, s.pb_max_base_len, s.pb_max_base_depth,
                          tol_pct=s.pb_pivot_tolerance, min_position=0.35,
                          select=getattr(s, "base_select", "longest"))
        if not b.valid:
            stage, detail = "1. no base detected", b.reason
        else:
            clear = (g["close"] - b.high) / b.high * 100.0
            rec["pivot"] = b.high
            rec["clear_pct"] = clear
            # --- stage 2: did it clear the pivot by the required margin?
            if clear < s.bo_min_close_above_pivot:
                stage = "2. cleared pivot by too little"
                detail = ("closed %+.2f%% vs pivot, needs %+.1f%%"
                          % (clear, s.bo_min_close_above_pivot))
            elif float(df["Close"].iloc[t - 1]) > b.high:
                stage = "3. already above the pivot earlier"
                detail = "prior close was already through the level"
            elif t - last_flagged < 10:
                stage = "4. suppressed by the 10-bar dedup"
                detail = "another breakout was flagged within 10 sessions"
            else:
                # --- stage 5: the hard gates
                f = F.compute_features(
                    df.iloc[:t + 1], sym, bench, min_bars=s.min_bars,
                    base_min_len=s.pb_min_base_len, base_max_len=s.pb_max_base_len,
                    base_max_depth=s.pb_max_base_depth, pivot_tol=s.pb_pivot_tolerance,
                    bo_lookback=2, base_select=getattr(s, "base_select", "longest"))
                if f is None:
                    stage, detail = "5. insufficient history", "fewer than min_bars"
                elif f.get("breakout") is None:
                    stage = "6. re-detection disagreed"
                    detail = "find_breakout did not confirm this bar"
                else:
                    card = R.ScoreCard(sym)
                    if not R.breakout_gates(card, f, s):
                        first = card.rejections[0]
                        stage = "7. gate: %s" % first.label
                        detail = first.detail
                    else:
                        R.breakout_signals(card, f, s)
                        R.breakout_warnings(card, f, s)
                        card.finalise(1.0)
                        rec["score"] = card.score
                        if card.score < s.bo_min_score:
                            stage = "8. score below threshold"
                            detail = "scored %.0f, needs %.0f" % (card.score, s.bo_min_score)
                        else:
                            stage, detail = "0. CAUGHT", "flagged with score %.0f" % card.score
                            last_flagged = t
        rec["stage"] = stage
        rec["detail"] = detail
        rows.append(rec)
    return pd.DataFrame(rows)
