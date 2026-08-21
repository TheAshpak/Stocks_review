"""Technical indicator primitives, implemented on pandas/numpy only.

No TA-Lib / pandas-ta dependency so the app installs cleanly on Windows.
All functions take/return pandas Series aligned to the input index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ moving averages
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing (used by ATR / ADX / RSI)."""
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# ------------------------------------------------------------------ volatility
def true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    return wilder(true_range(h, l, c), n)


def bollinger_bandwidth(c: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    """(upper - lower) / mid, in percent. The classic 'squeeze' measure."""
    m = sma(c, n)
    sd = c.rolling(n, min_periods=n).std(ddof=0)
    return (2.0 * k * sd) / m.replace(0, np.nan) * 100.0


def donchian(h: pd.Series, l: pd.Series, n: int = 20) -> tuple[pd.Series, pd.Series]:
    return h.rolling(n, min_periods=n).max(), l.rolling(n, min_periods=n).min()


# ------------------------------------------------------------------ momentum
def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = wilder(up, n)
    ad = wilder(dn, n)
    out = 100.0 - 100.0 / (1.0 + au / ad.replace(0, np.nan))
    out = out.where(ad > 0, 100.0)           # all-up-moves window -> 100
    return out.where(au.notna())             # keep the warm-up as NaN


def macd(c: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    line = ema(c, fast) - ema(c, slow)
    signal = line.ewm(span=sig, adjust=False, min_periods=sig).mean()
    return line, signal, line - signal


def adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14):
    up = h.diff()
    dn = -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr_n = wilder(true_range(h, l, c), n).replace(0, np.nan)
    pdi = 100.0 * wilder(plus, n) / tr_n
    mdi = 100.0 * wilder(minus, n) / tr_n
    dx = 100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx, n), pdi, mdi


def roc(c: pd.Series, n: int) -> pd.Series:
    return c.pct_change(n) * 100.0


def stochastic(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14, d: int = 3):
    hh = h.rolling(n, min_periods=n).max()
    ll = l.rolling(n, min_periods=n).min()
    k = 100.0 * (c - ll) / (hh - ll).replace(0, np.nan)
    return k, k.rolling(d, min_periods=d).mean()


# ------------------------------------------------------------------ volume
def obv(c: pd.Series, v: pd.Series) -> pd.Series:
    sign = np.sign(c.diff()).fillna(0.0)
    return (sign * v).cumsum()


def up_down_volume_ratio(c: pd.Series, v: pd.Series, n: int = 20) -> pd.Series:
    """Volume traded on up-closes divided by volume on down-closes."""
    d = c.diff()
    upv = v.where(d > 0, 0.0).rolling(n, min_periods=n).sum()
    dnv = v.where(d < 0, 0.0).rolling(n, min_periods=n).sum()
    return upv / dnv.replace(0, np.nan)


def range_position(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """Where the close sits inside the bar's range: 0 = at the low, 1 = at the high."""
    return ((c - l) / (h - l).replace(0, np.nan)).clip(0.0, 1.0)


def accumulation_days(df: pd.DataFrame, window: int = 25, vol_mult: float = 1.0,
                      pos: float = 0.75) -> int:
    """Bars closing in the top `pos` of their range on above-average volume."""
    w = df.tail(window)
    if w.empty:
        return 0
    rp = range_position(w["Open"], w["High"], w["Low"], w["Close"])
    return int(((rp >= pos) & (w["Volume"] > w["VolSMA50"] * vol_mult)).sum())


def distribution_days(df: pd.DataFrame, window: int = 25, vol_mult: float = 1.0,
                      pos: float = 0.25) -> int:
    """Bars closing in the bottom `pos` of their range on above-average volume."""
    w = df.tail(window)
    if w.empty:
        return 0
    rp = range_position(w["Open"], w["High"], w["Low"], w["Close"])
    return int(((rp <= pos) & (w["Volume"] > w["VolSMA50"] * vol_mult)).sum())


# ------------------------------------------------------------------ scalar helpers
def linreg_slope_pct(y: np.ndarray) -> float:
    """Least-squares slope over the array, expressed as % of mean per bar."""
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    if len(y) < 3:
        return float("nan")
    x = np.arange(len(y), dtype=float)
    b = np.polyfit(x, y, 1)[0]
    m = y.mean()
    return float(b / m * 100.0) if m else float("nan")


def pct_rank(series: pd.Series, window: int = 250) -> float:
    """Percentile (0-100) of the latest value within the trailing window."""
    w = series.tail(window).dropna()
    if len(w) < 20:
        return float("nan")
    last = w.iloc[-1]
    return float((w <= last).mean() * 100.0)


def nr_count(df: pd.DataFrame, window: int = 15, n: int = 7) -> int:
    """Count of NR-n bars (narrowest range of the prior n bars) in the window."""
    rng = df["High"] - df["Low"]
    is_nr = rng <= rng.rolling(n, min_periods=n).min()
    return int(is_nr.tail(window).sum())


def inside_day_count(df: pd.DataFrame, window: int = 15) -> int:
    inside = (df["High"] <= df["High"].shift(1)) & (df["Low"] >= df["Low"].shift(1))
    return int(inside.tail(window).sum())


def safe_last(s: pd.Series, default: float = float("nan")) -> float:
    try:
        v = float(s.iloc[-1])
        return v if np.isfinite(v) else default
    except Exception:
        return default
