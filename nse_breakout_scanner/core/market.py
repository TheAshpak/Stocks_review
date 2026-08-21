"""Market regime and breadth.

Breakout failure rates rise sharply when the index itself is under its own moving
averages and participation is narrowing. The regime is therefore computed once per
scan and used to scale every breakout score, with the reasoning shown in the UI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as D
from . import indicators as I
from . import universe as U


def breadth(feats: dict) -> dict:
    """Participation stats across the scanned universe."""
    n = len(feats)
    if n == 0:
        return {"n": 0, "above_sma50": float("nan"), "above_sma200": float("nan"),
                "advancing": float("nan"), "at_52w_high": float("nan")}
    return {
        "n": n,
        "above_sma50": 100.0 * sum(1 for f in feats.values() if f["above_sma50"]) / n,
        "above_sma200": 100.0 * sum(1 for f in feats.values() if f["above_sma200"]) / n,
        "advancing": 100.0 * sum(1 for f in feats.values()
                                 if np.isfinite(f["chg_pct"]) and f["chg_pct"] > 0) / n,
        "at_52w_high": 100.0 * sum(1 for f in feats.values() if f["at_52w_high"]) / n,
    }


def index_state(df: pd.DataFrame) -> dict:
    """Where an index sits relative to its own moving averages."""
    out = {"close": float("nan"), "sma20": float("nan"), "sma50": float("nan"),
           "sma200": float("nan"), "above20": False, "above50": False,
           "above200": False, "chg_pct": float("nan")}
    if df is None or len(df) < 210:
        return out
    c = df["Close"]
    out["close"] = float(c.iloc[-1])
    out["sma20"] = float(I.sma(c, 20).iloc[-1])
    out["sma50"] = float(I.sma(c, 50).iloc[-1])
    out["sma200"] = float(I.sma(c, 200).iloc[-1])
    out["above20"] = out["close"] > out["sma20"]
    out["above50"] = out["close"] > out["sma50"]
    out["above200"] = out["close"] > out["sma200"]
    out["chg_pct"] = float((c.iloc[-1] / c.iloc[-2] - 1) * 100.0) if len(c) > 1 else float("nan")
    return out


def assess(feats: dict, settings, refresh: bool = False) -> dict:
    """Return the market-regime verdict plus the evidence behind it."""
    nifty = D.load_index(U.INDEX_NIFTY50, refresh=refresh)
    vix_df = D.load_index(U.INDEX_VIX, refresh=refresh)
    idx = index_state(nifty)
    br = breadth(feats)

    vix = float(vix_df["Close"].iloc[-1]) if len(vix_df) else float("nan")
    vix_chg = (float(vix_df["Close"].iloc[-1] / vix_df["Close"].iloc[-6] - 1) * 100.0
               if len(vix_df) > 6 else float("nan"))

    pts = 0.0
    ev: list[str] = []

    for key, label, w in (("above20", "20-DMA", 1.0), ("above50", "50-DMA", 1.0),
                          ("above200", "200-DMA", 1.0)):
        if idx[key]:
            pts += w
            ev.append(f"Nifty 50 above its {label}")
        else:
            ev.append(f"Nifty 50 **below** its {label}")

    if np.isfinite(br["above_sma50"]):
        if br["above_sma50"] >= settings.breadth_riskon:
            pts += 1.0
            ev.append(f"broad participation: {br['above_sma50']:.0f}% of the universe "
                      f"above its 50-DMA")
        elif br["above_sma50"] <= settings.breadth_riskoff:
            pts -= 1.0
            ev.append(f"narrow participation: only {br['above_sma50']:.0f}% above "
                      f"its 50-DMA")
        else:
            ev.append(f"mixed participation: {br['above_sma50']:.0f}% above its 50-DMA")

    if np.isfinite(vix):
        if vix < 15:
            pts += 0.5
            ev.append(f"India VIX calm at {vix:.1f}")
        elif vix > 20:
            pts -= 1.0
            ev.append(f"India VIX elevated at {vix:.1f}")
        else:
            ev.append(f"India VIX neutral at {vix:.1f}")

    if pts >= 3.0:
        state, mult = "Risk-On", 1.05
    elif pts <= 1.0:
        state, mult = "Risk-Off", 0.85
    else:
        state, mult = "Neutral", 1.0

    if not settings.regime_scales_score:
        mult = 1.0

    return {"state": state, "multiplier": mult, "points": pts, "evidence": ev,
            "index": idx, "breadth": br, "vix": vix, "vix_chg": vix_chg,
            "note": {
                "Risk-On": "Breakouts have tailwinds - full position sizing is defensible.",
                "Neutral": "Mixed tape - take only the highest-grade setups and size down.",
                "Risk-Off": "Breakout failure rates are elevated. Scores are cut 15%; "
                            "consider standing aside.",
            }[state]}
