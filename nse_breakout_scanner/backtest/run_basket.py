"""Run the ₹1,000-since-2010 simulation on a 5-stock basket (2 large / 2 mid / 1 small).

Run:  python -m backtest.run_basket

Stock selection is data-driven and reproducible: within each NSE cap bucket, take the
highest-turnover name that has clean history back to 2009 and does not repeat an industry
already chosen. Nothing is hand-picked for its returns.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config as C              # noqa: E402
from core import data as D                # noqa: E402
from core import universe as U            # noqa: E402
from backtest import events as E          # noqa: E402
from backtest import portfolio as P       # noqa: E402

pd.set_option("display.width", 210)

CANDIDATES = {
    "Large cap (Nifty 50)": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC", "LT", "SBIN"],
    "Mid cap (Midcap 150)": ["VOLTAS", "FEDERALBNK", "ASHOKLEY", "MPHASIS", "EXIDEIND",
                             "SUPREMEIND", "AUROPHARMA"],
    "Small cap (Smallcap 250)": ["KEC", "NCC", "GRANULES", "BLUEDART"],
}
WANT = {"Large cap (Nifty 50)": 2, "Mid cap (Midcap 150)": 2,
        "Small cap (Smallcap 250)": 1}
START = "2009-01-01"           # a year of warm-up before the 2010 start
FIRST_TRADE = pd.Timestamp("2010-01-01")


def select(log=print) -> tuple:
    industry = {}
    for name in ("Nifty 50", "Nifty Midcap 150", "Nifty Smallcap 250"):
        _, meta, _ = U.get_universe(name)
        for r in meta.itertuples(index=False):
            industry[r.symbol] = r.industry

    allc = sorted({s for v in CANDIDATES.values() for s in v})
    px, info = D.load_prices("BASKET pool", allc, period="max")
    chosen, used_ind = [], set()
    for bucket, names in CANDIDATES.items():
        scored = []
        for s in names:
            d = px.get(s)
            if d is None or len(d) == 0 or d.index[0] > pd.Timestamp("2009-04-01"):
                continue
            turn = float(((d["Close"] * d["Volume"]) / 1e7).tail(250).median())
            scored.append((turn, s))
        scored.sort(reverse=True)
        picked = 0
        for turn, s in scored:
            ind = industry.get(s, "?")
            if ind in used_ind:
                continue
            chosen.append({"symbol": s, "bucket": bucket, "industry": ind,
                           "turnover_cr": round(turn, 1),
                           "first_bar": px[s].index[0].date()})
            used_ind.add(ind)
            picked += 1
            if picked >= WANT[bucket]:
                break
    return chosen, px


def main() -> None:
    chosen, pool = select()
    syms = [c["symbol"] for c in chosen]
    print("=" * 84)
    print("BASKET (selected by highest turnover per bucket, no repeated industry)")
    print("=" * 84)
    print(pd.DataFrame(chosen).to_string(index=False))

    prices = {s: pool[s] for s in syms}
    bench = D.load_index(U.BENCHMARK, period="max")
    nifty = D.load_index(U.INDEX_NIFTY50, period="max")
    bseries = bench["Close"] if len(bench) else None

    s = C.preset("Balanced")
    cfg = E.BTConfig(warmup=252)
    print("\ngenerating signals with the production rule engine…")
    ev = E.build_breakout_events(prices, bseries, s, cfg, log=None)
    if ev.empty:
        print("no events"); return

    # entry index + bars held -> calendar exit date
    exits = []
    for _, r in ev.iterrows():
        idx = prices[r["symbol"]].index
        j = int(r["t"]) + int(r["trade_bars"]) if np.isfinite(r["trade_bars"]) else None
        exits.append(idx[min(j, len(idx) - 1)] if j is not None else pd.NaT)
    ev["exit_date"] = exits
    ev = ev[ev["date"] >= FIRST_TRADE].reset_index(drop=True)
    print("signals: %d, %s -> %s" % (len(ev), ev["date"].min().date(), ev["date"].max().date()))
    print(ev.groupby("symbol").size().to_string())

    closes = {k: v["Close"] for k, v in prices.items()}
    scenarios = [
        ("all years included", None, None),
        ("ex COVID crash+recovery (Feb 2020 - Dec 2020)", "2020-02-01", "2020-12-31"),
        ("ex all of 2020 and 2021", "2020-01-01", "2021-12-31"),
    ]

    rows = []
    for name, a, b in scenarios:
        cfg_p = P.PortfolioConfig(start_capital=1000.0, risk_pct=0.02, max_positions=3,
                                  max_position_pct=0.40, cost_pct=0.004,
                                  exclude_from=a, exclude_to=b)
        res = P.run(ev, closes, cfg_p)
        st = P.stats(res, cfg_p)
        st["scenario"] = name
        st["skipped_window"] = res["skipped"]["window"]
        st["skipped_no_slot"] = res["skipped"]["no_slot"]
        rows.append(st)
        if a is None:
            base_res = res

    print("\n" + "=" * 84)
    print("RESULT: Rs 1,000 from Jan 2010, 2% risk per trade, max 3 positions, 0.4% costs")
    print("=" * 84)
    out = pd.DataFrame(rows)[["scenario", "trades", "final", "multiple", "cagr", "max_dd",
                              "win_rate", "expectancy_R", "profit_factor",
                              "pct_time_invested", "skipped_window", "skipped_no_slot"]]
    print(out.round(2).to_string(index=False))

    bh = P.buy_and_hold(closes, 1000.0, 0.004, start_date=FIRST_TRADE)
    print("\nBENCHMARKS over the same window")
    print("  equal-weight buy & hold of the same 5 stocks: Rs %.0f  (%.1fx, CAGR %.1f%%, "
          "max DD %.1f%%)" % (bh["final"], bh["multiple"], bh["cagr"], bh["max_dd"]))
    for label, idx in (("Nifty 500", bench), ("Nifty 50", nifty)):
        if len(idx):
            px = idx["Close"]
            px = px[px.index >= FIRST_TRADE]
            if len(px) > 10:
                mult = float(px.iloc[-1] / px.iloc[0])
                yrs = (px.index[-1] - px.index[0]).days / 365.25
                dd = float(((px / px.cummax() - 1) * 100).min())
                print("  %-14s buy & hold: Rs %.0f  (%.1fx, CAGR %.1f%%, max DD %.1f%%)"
                      % (label, 1000 * mult, mult, (mult ** (1 / yrs) - 1) * 100, dd))

    eq = base_res["equity"]["equity"]
    print("\nEQUITY BY YEAR (all-years scenario)")
    yr = eq.resample("YE").last()
    prev = 1000.0
    for d, v in yr.items():
        print("  %d  Rs %9.0f   %+7.1f%%" % (d.year, v, (v / prev - 1) * 100))
        prev = v

    tr = pd.DataFrame([{"symbol": t.symbol, "R": t.R, "exit": t.exit_reason}
                       for t in base_res["trades"]])
    print("\nTRADES BY SYMBOL (all-years scenario)")
    print(tr.groupby("symbol").agg(n=("R", "size"), win=("R", lambda x: (x > 0).mean() * 100),
                                   meanR=("R", "mean")).round(2).to_string())
    print("\nexit mix: " + ", ".join("%s %d" % (k, v)
                                     for k, v in tr["exit"].value_counts().items()))


if __name__ == "__main__":
    main()
