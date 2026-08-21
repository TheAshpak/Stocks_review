"""Statistics for the backtest: rank correlation, quantile tables, non-negative ridge.

Hand-rolled on numpy so the project keeps its light dependency footprint (no scipy /
sklearn), consistent with the decision not to depend on TA-Lib.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ correlation
def _rank(a: np.ndarray) -> np.ndarray:
    """Average ranks, ties shared (the definition Spearman needs)."""
    return pd.Series(a).rank(method="average").to_numpy()


def spearman(x, y) -> float:
    """Rank correlation. NaNs in either series drop the pair."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 10:
        return float("nan")
    xr, yr = _rank(x[m]), _rank(y[m])
    if xr.std() == 0 or yr.std() == 0:
        return float("nan")
    return float(np.corrcoef(xr, yr)[0, 1])


def spearman_ci(x, y, n_boot: int = 400, seed: int = 7) -> tuple:
    """Bootstrap 90% interval for the rank correlation.

    Reported because a single IC on a few thousand overlapping events looks far more
    precise than it is.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 30:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        vals[b] = spearman(x[idx], y[idx])
    vals = vals[np.isfinite(vals)]
    if len(vals) < 20:
        return (float("nan"), float("nan"))
    return (float(np.percentile(vals, 5)), float(np.percentile(vals, 95)))


# ------------------------------------------------------------------ bucket tables
def quantile_table(score, outcome, q: int = 5, labels=None) -> pd.DataFrame:
    """Mean/median outcome and hit rate by score bucket - the readable version of an IC."""
    df = pd.DataFrame({"score": np.asarray(score, dtype=float),
                       "outcome": np.asarray(outcome, dtype=float)}).dropna()
    if len(df) < q * 5:
        return pd.DataFrame()
    try:
        df["bucket"] = pd.qcut(df["score"], q, labels=labels, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    g = df.groupby("bucket", observed=True)["outcome"]
    out = pd.DataFrame({
        "n": g.size(),
        "mean": g.mean().round(3),
        "median": g.median().round(3),
        "win %": (g.apply(lambda s: (s > 0).mean() * 100)).round(1),
        "score lo": df.groupby("bucket", observed=True)["score"].min().round(1),
        "score hi": df.groupby("bucket", observed=True)["score"].max().round(1),
    })
    return out.reset_index()


def tercile_spread(credit, outcome) -> float:
    """Mean outcome of the top third minus the bottom third of a factor's credit.

    More intuitive than a correlation for a factor whose credit clusters at 0 and 1.
    """
    c = np.asarray(credit, dtype=float)
    o = np.asarray(outcome, dtype=float)
    m = np.isfinite(c) & np.isfinite(o)
    c, o = c[m], o[m]
    if len(c) < 60:
        return float("nan")
    lo, hi = np.percentile(c, 33.3), np.percentile(c, 66.7)
    if hi <= lo:                      # degenerate (constant credit)
        return float("nan")
    top, bot = o[c >= hi], o[c <= lo]
    if len(top) < 15 or len(bot) < 15:
        return float("nan")
    return float(top.mean() - bot.mean())


# ------------------------------------------------------------------ non-negative ridge
def nn_ridge(X: np.ndarray, y: np.ndarray, alpha: float = 1.0,
             iters: int = 3000) -> np.ndarray:
    """Minimise ||Xw - y||^2/n + alpha||w||^2 subject to w >= 0.

    Projected gradient descent with a Lipschitz step. Non-negativity matters: a factor
    the app presents as bullish must not be given a negative weight, or the score stops
    meaning what the UI claims it means. Columns and target are centred, so the
    intercept is implicit.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, p = X.shape
    if n < p * 5:
        return np.full(p, np.nan)

    Xc = X - X.mean(axis=0, keepdims=True)
    yc = y - y.mean()
    sd = Xc.std(axis=0)
    sd[sd == 0] = 1.0
    Xs = Xc / sd                      # standardised so alpha penalises comparably

    # Lipschitz constant of the gradient
    smax = np.linalg.norm(Xs, 2)
    L = 2.0 * (smax ** 2 / n + alpha)
    if not np.isfinite(L) or L <= 0:
        return np.full(p, np.nan)
    step = 1.0 / L

    w = np.zeros(p)
    for _ in range(iters):
        grad = 2.0 / n * Xs.T @ (Xs @ w - yc) + 2.0 * alpha * w
        w = np.maximum(w - step * grad, 0.0)

    return w / sd                     # back to the original credit scale


def fit_weights(credits: pd.DataFrame, outcome: np.ndarray, total_weight: float,
                alpha: float = 1.0) -> dict:
    """Fit non-negative weights and rescale so they sum to the original total.

    Rescaling keeps the 0-100 score comparable to the conventional version - only the
    *relative* importance of factors changes.
    """
    cols = list(credits.columns)
    X = credits.to_numpy(dtype=float)
    y = np.asarray(outcome, dtype=float)
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    if m.sum() < max(120, len(cols) * 8):
        return {}
    w = nn_ridge(X[m], y[m], alpha=alpha)
    if not np.all(np.isfinite(w)) or w.sum() <= 0:
        return {}
    w = w / w.sum() * total_weight
    return {c: float(v) for c, v in zip(cols, w)}


def blend(conventional: dict, fitted: dict, lam: float) -> dict:
    """Shrink fitted weights toward the conventional ones. lam=0 keeps convention."""
    out = {}
    for k, v in conventional.items():
        out[k] = float((1.0 - lam) * v + lam * fitted.get(k, 0.0))
    tot_c, tot_o = sum(conventional.values()), sum(out.values())
    if tot_o > 0:
        out = {k: v / tot_o * tot_c for k, v in out.items()}
    return out


def score_from_credits(credits: pd.DataFrame, weights: dict) -> np.ndarray:
    """Recompute the 0-100 score from stored credits under an arbitrary weight set.

    This is what makes weight search cheap: credits are computed once per event, then
    any candidate weight vector is one matrix multiply away from a full rescore.
    """
    cols = [c for c in credits.columns if c in weights]
    if not cols:
        return np.full(len(credits), np.nan)
    w = np.array([weights[c] for c in cols], dtype=float)
    tot = w.sum()
    if tot <= 0:
        return np.full(len(credits), np.nan)
    return credits[cols].to_numpy(dtype=float) @ w / tot * 100.0
