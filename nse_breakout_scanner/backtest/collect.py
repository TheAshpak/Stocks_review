"""Build the historical event datasets and save them to parquet.

Run:  python -m backtest.collect [n_symbols] [period]

Separated from the analysis so the expensive walk-forward scan happens once and any
number of weight experiments can then run against the saved events in seconds.
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config as C            # noqa: E402
from core import data as D              # noqa: E402
from core import universe as U          # noqa: E402
from backtest import events as E        # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "backtest_out")
CACHE_KEY = "BT Nifty 500"


def main(n_symbols: int = 0, period: str = "10y") -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    t_all = time.time()

    syms, meta, note = U.get_universe("Nifty 500")
    if n_symbols:
        syms = syms[:n_symbols]
    print("universe: %d symbols (%s)" % (len(syms), note), flush=True)

    t0 = time.time()
    px, info = D.load_prices(CACHE_KEY, syms, period=period,
                             progress_cb=lambda f, m: print("   " + m, flush=True))
    print("prices: %s, %d loaded, %d missing, %.1fs"
          % (info["source"], info["loaded"], len(info["missing"]), time.time() - t0),
          flush=True)
    bars = pd.Series({k: len(v) for k, v in px.items()})
    print("bars per symbol: median %d, min %d, max %d | last bar %s"
          % (bars.median(), bars.min(), bars.max(), info["last_bar"]), flush=True)

    bench = D.load_index(U.BENCHMARK, period=period)["Close"]
    print("benchmark bars: %d" % len(bench), flush=True)

    s = C.preset("Balanced")
    cfg = E.BTConfig(period=period)

    t0 = time.time()
    print("\n--- pre-breakout events ---", flush=True)
    pb = E.build_prebreakout_events(px, bench, s, cfg)
    pb.to_parquet(os.path.join(OUT_DIR, "events_prebreakout.parquet"))
    print("saved %d pre-breakout events (%.1fs)" % (len(pb), time.time() - t0), flush=True)

    t0 = time.time()
    print("\n--- breakout events ---", flush=True)
    bo = E.build_breakout_events(px, bench, s, cfg)
    bo.to_parquet(os.path.join(OUT_DIR, "events_breakout.parquet"))
    print("saved %d breakout events (%.1fs)" % (len(bo), time.time() - t0), flush=True)

    print("\nTOTAL %.1f min" % ((time.time() - t_all) / 60), flush=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    p = sys.argv[2] if len(sys.argv) > 2 else "10y"
    main(n, p)
