"""Tunable thresholds for every scanner, with Strict / Balanced / Loose presets.

Every number a rule tests against lives here so the sidebar can drive the whole
engine without touching scanner code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace


@dataclass
class Settings:
    # ---------------- universe / liquidity gates (shared) ----------------
    min_price: float = 30.0                # rupees; avoids penny-stock noise
    min_avg_volume: float = 200_000        # 20d average shares traded
    min_turnover_cr: float = 5.0           # 20d median traded value, INR crore
    min_bars: int = 250                    # need >=250 bars for SMA200 + 52w stats

    # ---------------- pre-breakout (tab 1) ----------------
    pb_max_dist_to_pivot: float = 4.0      # % below pivot to still be "about to"
    pb_min_base_len: int = 15              # bars of consolidation
    pb_max_base_len: int = 120
    pb_max_base_depth: float = 25.0        # % from base high to base low
    pb_max_off_52w_high: float = 25.0      # % below the 52-week high
    pb_min_prior_leg: float = 20.0         # % prior advance into the base
    pb_require_above_sma200: bool = True
    pb_atr_compression: float = 0.75       # ATR% now / ATR% 40 bars ago
    pb_vol_dryup: float = 0.80             # VolSMA10 / VolSMA50 inside the base
    pb_max_tightness: float = 3.0          # stdev/mean of last 10 closes, %
    pb_min_rsi: float = 45.0
    pb_min_score: float = 50.0
    pb_pivot_tolerance: float = 2.0        # % band counted as a "touch"
    base_select: str = "longest"           # "longest" = most significant level,
                                           # "quality" = tightest recent base

    # ---------------- breakout (tab 2) ----------------
    bo_lookback_days: int = 10             # how recently the breakout may have fired
    bo_min_breakout_volume: float = 1.5    # x VolSMA50 on the breakout bar
    bo_require_volume: bool = True         # hard gate vs. scored penalty
    bo_min_close_above_pivot: float = 0.5  # % clearance to count as a break
    # 8%% not 15%%: backtested out-of-sample, mean R turns negative beyond 8%% past
    # the pivot (-0.170 in 8-15%%, -0.149 above 15%%). See BACKTEST.md section 6.
    bo_max_extension: float = 8.0          # % above pivot before "chase risk"
    bo_max_atr_extension: float = 2.5      # ATRs above EMA20 before "chase risk"
    bo_min_close_range_pos: float = 0.60   # close position in breakout-day range
    bo_max_rsi: float = 85.0               # above this = climax risk
    bo_max_distribution_days: int = 3      # in the last 10 bars
    # A level must be this many sessions old before a close through it counts as a
    # breakout. Without it, a stock in a vertical run is flagged every time it
    # closes above the prior window's highest high - even yesterday's high.
    min_pivot_age: int = 10
    bo_min_score: float = 50.0

    # ---------------- weakening (tab 3) ----------------
    wk_min_signals: int = 2                # signals needed to be listed
    wk_min_risk_score: float = 25.0
    wk_distribution_window: int = 15
    wk_min_distribution_days: int = 3
    wk_divergence_lookback: int = 40
    wk_death_cross_gap: float = 2.0        # % gap between SMA50 and SMA200
    wk_parabolic_move: float = 25.0        # % gain in 10 bars = climax candidate
    wk_parabolic_atr: float = 3.0          # ATRs above EMA20
    wk_updown_vol_ratio: float = 0.90      # 20d up-volume / down-volume

    # ---------------- market regime ----------------
    regime_scales_score: bool = True
    breadth_riskon: float = 55.0           # % of universe above SMA50
    breadth_riskoff: float = 35.0

    weights_mode: str = "conventional"     # "conventional" | "fitted"

    label: str = "Balanced"


PRESETS: dict[str, dict] = {
    "Strict": dict(
        label="Strict",
        pb_max_dist_to_pivot=3.0,
        pb_min_base_len=25,
        pb_max_base_depth=20.0,
        pb_max_off_52w_high=15.0,
        pb_min_prior_leg=25.0,
        pb_atr_compression=0.70,
        pb_vol_dryup=0.75,
        pb_max_tightness=2.5,
        pb_min_rsi=50.0,
        pb_min_score=70.0,
        bo_min_breakout_volume=2.0,
        bo_require_volume=True,
        bo_lookback_days=7,
        bo_max_extension=6.0,
        bo_min_close_range_pos=0.70,
        bo_min_score=70.0,
        wk_min_signals=2,
        wk_min_risk_score=20.0,
        min_turnover_cr=10.0,
    ),
    "Balanced": dict(label="Balanced"),
    "Loose": dict(
        label="Loose",
        pb_max_dist_to_pivot=7.0,
        pb_min_base_len=10,
        pb_max_base_depth=32.0,
        pb_max_off_52w_high=35.0,
        pb_min_prior_leg=10.0,
        pb_require_above_sma200=False,
        pb_atr_compression=0.90,
        pb_vol_dryup=0.95,
        pb_max_tightness=4.5,
        pb_min_rsi=40.0,
        pb_min_score=35.0,
        bo_min_breakout_volume=1.2,
        bo_require_volume=False,
        bo_lookback_days=15,
        bo_max_extension=12.0,
        bo_min_close_range_pos=0.50,
        bo_min_score=35.0,
        wk_min_signals=1,
        wk_min_risk_score=15.0,
        min_turnover_cr=2.0,
        min_price=20.0,
    ),
}


def preset(name: str) -> Settings:
    """Build a Settings object from a preset name."""
    return Settings(**PRESETS.get(name, PRESETS["Balanced"]))


def override(s: Settings, **kw) -> Settings:
    """Return a copy of `s` with the given fields replaced."""
    clean = {k: v for k, v in kw.items() if k in asdict(s)}
    return replace(s, **clean)
