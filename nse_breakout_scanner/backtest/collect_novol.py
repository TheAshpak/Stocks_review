"""Rebuild breakout events with the volume gate OFF.

The main dataset only contains breakouts that already passed the >=1.5x volume gate, so
it cannot answer whether that gate earns its keep. This variant admits every breakout
regardless of volume, so low-volume breaks can be compared directly.
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config as C, data as D, universe as U          # noqa: E402
from backtest import events as E                                # noqa: E402
from backtest.collect import OUT_DIR, CACHE_KEY                 # noqa: E402

if __name__ == "__main__":
    syms, meta, _ = U.get_universe("Nifty 500")
    px, info = D.load_prices(CACHE_KEY, syms, period="10y")
    bench = D.load_index(U.BENCHMARK, period="10y")["Close"]
    s = C.override(C.preset("Balanced"), bo_require_volume=False,
                   bo_min_breakout_volume=1.0)
    print("volume gate off; %d symbols" % len(px), flush=True)
    t0 = time.time()
    df = E.build_breakout_events(px, bench, s, E.BTConfig())
    df.to_parquet(os.path.join(OUT_DIR, "events_breakout_novol.parquet"))
    print("saved %d events in %.1f min" % (len(df), (time.time() - t0) / 60), flush=True)
