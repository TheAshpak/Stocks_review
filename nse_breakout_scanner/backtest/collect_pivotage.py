"""Re-collect breakout events with the pivot-age constraint OFF.

Recording pivot_age on every event lets the threshold be chosen from measured outcomes
rather than taste: collect everything, then bucket by age in analysis.
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config as C, data as D, universe as U       # noqa: E402
from backtest import events as E                             # noqa: E402
from backtest.collect import OUT_DIR, CACHE_KEY              # noqa: E402

if __name__ == "__main__":
    syms, meta, _ = U.get_universe("Nifty 500")
    px, info = D.load_prices(CACHE_KEY, syms, period="10y")
    bench = D.load_index(U.BENCHMARK, period="10y")["Close"]
    s = C.override(C.preset("Balanced"), min_pivot_age=0)   # capture everything
    print("collecting with min_pivot_age=0 over %d symbols" % len(px), flush=True)
    t0 = time.time()
    df = E.build_breakout_events(px, bench, s, E.BTConfig())
    df.to_parquet(os.path.join(OUT_DIR, "events_breakout_pivotage.parquet"))
    print("saved %d events in %.1f min" % (len(df), (time.time()-t0)/60), flush=True)
