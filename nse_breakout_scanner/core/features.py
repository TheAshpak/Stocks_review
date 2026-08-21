"""Per-symbol feature extraction.

`compute_features` turns one OHLCV frame into a flat dict of scalars that every
rule in every scanner reads from. Computing it once per symbol keeps the three
scanners cheap and guarantees all three tabs agree about the same stock.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as I
from . import structure as S


def _f(x, default=float("nan")) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except Exception:
        return default


def bearish_divergence(price: pd.Series, ind: pd.Series, lookback: int = 40,
                       k: int = 3) -> tuple[bool, str]:
    """Price prints a higher swing high while the indicator prints a lower one."""
    p = price.tail(lookback).to_numpy(dtype=float)
    v = ind.tail(lookback).to_numpy(dtype=float)
    if len(p) < 2 * k + 3 or len(v) != len(p):
        return False, ""
    flags = S.pivot_flags(pd.Series(p), k=k, kind="high")
    idx = np.flatnonzero(flags)
    if len(idx) < 2:
        return False, ""
    i1, i2 = int(idx[-2]), int(idx[-1])
    if not all(np.isfinite([p[i1], p[i2], v[i1], v[i2]])):
        return False, ""
    if p[i2] > p[i1] and v[i2] < v[i1]:
        return True, ("price %.1f -> %.1f (higher high) but indicator %.1f -> %.1f "
                      "(lower high)" % (p[i1], p[i2], v[i1], v[i2]))
    return False, ""


def _streak_above(close: pd.Series, ref: pd.Series) -> int:
    """How many consecutive bars, counting back from the last, closed above `ref`."""
    a = (close > ref).to_numpy()
    n = 0
    for x in a[::-1]:
        if not x:
            break
        n += 1
    return n


def compute_features(df: pd.DataFrame, symbol: str, bench: pd.Series | None = None,
                     min_bars: int = 250, base_min_len: int = 15,
                     base_max_len: int = 120, base_max_depth: float = 25.0,
                     pivot_tol: float = 2.0, bo_lookback: int = 10,
                     base_select: str = "longest",
                     min_pivot_age: int = 10) -> dict | None:
    """Return the full feature dict, or None when history is too short to judge."""
    if df is None or len(df) < min_bars:
        return None

    o, h, l, c, v = (df["Open"], df["High"], df["Low"], df["Close"], df["Volume"])
    n = len(df)
    close = _f(c.iloc[-1])
    if not np.isfinite(close) or close <= 0:
        return None

    d: dict = {"symbol": symbol, "bars": n, "close": close,
               "date": df.index[-1]}

    # ---------------------------------------------------------------- moving averages
    ema10, ema20 = I.ema(c, 10), I.ema(c, 20)
    sma50, sma100 = I.sma(c, 50), I.sma(c, 100)
    sma150, sma200 = I.sma(c, 150), I.sma(c, 200)
    d["ema10"], d["ema20"] = _f(ema10.iloc[-1]), _f(ema20.iloc[-1])
    d["sma50"], d["sma100"] = _f(sma50.iloc[-1]), _f(sma100.iloc[-1])
    d["sma150"], d["sma200"] = _f(sma150.iloc[-1]), _f(sma200.iloc[-1])
    d["sma50_slope"] = I.linreg_slope_pct(sma50.tail(20).to_numpy())
    d["sma200_slope"] = I.linreg_slope_pct(sma200.tail(30).to_numpy())
    d["ema20_slope"] = I.linreg_slope_pct(ema20.tail(10).to_numpy())
    d["above_ema20"] = close > d["ema20"]
    d["above_sma50"] = close > d["sma50"]
    d["above_sma200"] = close > d["sma200"]
    d["ma_stack"] = bool(close > d["ema20"] > d["sma50"] > d["sma200"])
    d["golden_gap_pct"] = ((d["sma50"] - d["sma200"]) / d["sma200"] * 100.0
                           if np.isfinite(d["sma200"]) and d["sma200"] else float("nan"))
    d["days_above_ema20"] = _streak_above(c, ema20)
    d["days_above_sma50"] = _streak_above(c, sma50)

    # ---------------------------------------------------------------- 52-week context
    w52 = df.tail(250)
    d["high_52w"] = _f(w52["High"].max())
    d["low_52w"] = _f(w52["Low"].min())
    d["off_52w_high_pct"] = ((d["high_52w"] - close) / d["high_52w"] * 100.0
                             if d["high_52w"] else float("nan"))
    d["above_52w_low_pct"] = ((close - d["low_52w"]) / d["low_52w"] * 100.0
                              if d["low_52w"] else float("nan"))
    hi_pos = int(np.argmax(w52["High"].to_numpy()))
    d["days_since_52w_high"] = int(len(w52) - 1 - hi_pos)
    d["at_52w_high"] = close >= d["high_52w"] * 0.995
    d["at_all_time_high"] = close >= _f(df["High"].max()) * 0.995

    # ---------------------------------------------------------------- volume
    volsma10, volsma20 = I.sma(v, 10), I.sma(v, 20)
    volsma50 = I.sma(v, 50)
    d["volume"] = _f(v.iloc[-1])
    d["volsma20"], d["volsma50"] = _f(volsma20.iloc[-1]), _f(volsma50.iloc[-1])
    d["rvol"] = (d["volume"] / d["volsma50"]
                 if np.isfinite(d["volsma50"]) and d["volsma50"] > 0 else float("nan"))
    d["vol_dryup"] = (_f(volsma10.iloc[-1]) / d["volsma50"]
                      if np.isfinite(d["volsma50"]) and d["volsma50"] > 0 else float("nan"))
    d["updown_vol"] = _f(I.up_down_volume_ratio(c, v, 20).iloc[-1])
    obv = I.obv(c, v)
    d["obv_slope20"] = I.linreg_slope_pct(obv.tail(20).to_numpy())
    d["turnover_cr"] = _f(((c * v) / 1e7).tail(20).median())   # INR crore, 20d median

    work = df.assign(VolSMA50=volsma50)
    d["acc_days_25"] = I.accumulation_days(work, 25)
    d["dist_days_25"] = I.distribution_days(work, 25)
    d["dist_days_15"] = I.distribution_days(work, 15)
    d["dist_days_10"] = I.distribution_days(work, 10)

    # ---------------------------------------------------------------- volatility
    atr = I.atr(h, l, c, 14)
    d["atr"] = _f(atr.iloc[-1])
    atr_pct = atr / c * 100.0
    d["atr_pct"] = _f(atr_pct.iloc[-1])
    d["atr_pct_40ago"] = _f(atr_pct.iloc[-41]) if n > 41 else float("nan")
    d["atr_compression"] = (d["atr_pct"] / d["atr_pct_40ago"]
                            if np.isfinite(d["atr_pct_40ago"]) and d["atr_pct_40ago"] > 0
                            else float("nan"))
    bbw = I.bollinger_bandwidth(c, 20, 2.0)
    d["bbw"] = _f(bbw.iloc[-1])
    d["bbw_rank"] = I.pct_rank(bbw, 250)
    d["nr7_count"] = I.nr_count(df, 15, 7)
    d["inside_days"] = I.inside_day_count(df, 15)

    # ---------------------------------------------------------------- momentum
    rsi = I.rsi(c, 14)
    d["rsi"] = _f(rsi.iloc[-1])
    d["rsi_slope"] = I.linreg_slope_pct(rsi.tail(10).to_numpy())
    ml, sl, hist = I.macd(c)
    d["macd_hist"] = _f(hist.iloc[-1])
    d["macd_hist_prev"] = _f(hist.iloc[-2]) if n > 2 else float("nan")
    d["macd_line"], d["macd_signal"] = _f(ml.iloc[-1]), _f(sl.iloc[-1])
    d["macd_bear_cross"] = bool(np.isfinite(d["macd_line"]) and np.isfinite(d["macd_signal"])
                                and d["macd_line"] < d["macd_signal"]
                                and _f(ml.iloc[-4]) > _f(sl.iloc[-4]) if n > 4 else False)
    d["macd_hist_falling"] = bool(np.isfinite(d["macd_hist"])
                                  and np.isfinite(d["macd_hist_prev"])
                                  and d["macd_hist"] < d["macd_hist_prev"])
    adx, dip, dim = I.adx(h, l, c, 14)
    d["adx"], d["di_plus"], d["di_minus"] = (_f(adx.iloc[-1]), _f(dip.iloc[-1]),
                                             _f(dim.iloc[-1]))
    d["adx_slope"] = I.linreg_slope_pct(adx.tail(10).to_numpy())
    d["adx_10ago"] = _f(adx.iloc[-11]) if n > 11 else float("nan")
    d["roc20"], d["roc60"] = _f(I.roc(c, 20).iloc[-1]), _f(I.roc(c, 60).iloc[-1])
    d["roc120"] = _f(I.roc(c, 120).iloc[-1])
    d["roc10"] = _f(I.roc(c, 10).iloc[-1])
    k_, dd_ = I.stochastic(h, l, c)
    d["stoch_k"] = _f(k_.iloc[-1])

    # ---------------------------------------------------------------- relative strength
    d["rs20"] = d["rs60"] = d["rs120"] = float("nan")
    d["rs_line_at_high"] = False
    d["mansfield_rs"] = float("nan")
    if bench is not None and len(bench) > 20:
        b = bench.reindex(df.index).ffill()
        if b.notna().sum() > 130:
            for k in (20, 60, 120):
                br = _f(I.roc(b, k).iloc[-1])
                sr = _f(I.roc(c, k).iloc[-1])
                d[f"rs{k}"] = sr - br if np.isfinite(br) and np.isfinite(sr) else float("nan")
            rs_line = (c / b).replace([np.inf, -np.inf], np.nan).dropna()
            if len(rs_line) > 60:
                d["rs_line_at_high"] = bool(_f(rs_line.iloc[-1])
                                            >= _f(rs_line.tail(60).max()) * 0.998)
                rs_sma = I.sma(rs_line, min(200, max(50, len(rs_line) // 2)))
                if np.isfinite(_f(rs_sma.iloc[-1])) and _f(rs_sma.iloc[-1]) != 0:
                    d["mansfield_rs"] = (_f(rs_line.iloc[-1]) / _f(rs_sma.iloc[-1]) - 1) * 100.0

    # ---------------------------------------------------------------- candle / bar
    hl = _f(h.iloc[-1]) - _f(l.iloc[-1])
    d["range_pos"] = ((close - _f(l.iloc[-1])) / hl) if hl > 0 else float("nan")
    pc = _f(c.iloc[-2]) if n > 2 else float("nan")
    d["gap_pct"] = ((_f(o.iloc[-1]) - pc) / pc * 100.0) if pc else float("nan")
    d["chg_pct"] = ((close - pc) / pc * 100.0) if pc else float("nan")
    d["upper_wick_ratio"] = ((_f(h.iloc[-1]) - close) / hl) if hl > 0 else float("nan")

    # bearish reversal bars, checked over the last 3 sessions so a one-day lag
    # in running the scan does not hide the signal
    d["shooting_star"] = False
    d["bear_engulfing"] = False
    d["wide_red_bar"] = False
    rng_avg = _f((h - l).tail(20).mean())
    for j in range(1, min(4, n)):
        oj, hj, lj, cj = (_f(o.iloc[-j]), _f(h.iloc[-j]), _f(l.iloc[-j]), _f(c.iloc[-j]))
        rj = hj - lj
        if rj <= 0:
            continue
        body_top = max(oj, cj)
        if (hj - body_top) / rj > 0.55 and (cj - lj) / rj < 0.40:
            d["shooting_star"] = True
        if n > j + 1:
            op, cp = _f(o.iloc[-j - 1]), _f(c.iloc[-j - 1])
            if cp > op and cj < oj and cj < op and oj > cp:
                d["bear_engulfing"] = True
        if (cj < oj and np.isfinite(rng_avg) and rng_avg > 0 and rj > 1.6 * rng_avg
                and (cj - lj) / rj < 0.35):
            d["wide_red_bar"] = True

    # ---------------------------------------------------------------- structure
    pivot_highs, pivot_lows = S.recent_pivots(df, k=5, lookback=160)
    d["higher_lows"] = S.higher_lows(pivot_lows, 3)
    d["lower_highs"] = S.lower_highs(pivot_highs, 2)

    # exclude_recent=2 so a fresh spike cannot invent the level it is breaking
    base = S.detect_base(df, base_min_len, base_max_len, base_max_depth,
                         tol_pct=pivot_tol, min_position=0.55, exclude_recent=2,
                         select=base_select)
    d["base"] = base
    d["base_valid"] = base.valid
    d["base_reason"] = base.reason
    d["base_len"] = base.length
    d["base_depth_pct"] = base.depth_pct
    d["base_position"] = base.position
    d["base_touches"] = base.touches
    d["base_tightness_pct"] = base.tightness_pct
    d["base_contractions"] = base.contractions
    d["base_vcp"] = base.vcp
    d["prior_leg_pct"] = base.prior_leg_pct
    d["pivot"] = base.high
    d["pivot_age"] = base.pivot_age
    d["dist_to_pivot_pct"] = ((base.high - close) / close * 100.0
                              if np.isfinite(base.high) and close else float("nan"))
    d["overhead_supply_pct"] = S.overhead_supply_pct(df, base.high)
    pat, pats = S.classify_pattern(df, base, pivot_lows)
    d["pattern"], d["patterns"] = pat, pats

    fit, lo_band, hi_band, ch_slope = S.regression_channel(c, 60)
    d["chan_lower"], d["chan_slope"] = lo_band, ch_slope
    d["below_channel"] = bool(np.isfinite(lo_band) and close < lo_band)

    d["low10"] = _f(l.tail(10).min())
    d["low20"] = _f(l.tail(20).min())

    don_hi, don_lo = I.donchian(h, l, 20)
    d["donchian_low20"] = _f(don_lo.iloc[-1])
    d["below_donchian20"] = bool(np.isfinite(d["donchian_low20"])
                                 and close < d["donchian_low20"])

    # ---------------------------------------------------------------- divergences
    d["rsi_div_bear"], d["rsi_div_detail"] = bearish_divergence(c, rsi, 40)
    d["obv_div_bear"], d["obv_div_detail"] = bearish_divergence(c, obv, 40)

    # ---------------------------------------------------------------- exhaustion
    d["atr_above_ema20"] = ((close - d["ema20"]) / d["atr"]
                            if np.isfinite(d["atr"]) and d["atr"] > 0 else float("nan"))
    d["parabolic"] = bool(np.isfinite(d["roc10"]) and d["roc10"] >= 25.0)

    # ---------------------------------------------------------------- breakout event
    d["breakout"] = S.find_breakout(work, lookback=bo_lookback, min_clear=0.5,
                                    base_min_len=base_min_len,
                                    base_max_len=base_max_len,
                                    max_depth=base_max_depth,
                                    select=base_select,
                                    min_pivot_age=min_pivot_age)
    return d


def bulk_features(prices: dict, bench: pd.Series | None, settings,
                  progress_cb=None) -> tuple[dict, dict]:
    """Compute features for every symbol. Returns (features, skipped reasons)."""
    feats: dict = {}
    skipped: dict = {}
    total = max(len(prices), 1)
    for i, (sym, df) in enumerate(prices.items()):
        try:
            f = compute_features(
                df, sym, bench,
                min_bars=settings.min_bars,
                base_min_len=settings.pb_min_base_len,
                base_max_len=settings.pb_max_base_len,
                base_max_depth=settings.pb_max_base_depth,
                pivot_tol=settings.pb_pivot_tolerance,
                bo_lookback=settings.bo_lookback_days,
                base_select=getattr(settings, 'base_select', 'longest'),
                min_pivot_age=getattr(settings, 'min_pivot_age', 10),
            )
        except Exception as exc:
            skipped[sym] = f"error: {type(exc).__name__}: {exc}"
            continue
        if f is None:
            skipped[sym] = f"insufficient history (<{settings.min_bars} bars)"
        else:
            feats[sym] = f
        if progress_cb and i % 25 == 0:
            progress_cb(i / total, f"analysed {i}/{total}")
    if progress_cb:
        progress_cb(1.0, f"analysed {len(prices)}/{total}")
    return feats, skipped
