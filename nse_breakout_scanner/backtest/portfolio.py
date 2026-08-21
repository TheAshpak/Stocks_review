"""Capital-level portfolio simulation on a small hand-picked basket.

The event study in `analyze.py` measures expectancy *per trade*. That is the right unit
for judging a signal, but it says nothing about what an account would have done, because
an account has finite capital, can only hold so many positions at once, pays costs, and
compounds. This module walks the calendar day by day and marks the book to market.

Deliberately separate from the main backtest: five symbols is far too thin to draw
statistical conclusions from. This is an illustration of mechanics, not evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class PortfolioConfig:
    start_capital: float = 1000.0
    risk_pct: float = 0.02           # fraction of equity risked per trade
    max_positions: int = 3
    max_position_pct: float = 0.40   # cap any single position at this share of equity
    cost_pct: float = 0.004          # round-trip: brokerage + STT + slippage
    exclude_from: str | None = None   # skip entries inside this window
    exclude_to: str | None = None
    allow_fractional: bool = True    # see note in run(): Rs 1,000 cannot buy whole shares


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry: float
    exit_price: float
    stop: float
    shares: float
    cost: float
    R: float
    exit_reason: str


def exit_price_from_R(entry: float, stop: float, R: float) -> float:
    """The simulator records outcomes in R; recover the rupee exit price."""
    return entry + R * (entry - stop)


def run(events: pd.DataFrame, closes: dict, cfg: PortfolioConfig) -> dict:
    """Day-by-day simulation.

    `events` needs: symbol, date (entry), entry, stop, exit_date, trade_R, trade_exit.
    `closes` maps symbol -> Close series, used to mark open positions to market.
    """
    ev = events.dropna(subset=["trade_R", "exit_date"]).copy()
    ev = ev.sort_values("date").reset_index(drop=True)

    ex_from = pd.Timestamp(cfg.exclude_from) if cfg.exclude_from else None
    ex_to = pd.Timestamp(cfg.exclude_to) if cfg.exclude_to else None

    all_dates = sorted(set().union(*[set(s.index) for s in closes.values()]))
    if not all_dates:
        return {}
    start = ev["date"].min()
    all_dates = [d for d in all_dates if d >= start]

    by_date: dict = {}
    for _, r in ev.iterrows():
        by_date.setdefault(r["date"], []).append(r)

    cash = float(cfg.start_capital)
    open_pos: list[Position] = []
    closed: list[Position] = []
    curve, skipped = [], {"window": 0, "no_slot": 0, "no_cash": 0, "unaffordable": 0}

    for d in all_dates:
        # ---- exits first, so capital freed today can be redeployed today
        still = []
        for p in open_pos:
            if d >= p.exit_date:
                cash += p.shares * p.exit_price - (p.shares * p.exit_price) * cfg.cost_pct / 2
                closed.append(p)
            else:
                still.append(p)
        open_pos = still

        # ---- mark to market for equity (used for position sizing)
        mtm = 0.0
        for p in open_pos:
            s = closes.get(p.symbol)
            px = float(s.loc[d]) if (s is not None and d in s.index) else p.entry
            mtm += p.shares * px
        equity = cash + mtm

        # ---- entries
        for r in by_date.get(d, []):
            if ex_from is not None and ex_from <= d <= ex_to:
                skipped["window"] += 1
                continue
            if len(open_pos) >= cfg.max_positions:
                skipped["no_slot"] += 1
                continue
            if any(p.symbol == r["symbol"] for p in open_pos):
                continue                      # one position per symbol at a time
            entry, stop = float(r["entry"]), float(r["stop"])
            rps = entry - stop
            if not np.isfinite(rps) or rps <= 0:
                continue

            shares = (equity * cfg.risk_pct) / rps
            value = shares * entry
            cap = equity * cfg.max_position_pct
            if value > cap:
                shares, value = cap / entry, cap
            if value > cash:
                shares, value = cash / entry, cash
            if not cfg.allow_fractional:
                shares = float(int(shares))
                value = shares * entry
            if shares <= 0 or value <= 0:
                skipped["unaffordable"] += 1
                continue

            entry_cost = value * cfg.cost_pct / 2
            if value + entry_cost > cash:
                skipped["no_cash"] += 1
                continue
            cash -= value + entry_cost
            open_pos.append(Position(
                symbol=r["symbol"], entry_date=d, exit_date=r["exit_date"],
                entry=entry, exit_price=exit_price_from_R(entry, stop, float(r["trade_R"])),
                stop=stop, shares=shares, cost=entry_cost, R=float(r["trade_R"]),
                exit_reason=str(r["trade_exit"])))

        mtm = 0.0
        for p in open_pos:
            s = closes.get(p.symbol)
            px = float(s.loc[d]) if (s is not None and d in s.index) else p.entry
            mtm += p.shares * px
        curve.append({"date": d, "equity": cash + mtm, "cash": cash,
                      "open": len(open_pos)})

    # ---- force-close anything still open at the final mark
    last = all_dates[-1]
    for p in open_pos:
        s = closes.get(p.symbol)
        px = float(s.loc[last]) if (s is not None and last in s.index) else p.entry
        cash += p.shares * px
        closed.append(p)

    eq = pd.DataFrame(curve).set_index("date")
    return {"equity": eq, "trades": closed, "skipped": skipped,
            "final": float(eq["equity"].iloc[-1]) if len(eq) else float(cfg.start_capital)}


def stats(res: dict, cfg: PortfolioConfig) -> dict:
    eq = res["equity"]["equity"]
    trades = res["trades"]
    if len(eq) < 2:
        return {}
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / cfg.start_capital
    cagr = (total ** (1 / years) - 1) * 100 if years > 0 else np.nan
    dd = (eq / eq.cummax() - 1) * 100
    rs = [t.R for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    monthly = eq.resample("ME").last().pct_change().dropna()
    return {
        "start": cfg.start_capital, "final": float(eq.iloc[-1]),
        "multiple": float(total), "years": years, "cagr": cagr,
        "max_dd": float(dd.min()),
        "trades": len(trades),
        "win_rate": (len(wins) / len(rs) * 100) if rs else np.nan,
        "avg_win_R": float(np.mean(wins)) if wins else np.nan,
        "avg_loss_R": float(np.mean(losses)) if losses else np.nan,
        "expectancy_R": float(np.mean(rs)) if rs else np.nan,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else np.nan,
        "best_month": float(monthly.max() * 100) if len(monthly) else np.nan,
        "worst_month": float(monthly.min() * 100) if len(monthly) else np.nan,
        "pct_time_invested": float((res["equity"]["open"] > 0).mean() * 100),
    }


def buy_and_hold(closes: dict, start_capital: float, cost_pct: float,
                 start_date=None) -> dict:
    """Equal-weight buy and hold across the same basket - the benchmark that matters."""
    syms = list(closes)
    per = start_capital / len(syms)
    curves = []
    for s in syms:
        px = closes[s]
        if start_date is not None:
            px = px[px.index >= start_date]
        if len(px) == 0:
            continue
        shares = (per * (1 - cost_pct / 2)) / float(px.iloc[0])
        curves.append((shares * px).rename(s))
    if not curves:
        return {}
    eq = pd.concat(curves, axis=1).ffill().sum(axis=1)
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / start_capital
    dd = (eq / eq.cummax() - 1) * 100
    return {"equity": eq, "final": float(eq.iloc[-1]), "multiple": float(total),
            "cagr": (total ** (1 / years) - 1) * 100 if years > 0 else np.nan,
            "max_dd": float(dd.min()), "years": years}
