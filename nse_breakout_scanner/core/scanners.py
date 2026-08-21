"""The three scanners.

Each one walks the feature set, applies its gates, scores what survives, attaches a
trade plan, and returns both the accepted table and the rejected table - so you can
always see what was thrown away and why.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import rules as R
from . import structure as S


# ------------------------------------------------------------------ trade plan
def _plan_prebreakout(f: dict) -> dict:
    """Entry above the pivot, stop under the last swing low, target = measured move."""
    pivot, atr = f["pivot"], f["atr"]
    entry = pivot * 1.005                     # a small buffer beats a one-tick poke
    cands = []
    if np.isfinite(f["low10"]) and np.isfinite(atr):
        cands.append(f["low10"] - 0.25 * atr)
    if np.isfinite(atr):
        cands.append(entry - 2.0 * atr)
    if np.isfinite(f["base"].low):
        cands.append(f["base"].low - 0.1 * atr if np.isfinite(atr) else f["base"].low)
    stop = max([c for c in cands if np.isfinite(c)], default=float("nan"))
    if np.isfinite(stop) and stop >= entry * 0.995:
        stop = entry - 2.0 * atr if np.isfinite(atr) else entry * 0.95
    target = S.measured_move_target(f["base"], entry)
    risk = (entry - stop) / entry * 100.0 if np.isfinite(stop) else float("nan")
    rr = ((target - entry) / (entry - stop)
          if np.isfinite(target) and np.isfinite(stop) and entry > stop else float("nan"))
    return {"entry": entry, "stop": stop, "target": target,
            "risk_pct": risk, "rr": rr}


def _plan_breakout(f: dict) -> dict:
    """Entry at market, stop back under the pivot (which should now be support)."""
    bo = f["breakout"]
    pivot, atr, close = bo["pivot"], f["atr"], f["close"]
    entry = close
    cands = [pivot * 0.98]
    if np.isfinite(atr):
        cands.append(close - 2.5 * atr)
    stop = max([c for c in cands if np.isfinite(c)], default=float("nan"))
    if np.isfinite(stop) and stop >= entry * 0.995:
        stop = entry * 0.95
    target = S.measured_move_target(bo["base"], pivot * 1.005)
    risk = (entry - stop) / entry * 100.0 if np.isfinite(stop) else float("nan")
    rr = ((target - entry) / (entry - stop)
          if np.isfinite(target) and np.isfinite(stop) and entry > stop else float("nan"))
    return {"entry": entry, "stop": stop, "target": target, "risk_pct": risk, "rr": rr,
            "trail": f["ema20"]}


def _meta(meta_df: pd.DataFrame) -> dict:
    if meta_df is None or len(meta_df) == 0:
        return {}
    return {r.symbol: (r.name, r.industry) for r in meta_df.itertuples(index=False)}


# ------------------------------------------------------------------ tab 1
def scan_pre_breakout(feats: dict, settings, regime: dict,
                      meta_df: pd.DataFrame | None = None):
    """Stocks coiling under resistance, ranked by setup quality."""
    lookup = _meta(meta_df)
    rows, cards, rejects = [], {}, []
    mult = regime.get("multiplier", 1.0)

    for sym, f in feats.items():
        card = R.ScoreCard(sym)
        if not R.pre_breakout_gates(card, f, settings):
            first = card.rejections[0] if card.rejections else None
            rejects.append({"Symbol": sym, "Close": f["close"],
                            "Failed gate": first.label if first else "unknown",
                            "Why": first.detail if first else ""})
            cards[sym] = card
            continue

        R.pre_breakout_signals(card, f, settings)
        R.pre_breakout_warnings(card, f, settings)
        card.finalise(mult)
        cards[sym] = card

        if card.score < settings.pb_min_score:
            rejects.append({"Symbol": sym, "Close": f["close"],
                            "Failed gate": "Score below threshold",
                            "Why": "scored %.0f versus the %.0f minimum"
                                   % (card.score, settings.pb_min_score)})
            continue

        plan = _plan_prebreakout(f)
        name, industry = lookup.get(sym, (sym, ""))
        rows.append({
            "Symbol": sym, "Company": name, "Industry": industry,
            "Score": round(card.score, 1), "Grade": card.grade,
            "Close": round(f["close"], 2),
            "Pivot": round(f["pivot"], 2),
            "To pivot %": round(f["dist_to_pivot_pct"], 2),
            "Pattern": f["pattern"],
            "Base bars": f["base_len"],
            "Base depth %": round(f["base_depth_pct"], 1),
            "Touches": f["base_touches"],
            "ATR compr": round(f["atr_compression"], 2) if np.isfinite(f["atr_compression"]) else None,
            "Vol dryup": round(f["vol_dryup"], 2) if np.isfinite(f["vol_dryup"]) else None,
            "RS 60d %": round(f["rs60"], 1) if np.isfinite(f["rs60"]) else None,
            "RSI": round(f["rsi"], 1),
            "Entry >": round(plan["entry"], 2),
            "Stop": round(plan["stop"], 2) if np.isfinite(plan["stop"]) else None,
            "Target": round(plan["target"], 2) if np.isfinite(plan["target"]) else None,
            "Risk %": round(plan["risk_pct"], 2) if np.isfinite(plan["risk_pct"]) else None,
            "R:R": round(plan["rr"], 2) if np.isfinite(plan["rr"]) else None,
            "Turnover cr": round(f["turnover_cr"], 1),
            "Warnings": len(card.warnings),
            "Off 52w high %": round(f["off_52w_high_pct"], 1),
        })

    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["Score", "To pivot %"], ascending=[False, True])
        df = df.reset_index(drop=True)
    return df, cards, pd.DataFrame(rejects)


# ------------------------------------------------------------------ tab 2
def scan_breakouts(feats: dict, settings, regime: dict,
                   meta_df: pd.DataFrame | None = None):
    """Confirmed breakouts still acting well, plus a separate failed-breakout table."""
    lookup = _meta(meta_df)
    rows, cards, rejects, failed = [], {}, [], []
    mult = regime.get("multiplier", 1.0)

    for sym, f in feats.items():
        card = R.ScoreCard(sym)
        bo = f.get("breakout")

        # a break that has already been given back is a warning to everyone else
        if bo is not None and f["close"] < bo["pivot"]:
            name, industry = lookup.get(sym, (sym, ""))
            failed.append({
                "Symbol": sym, "Company": name,
                "Close": round(f["close"], 2), "Pivot": round(bo["pivot"], 2),
                "Below pivot %": round((f["close"] - bo["pivot"]) / bo["pivot"] * 100.0, 2),
                "Broke out": bo["date"].strftime("%d %b"),
                "Days since": bo["days_since"],
                "BO volume x": round(bo["rvol"], 2) if np.isfinite(bo["rvol"]) else None,
                "Why it failed": ("volume never confirmed (%.2fx)" % bo["rvol"]
                                  if np.isfinite(bo["rvol"])
                                  and bo["rvol"] < settings.bo_min_breakout_volume
                                  else "closed back below the level"),
            })

        if not R.breakout_gates(card, f, settings):
            first = card.rejections[0] if card.rejections else None
            rejects.append({"Symbol": sym, "Close": f["close"],
                            "Failed gate": first.label if first else "unknown",
                            "Why": first.detail if first else ""})
            cards[sym] = card
            continue

        R.breakout_signals(card, f, settings)
        R.breakout_warnings(card, f, settings)
        card.finalise(mult)
        cards[sym] = card

        if card.score < settings.bo_min_score:
            rejects.append({"Symbol": sym, "Close": f["close"],
                            "Failed gate": "Score below threshold",
                            "Why": "scored %.0f versus the %.0f minimum"
                                   % (card.score, settings.bo_min_score)})
            continue

        plan = _plan_breakout(f)
        bo = f["breakout"]
        name, industry = lookup.get(sym, (sym, ""))
        rows.append({
            "Symbol": sym, "Company": name, "Industry": industry,
            "Score": round(card.score, 1), "Grade": card.grade,
            "Status": R.breakout_status(f, settings),
            "Close": round(f["close"], 2),
            "Pivot": round(bo["pivot"], 2),
            "Above pivot %": round((f["close"] - bo["pivot"]) / bo["pivot"] * 100.0, 2),
            "BO date": bo["date"].strftime("%d %b %Y"),
            "Days since": bo["days_since"],
            "BO volume x": round(bo["rvol"], 2) if np.isfinite(bo["rvol"]) else None,
            "BO close pos": round(bo["close_range_pos"], 2) if np.isfinite(bo["close_range_pos"]) else None,
            "Base bars": bo["base"].length,
            "Pattern": f["pattern"],
            "RS 60d %": round(f["rs60"], 1) if np.isfinite(f["rs60"]) else None,
            "RSI": round(f["rsi"], 1),
            "ADX": round(f["adx"], 1) if np.isfinite(f["adx"]) else None,
            "Entry": round(plan["entry"], 2),
            "Stop": round(plan["stop"], 2) if np.isfinite(plan["stop"]) else None,
            "Trail (EMA20)": round(plan["trail"], 2) if np.isfinite(plan["trail"]) else None,
            "Target": round(plan["target"], 2) if np.isfinite(plan["target"]) else None,
            "Risk %": round(plan["risk_pct"], 2) if np.isfinite(plan["risk_pct"]) else None,
            "R:R": round(plan["rr"], 2) if np.isfinite(plan["rr"]) else None,
            "Off 52w high %": round(f["off_52w_high_pct"], 1),
            "Turnover cr": round(f["turnover_cr"], 1),
            "Warnings": len(card.warnings),
        })

    df = pd.DataFrame(rows)
    if len(df):
        order = {"Fresh": 0, "Holding": 1, "Extended": 2, "Failed": 3}
        df["_o"] = df["Status"].map(order).fillna(9)
        df = df.sort_values(["_o", "Score"], ascending=[True, False]).drop(columns="_o")
        df = df.reset_index(drop=True)
    fdf = pd.DataFrame(failed)
    if len(fdf):
        fdf = fdf.sort_values("Below pivot %").reset_index(drop=True)
    return df, cards, pd.DataFrame(rejects), fdf


# ------------------------------------------------------------------ tab 3
WEAKENING_STAGES = ["Early warning", "Turning", "Breaking down"]


def weakening_stage(f: dict) -> str:
    """How far the deterioration has already progressed.

    'Early warning' is the valuable cohort: the trend still looks fine on the surface
    (above both the 20-EMA and 50-SMA) while divergences and distribution build
    underneath. By 'Breaking down' the damage is visible to everyone.
    """
    if not f["above_sma50"]:
        return "Breaking down"
    if not f["above_ema20"]:
        return "Turning"
    return "Early warning"


def scan_weakening(feats: dict, settings, regime: dict,
                   meta_df: pd.DataFrame | None = None):
    """Currently-bullish stocks showing early deterioration.

    The universe is restricted to names still in an uptrend on purpose: the job is to
    catch the turn while there is still profit to protect, not to list wreckage.
    """
    lookup = _meta(meta_df)
    rows, cards, skipped = [], {}, []

    for sym, f in feats.items():
        card = R.ScoreCard(sym)
        if not R.liquidity_gates(card, f, settings):
            cards[sym] = card
            continue

        still_bullish = bool(f["above_sma200"] or f["above_sma50"])
        R.gate(card, "WK_BULL", "Trend", "Currently still in an uptrend", still_bullish,
               "close %s%.2f, SMA50 %s%.2f, SMA200 %s%.2f"
               % ("₹", f["close"], "₹", f["sma50"], "₹", f["sma200"]))
        if not still_bullish:
            skipped.append({"Symbol": sym, "Close": round(f["close"], 2),
                            "Reason": "already below both the 50- and 200-day averages "
                                      "- this is a downtrend, not a turn"})
            cards[sym] = card
            continue

        risk_score, tripped = R.weakening_signals(card, f, settings)
        card.score = risk_score
        card.grade = R.severity_of(risk_score, len(tripped))
        cards[sym] = card

        if len(tripped) < settings.wk_min_signals or risk_score < settings.wk_min_risk_score:
            continue

        name, industry = lookup.get(sym, (sym, ""))
        top = sorted(tripped, key=lambda s: -s.points)[:4]
        rows.append({
            "Symbol": sym, "Company": name, "Industry": industry,
            "Risk score": round(risk_score, 1),
            "Severity": card.grade,
            "Stage": weakening_stage(f),
            "Signals": len(tripped),
            "Close": round(f["close"], 2),
            "Chg %": round(f["chg_pct"], 2) if np.isfinite(f["chg_pct"]) else None,
            "Key signals": "; ".join(s.label for s in top),
            "vs EMA20 %": round((f["close"] / f["ema20"] - 1) * 100.0, 2)
                          if np.isfinite(f["ema20"]) and f["ema20"] else None,
            "vs SMA50 %": round((f["close"] / f["sma50"] - 1) * 100.0, 2)
                          if np.isfinite(f["sma50"]) and f["sma50"] else None,
            "vs SMA200 %": round((f["close"] / f["sma200"] - 1) * 100.0, 2)
                           if np.isfinite(f["sma200"]) and f["sma200"] else None,
            "Days above EMA20": f["days_above_ema20"],
            "Dist days (15)": f["dist_days_15"],
            "RS 20d %": round(f["rs20"], 1) if np.isfinite(f["rs20"]) else None,
            "RSI": round(f["rsi"], 1),
            "Suggested stop": round(max(f["sma50"], f["low20"]), 2)
                              if np.isfinite(f["sma50"]) and np.isfinite(f["low20"]) else None,
            "Off 52w high %": round(f["off_52w_high_pct"], 1),
            "Turnover cr": round(f["turnover_cr"], 1),
        })

    df = pd.DataFrame(rows)
    if len(df):
        sev = {"Exit signal": 0, "High risk": 1, "Caution": 2, "Watch": 3}
        df["_o"] = df["Severity"].map(sev).fillna(9)
        df = df.sort_values(["_o", "Risk score"], ascending=[True, False]).drop(columns="_o")
        df = df.reset_index(drop=True)
    return df, cards, pd.DataFrame(skipped)
