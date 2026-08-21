"""NSE universe construction.

Constituent lists come straight from the NSE archives as CSV. Every successful
fetch is cached to disk and that cache doubles as the offline fallback, so the app
keeps working when NSE is unreachable.
"""
from __future__ import annotations

import io
import os
from datetime import datetime

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data_cache")

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_BASE = "https://nsearchives.nseindia.com/content"

UNIVERSES: dict[str, dict] = {
    "Nifty 50":       {"url": f"{_BASE}/indices/ind_nifty50list.csv",       "col": "Symbol"},
    "Nifty 100":      {"url": f"{_BASE}/indices/ind_nifty100list.csv",      "col": "Symbol"},
    "Nifty 200":      {"url": f"{_BASE}/indices/ind_nifty200list.csv",      "col": "Symbol"},
    "Nifty 500":      {"url": f"{_BASE}/indices/ind_nifty500list.csv",      "col": "Symbol"},
    "Nifty Midcap 150":  {"url": f"{_BASE}/indices/ind_niftymidcap150list.csv",  "col": "Symbol"},
    "Nifty Smallcap 250": {"url": f"{_BASE}/indices/ind_niftysmallcap250list.csv", "col": "Symbol"},
    "All NSE equity": {"url": f"{_BASE}/equities/EQUITY_L.csv",             "col": "SYMBOL"},
}

# Ultimate offline fallback: the Nifty 50 as of writing. Only used when NSE is
# unreachable *and* no disk cache exists yet.
_FALLBACK_NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA",
    "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND",
    "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "TRENT", "ULTRACEMCO", "WIPRO",
]

BENCHMARK = "^CRSLDX"      # Nifty 500
INDEX_NIFTY50 = "^NSEI"
INDEX_VIX = "^INDIAVIX"


def _cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = key.lower().replace(" ", "_")
    return os.path.join(CACHE_DIR, f"universe_{safe}.csv")


def to_yahoo(symbol: str) -> str:
    """NSE symbol -> Yahoo ticker. NSE uses '&' and '-' which Yahoo keeps as-is."""
    return f"{symbol.strip().upper()}.NS"


def from_yahoo(ticker: str) -> str:
    return ticker.replace(".NS", "")


def get_universe(name: str, refresh: bool = False) -> tuple[list[str], pd.DataFrame, str]:
    """Return (symbols, metadata frame, source note).

    Metadata carries company name and industry when NSE provides them, which the UI
    shows alongside each result.
    """
    if name not in UNIVERSES:
        name = "Nifty 500"
    spec = UNIVERSES[name]
    path = _cache_path(name)
    note = ""

    df = None
    if not refresh and os.path.exists(path):
        try:
            df = pd.read_csv(path)
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))).days
            note = f"disk cache ({age}d old)"
        except Exception:
            df = None

    if df is None:
        try:
            r = requests.get(spec["url"], headers=_HEADERS, timeout=25)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            df.to_csv(path, index=False)
            note = "live from NSE archives"
        except Exception as exc:
            if os.path.exists(path):
                df = pd.read_csv(path)
                note = f"NSE unreachable ({type(exc).__name__}); using disk cache"
            else:
                df = pd.DataFrame({"Symbol": _FALLBACK_NIFTY50})
                note = f"NSE unreachable ({type(exc).__name__}); using built-in Nifty 50"

    df.columns = [c.strip() for c in df.columns]
    col = spec["col"] if spec["col"] in df.columns else df.columns[0]
    if "Symbol" in df.columns:
        col = "Symbol"
    elif "SYMBOL" in df.columns:
        col = "SYMBOL"

    # the all-equity file mixes series; keep only the rolling-settlement equity series
    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip().isin(["EQ", "BE"])]

    meta = pd.DataFrame({
        "symbol": df[col].astype(str).str.strip().str.upper(),
        "name": (df["Company Name"] if "Company Name" in df.columns
                 else df["NAME OF COMPANY"] if "NAME OF COMPANY" in df.columns
                 else df[col]).astype(str).str.strip(),
        "industry": (df["Industry"].astype(str).str.strip()
                     if "Industry" in df.columns else ""),
    })
    meta = meta[meta["symbol"].str.len() > 0].drop_duplicates("symbol")
    meta = meta.reset_index(drop=True)
    return meta["symbol"].tolist(), meta, note
