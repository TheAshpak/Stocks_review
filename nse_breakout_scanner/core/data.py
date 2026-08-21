"""Price data acquisition and on-disk caching.

Daily OHLCV comes from Yahoo Finance via yfinance. Downloads are chunked and
threaded, then persisted as one long-format parquet per (universe, trading day) so
a rescan later the same day is instant.

`auto_adjust=True` is deliberate: split/bonus adjusted OHLC keeps chart structure
continuous. Unadjusted series show phantom gaps that a breakout scanner would read
as real price action.
"""
from __future__ import annotations

import glob
import hashlib
import os
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from . import universe as U

CACHE_DIR = U.CACHE_DIR
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _cache_file(universe_key: str, period: str, symbols: list[str]) -> str:
    """Cache path keyed by universe, period, trading day *and* the exact symbol set.

    The symbol hash matters: without it, a capped 100-symbol scan would write a cache
    that a later full 500-symbol scan would happily read back, silently scanning a
    subset. The date sorts before the hash so pruning stays chronological.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = universe_key.lower().replace(" ", "_")
    stamp = datetime.now().strftime("%Y%m%d")
    h = hashlib.sha1(",".join(sorted(symbols)).encode("utf-8")).hexdigest()[:8]
    return os.path.join(CACHE_DIR, f"prices_{safe}_{period}_{stamp}_{h}.parquet")


def _prune_cache(universe_key: str, keep: int = 4) -> None:
    safe = universe_key.lower().replace(" ", "_")
    files = sorted(glob.glob(os.path.join(CACHE_DIR, f"prices_{safe}_*.parquet")))
    for f in files[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise one symbol's OHLCV frame; return an empty frame if unusable."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLCV)
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in OHLCV if c in df.columns]
    if len(keep) < 5:
        return pd.DataFrame(columns=OHLCV)
    df = df[keep]
    for c in OHLCV:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = df["Volume"].fillna(0.0)
    df = df[(df["Close"] > 0) & (df["High"] >= df["Low"])]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def download_prices(symbols: list[str], period: str = "2y", chunk: int = 80,
                    progress_cb=None) -> pd.DataFrame:
    """Download daily OHLCV for NSE symbols. Returns a long-format frame.

    Columns: symbol, Date (index level), Open/High/Low/Close/Volume.
    """
    tickers = [U.to_yahoo(s) for s in symbols]
    frames: list[pd.DataFrame] = []
    total = len(tickers)
    done = 0

    for group in _chunks(tickers, chunk):
        try:
            raw = yf.download(group, period=period, interval="1d", auto_adjust=True,
                              progress=False, group_by="ticker", threads=True,
                              timeout=40)
        except Exception:
            raw = None

        if raw is not None and len(raw):
            for tk in group:
                try:
                    sub = raw[tk] if isinstance(raw.columns, pd.MultiIndex) else raw
                except KeyError:
                    continue
                sub = clean_frame(sub.dropna(how="all"))
                if sub.empty:
                    continue
                sub = sub.assign(symbol=U.from_yahoo(tk))
                frames.append(sub)

        done += len(group)
        if progress_cb:
            progress_cb(min(done / max(total, 1), 1.0),
                        f"downloaded {min(done, total)}/{total} symbols")

    if not frames:
        return pd.DataFrame(columns=["symbol"] + OHLCV)
    out = pd.concat(frames)
    out.index.name = "Date"
    return out


def load_prices(universe_key: str, symbols: list[str], period: str = "2y",
                refresh: bool = False, progress_cb=None) -> tuple[dict, dict]:
    """Return ({symbol: OHLCV frame}, info dict), using the daily parquet cache."""
    path = _cache_file(universe_key, period, symbols)
    info = {"source": "", "cached_at": "", "requested": len(symbols)}

    long_df = None
    if not refresh and os.path.exists(path):
        try:
            long_df = pd.read_parquet(path)
            info["source"] = "disk cache"
            info["cached_at"] = datetime.fromtimestamp(
                os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            long_df = None

    if long_df is None:
        long_df = download_prices(symbols, period=period, progress_cb=progress_cb)
        info["source"] = "downloaded"
        info["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if len(long_df):
            try:
                long_df.to_parquet(path)
                _prune_cache(universe_key)
            except Exception:
                pass

    out: dict[str, pd.DataFrame] = {}
    if len(long_df):
        wanted = set(symbols)
        for sym, g in long_df.groupby("symbol", sort=False):
            if sym not in wanted:
                continue
            out[sym] = g.drop(columns=["symbol"]).sort_index()

    info["loaded"] = len(out)
    info["missing"] = sorted(set(symbols) - set(out))
    if len(out):
        last = max(df.index.max() for df in out.values())
        info["last_bar"] = pd.Timestamp(last).strftime("%Y-%m-%d")
    else:
        info["last_bar"] = "n/a"
    return out, info


def load_index(ticker: str, period: str = "2y", refresh: bool = False) -> pd.DataFrame:
    """Fetch one index series (benchmark, Nifty 50, India VIX), cached per day."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = ticker.replace("^", "idx_").lower()
    path = os.path.join(CACHE_DIR, f"{safe}_{period}_{datetime.now():%Y%m%d}.parquet")
    if not refresh and os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    try:
        raw = yf.download(ticker, period=period, interval="1d", auto_adjust=True,
                          progress=False, timeout=30)
        df = clean_frame(raw)
    except Exception:
        df = pd.DataFrame(columns=OHLCV)
    if len(df):
        try:
            df.to_parquet(path)
        except Exception:
            pass
    return df
