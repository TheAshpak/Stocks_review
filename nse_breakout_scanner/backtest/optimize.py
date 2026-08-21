"""Analysis and weight optimisation over the saved event datasets.

Method, and the reasoning behind it:

* **Label.** The primary target is the R multiple of the planned trade, because that is
  the decision the score is used for. Benchmark-excess forward return is reported
  alongside as a sanity check that any edge is not just market beta.

* **Walk-forward only.** Weights are fitted on the earlier fraction of events and judged
  on the later fraction, which the fit never saw. In-sample IC is reported too, purely to
  show the gap - it is not evidence of anything.

* **Shrinkage.** A free fit on a few thousand overlapping events with ~15 factors is
  noisy. The fitted vector is blended toward the conventional one, and the blend strength
  is chosen on the out-of-sample fold. If shrinkage all the way to 0 wins, the conclusion
  is that the conventional weights could not be improved - and that gets reported as the
  answer rather than buried.

* **Non-negativity.** A factor the UI presents as bullish may not receive a negative
  weight; the score would stop meaning what the interface claims.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import rules as R
from . import stats as ST

# The conventional weights, read straight out of the rule engine so this file can never
# drift from it.
def conventional_weights(kind: str) -> dict:
    """Instantiate every scored signal once and read back its literal weight."""
    f = _dummy_features(kind)
    card = R.ScoreCard("DUMMY")
    if kind == "breakout":
        R.breakout_signals(card, f, _dummy_settings())
    else:
        R.pre_breakout_signals(card, f, _dummy_settings())
    return {f"c_{s.id}": s.weight for s in card.signals if s.weight > 0}


def _dummy_settings():
    from core import config as C
    return C.preset("Balanced")


def _dummy_features(kind: str) -> dict:
    """A neutral feature dict, enough for the signal builders to run and register."""
    from core import structure as S
    base = S.Base(length=30, high=110.0, low=100.0, depth_pct=9.0, position=0.8,
                  touches=2, pivot_age=5, tightness_pct=2.0, contractions=[9, 8, 7],
                  vcp=True, prior_leg_pct=30.0, valid=True)
    f = {k: 1.0 for k in (
        "close ema10 ema20 sma50 sma100 sma150 sma200 sma50_slope sma200_slope "
        "ema20_slope golden_gap_pct high_52w low_52w off_52w_high_pct above_52w_low_pct "
        "volume volsma20 volsma50 rvol vol_dryup updown_vol obv_slope20 turnover_cr atr "
        "atr_pct atr_pct_40ago atr_compression bbw bbw_rank rsi rsi_slope macd_hist "
        "macd_hist_prev macd_line macd_signal adx di_plus di_minus adx_slope adx_10ago "
        "roc20 roc60 roc120 roc10 stoch_k rs20 rs60 rs120 mansfield_rs range_pos gap_pct "
        "chg_pct upper_wick_ratio base_len base_depth_pct base_position base_touches "
        "base_tightness_pct prior_leg_pct pivot pivot_age dist_to_pivot_pct "
        "overhead_supply_pct chan_lower chan_slope donchian_low20 low10 low20 "
        "atr_above_ema20 days_above_ema20 days_above_sma50 days_since_52w_high "
        "acc_days_25 dist_days_25 dist_days_15 dist_days_10 nr7_count inside_days"
    ).split()}
    f.update({"symbol": "DUMMY", "bars": 500, "base": base, "base_valid": True,
              "base_reason": "", "base_contractions": [9, 8, 7], "base_vcp": True,
              "pattern": "Flat base", "patterns": ["Flat base"],
              "above_ema20": True, "above_sma50": True, "above_sma200": True,
              "ma_stack": True, "at_52w_high": False, "at_all_time_high": False,
              "higher_lows": True, "lower_highs": False, "rs_line_at_high": True,
              "below_channel": False, "below_donchian20": False, "parabolic": False,
              "rsi_div_bear": False, "rsi_div_detail": "", "obv_div_bear": False,
              "obv_div_detail": "", "macd_bear_cross": False, "macd_hist_falling": False,
              "shooting_star": False, "bear_engulfing": False, "wide_red_bar": False})
    if kind == "breakout":
        f["breakout"] = {"pivot": 100.0, "days_since": 1, "rvol": 2.0,
                         "close_range_pos": 0.9, "gap_pct": 0.5, "base": base,
                         "clear_pct": 1.0, "date": pd.Timestamp("2020-01-01"),
                         "index": 400, "bar_close": 101.0, "bar_volume": 1e6}
    else:
        f["breakout"] = None
    return f


# ------------------------------------------------------------------ reporting
def describe(df: pd.DataFrame, label_col: str, name: str) -> str:
    out = [f"\n{'='*78}", f"{name}: {len(df)} events", "=" * 78]
    if df.empty:
        return "\n".join(out + ["  no events"])
    out.append("  period            : %s -> %s" % (df["date"].min().date(),
                                                   df["date"].max().date()))
    out.append("  symbols           : %d" % df["symbol"].nunique())
    y = df[label_col]
    out.append("  label (%s)  : mean %+.3f  median %+.3f  win %.1f%%"
               % (label_col, y.mean(), y.median(), (y > 0).mean() * 100))
    for h in (5, 10, 20):
        c = f"exc{h}"
        if c in df:
            out.append("  excess fwd %2dd     : mean %+.2f%%  median %+.2f%%"
                       % (h, df[c].mean(), df[c].median()))
    if "trade_exit" in df:
        mix = df["trade_exit"].value_counts()
        out.append("  exits             : " + ", ".join(f"{k} {v}" for k, v in mix.items()))
    if "triggered" in df:
        out.append("  triggered         : %.1f%%" % (df["triggered"].mean() * 100))
    return "\n".join(out)


def factor_report(df: pd.DataFrame, credit_cols: list, label_col: str) -> pd.DataFrame:
    """Univariate edge per factor: rank correlation with the outcome, and tercile spread."""
    y = df[label_col].to_numpy(dtype=float)
    rows = []
    for c in credit_cols:
        x = df[c].to_numpy(dtype=float)
        finite = np.isfinite(x)
        rows.append({
            "factor": c[2:],
            "n": int(finite.sum()),
            "credit mean": float(np.nanmean(x)) if finite.any() else np.nan,
            "IC": ST.spearman(x, y),
            "top-bot": ST.tercile_spread(x, y),
        })
    out = pd.DataFrame(rows).sort_values("IC", ascending=False)
    return out.round(4)


def yearly_ic(df: pd.DataFrame, score: np.ndarray, label_col: str) -> pd.DataFrame:
    """IC computed within each calendar year - the honest stability check.

    Events overlap in time and share market moves, so one pooled IC looks far more
    reliable than it is. A factor set that only works in one year is curve-fitted.
    """
    d = pd.DataFrame({"year": df["date"].dt.year, "score": score,
                      "y": df[label_col].to_numpy(dtype=float)})
    rows = []
    for yr, g in d.groupby("year"):
        rows.append({"year": int(yr), "n": len(g), "IC": ST.spearman(g["score"], g["y"])})
    return pd.DataFrame(rows).round(4)


# ------------------------------------------------------------------ optimisation
def _rank_norm(y: np.ndarray) -> np.ndarray:
    """Rank-transform to unit scale. Trade outcomes are bimodal (-1R or a large win),
    which a squared-error fit handles badly; ranks make the fit robust to that."""
    r = pd.Series(y).rank(method="average").to_numpy()
    r = (r - r.mean()) / (r.std() if r.std() > 0 else 1.0)
    return r


def walk_forward(df: pd.DataFrame, credit_cols: list, label_col: str, kind: str,
                 fracs=(0.5, 0.2, 0.3),
                 alphas=(0.003, 0.03, 0.3, 3.0),
                 transforms=("raw", "rank"),
                 lambdas=(0.0, 0.15, 0.3, 0.5, 0.7, 0.85, 1.0)) -> dict:
    """Three-way chronological split: fit / select / report.

    * **train** (earliest 50%) fits the weight vector at each alpha and transform;
    * **validation** (next 20%) chooses alpha, transform and shrinkage;
    * **test** (last 30%) is touched exactly once, to report.

    Selecting hyper-parameters on the same fold used to report would leak, and with a
    grid this size the leak would be large enough to manufacture an improvement out of
    nothing.
    """
    d = df.dropna(subset=[label_col]).sort_values("date").reset_index(drop=True)
    d = d.dropna(subset=credit_cols)
    n = len(d)
    if n < 600:
        return {"error": "only %d usable events - too few for a 3-way split" % n}

    n1 = int(n * fracs[0])
    n2 = n1 + int(n * fracs[1])
    tr, va, te = d.iloc[:n1], d.iloc[n1:n2], d.iloc[n2:]
    conv = conventional_weights(kind)
    conv = {k: v for k, v in conv.items() if k in credit_cols}
    total = sum(conv.values())

    res = {"n_total": n, "n_train": len(tr), "n_val": len(va), "n_test": len(te),
           "label": label_col,
           "train_period": (tr["date"].min().date(), tr["date"].max().date()),
           "val_period": (va["date"].min().date(), va["date"].max().date()),
           "test_period": (te["date"].min().date(), te["date"].max().date()),
           "conventional": conv, "total_weight": total, "grid": []}

    y_tr = tr[label_col].to_numpy(dtype=float)
    best = None
    for a in alphas:
        for tf in transforms:
            y = _rank_norm(y_tr) if tf == "rank" else y_tr
            fitted = ST.fit_weights(tr[credit_cols], y, total, alpha=a)
            if not fitted:
                continue
            for lam in lambdas:
                w = ST.blend(conv, fitted, lam)
                ic_va = ST.spearman(ST.score_from_credits(va[credit_cols], w),
                                    va[label_col].to_numpy())
                rec = {"alpha": a, "transform": tf, "lambda": lam, "IC_val": ic_va,
                       "weights": w, "fitted_raw": fitted}
                res["grid"].append(rec)
                if np.isfinite(ic_va) and (best is None or ic_va > best["IC_val"]):
                    best = rec

    ic_te_conv = ST.spearman(ST.score_from_credits(te[credit_cols], conv),
                             te[label_col].to_numpy())
    lo, hi = ST.spearman_ci(ST.score_from_credits(te[credit_cols], conv),
                            te[label_col].to_numpy())
    ic_va_conv = ST.spearman(ST.score_from_credits(va[credit_cols], conv),
                             va[label_col].to_numpy())
    res["baseline"] = {"lambda": 0.0, "weights": conv, "IC_val": ic_va_conv,
                       "IC_test": ic_te_conv}
    res["baseline_test_ci"] = (lo, hi)

    if best is None:
        res["error"] = "no candidate fit succeeded"
        return res

    best = dict(best)
    best["IC_test"] = ST.spearman(ST.score_from_credits(te[credit_cols], best["weights"]),
                                  te[label_col].to_numpy())
    res["best"] = best
    res["fitted_raw"] = best["fitted_raw"]
    res["improvement"] = best["IC_test"] - ic_te_conv
    # An "improvement" inside the baseline's own confidence interval is noise.
    res["significant"] = bool(np.isfinite(hi) and best["IC_test"] > hi
                              and best["lambda"] > 0)
    return res


def summarise(res: dict, kind: str) -> str:
    if res.get("best") is None:
        return "  " + res.get("error", "no fit")
    out = []
    out.append("  label: %s" % res["label"])
    out.append("  train %d (%s..%s) | val %d (%s..%s) | test %d (%s..%s)"
               % (res["n_train"], res["train_period"][0], res["train_period"][1],
                  res["n_val"], res["val_period"][0], res["val_period"][1],
                  res["n_test"], res["test_period"][0], res["test_period"][1]))

    grid = pd.DataFrame([{k: v for k, v in g.items()
                          if k not in ("weights", "fitted_raw")} for g in res["grid"]])
    if not grid.empty:
        top = grid.sort_values("IC_val", ascending=False).head(6)
        out.append("\n  best 6 of %d grid points, ranked on VALIDATION only:" % len(grid))
        out.append("     " + top.round(4).to_string(index=False).replace("\n", "\n     "))

    b, base = res["best"], res["baseline"]
    lo, hi = res.get("baseline_test_ci", (np.nan, np.nan))
    out.append("\n  selected: alpha %.3f, transform %s, lambda %.2f (validation IC %.4f)"
               % (b["alpha"], b["transform"], b["lambda"], b["IC_val"]))
    out.append("  conventional validation IC: %.4f" % base["IC_val"])
    out.append("\n  --- untouched test fold ---")
    out.append("  conventional weights : IC %.4f  (90%% CI %.4f .. %.4f)"
               % (base["IC_test"], lo, hi))
    out.append("  selected weights     : IC %.4f  (%+.4f vs conventional)"
               % (b["IC_test"], res["improvement"]))
    out.append("  clears the conventional CI : %s"
               % ("YES - adopt" if res["significant"] else "NO - treat as noise"))
    return "\n".join(out)


def weight_table(res: dict) -> pd.DataFrame:
    if "error" in res or res.get("best") is None:
        return pd.DataFrame()
    conv, fit, best = res["conventional"], res["fitted_raw"], res["best"]["weights"]
    rows = []
    for k in conv:
        rows.append({"factor": k[2:], "conventional": round(conv[k], 1),
                     "pure fit": round(fit.get(k, 0.0), 1),
                     "selected": round(best.get(k, 0.0), 1),
                     "change": round(best.get(k, 0.0) - conv[k], 1)})
    return pd.DataFrame(rows).sort_values("selected", ascending=False)
