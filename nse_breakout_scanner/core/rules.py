"""The rule engine.

Every filter in the app is one function that returns `Signal` objects. A Signal
carries not just pass/fail but the *numbers it judged on*, so the UI can always
answer "why is this stock on the list?".

Three statuses matter:
  reject  - a hard gate failed; the stock never reaches the table
  warn    - the setup is listed but something is wrong with it
  pass    - a positive characteristic, contributing `points` out of `weight`

A score is `100 * sum(points) / sum(weight)` over scored signals only, so adding or
removing a rule cannot silently rescale the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import weights as WGT


# ------------------------------------------------------------------ primitives
@dataclass
class Signal:
    id: str
    category: str
    label: str
    detail: str
    status: str = "pass"          # pass | warn | fail | reject
    weight: float = 0.0
    points: float = 0.0


@dataclass
class ScoreCard:
    symbol: str
    signals: list = field(default_factory=list)
    score: float = 0.0
    raw_score: float = 0.0
    grade: str = ""

    def add(self, sig: Signal):
        self.signals.append(sig)
        return sig

    def by_status(self, status: str) -> list:
        return [s for s in self.signals if s.status == status]

    @property
    def rejections(self) -> list:
        return self.by_status("reject")

    @property
    def warnings(self) -> list:
        return self.by_status("warn")

    @property
    def passes(self) -> list:
        return [s for s in self.signals if s.status == "pass" and s.weight > 0]

    @property
    def misses(self) -> list:
        return [s for s in self.signals if s.status == "fail" and s.weight > 0]

    def finalise(self, regime_mult: float = 1.0) -> "ScoreCard":
        tw = sum(s.weight for s in self.signals if s.weight > 0
                 and s.status in ("pass", "fail"))
        tp = sum(s.points for s in self.signals if s.weight > 0
                 and s.status in ("pass", "fail"))
        self.raw_score = float(100.0 * tp / tw) if tw > 0 else 0.0
        self.score = float(np.clip(self.raw_score * regime_mult, 0, 100))
        self.grade = grade_of(self.score)
        return self


def grade_of(score: float) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B+"
    if score >= 55:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def fin(x) -> bool:
    try:
        return bool(np.isfinite(float(x)))
    except Exception:
        return False


def ramp(x, at0: float, at1: float) -> float:
    """Linear 0..1 credit: `at0` scores nothing, `at1` scores full. at0 may exceed at1."""
    if not fin(x):
        return 0.0
    x = float(x)
    if at1 == at0:
        return 1.0 if x >= at1 else 0.0
    return float(np.clip((x - at0) / (at1 - at0), 0.0, 1.0))


def scored(card: ScoreCard, sid: str, cat: str, label: str, credit: float,
           weight: float, detail: str, pass_at: float = 0.5) -> Signal:
    """Add a partial-credit signal. `credit` is 0..1 of `weight`.

    The literal weight passed in is the conventional default; a fitted weight set
    installed via `core.weights` overrides it by rule id.
    """
    credit = float(np.clip(credit, 0.0, 1.0))
    weight = WGT.resolve(sid, weight)
    return card.add(Signal(sid, cat, label, detail,
                           "pass" if credit >= pass_at else "fail",
                           weight, weight * credit))


def gate(card: ScoreCard, sid: str, cat: str, label: str, ok: bool,
         detail: str) -> bool:
    """Add a hard gate. Returns whether it passed."""
    card.add(Signal(sid, cat, label, detail, "pass" if ok else "reject", 0.0, 0.0))
    return ok


def warn(card: ScoreCard, sid: str, cat: str, label: str, tripped: bool,
         detail: str) -> bool:
    if tripped:
        card.add(Signal(sid, cat, label, detail, "warn", 0.0, 0.0))
    return tripped


# ================================================================== shared gates
def liquidity_gates(card: ScoreCard, f: dict, s) -> bool:
    """Tradeability. An illiquid 'breakout' cannot be entered or exited at the price
    the chart shows, so these are hard rejections regardless of how good the setup is."""
    ok = True
    ok &= gate(card, "LIQ_PRICE", "Liquidity", "Price above floor",
               fin(f["close"]) and f["close"] >= s.min_price,
               "close %s%.2f vs floor %s%.0f" % ("₹", f["close"], "₹", s.min_price))
    ok &= gate(card, "LIQ_VOL", "Liquidity", "Average volume sufficient",
               fin(f["volsma20"]) and f["volsma20"] >= s.min_avg_volume,
               "20d avg volume %s vs min %s" %
               (f"{f['volsma20']:,.0f}" if fin(f["volsma20"]) else "n/a",
                f"{s.min_avg_volume:,.0f}"))
    ok &= gate(card, "LIQ_TURN", "Liquidity", "Traded value sufficient",
               fin(f["turnover_cr"]) and f["turnover_cr"] >= s.min_turnover_cr,
               "20d median turnover %s%.1f cr vs min %s%.1f cr" %
               ("₹", f["turnover_cr"] if fin(f["turnover_cr"]) else 0.0,
                "₹", s.min_turnover_cr))
    return bool(ok)


# ================================================================== TAB 1: pre-breakout
def pre_breakout_gates(card: ScoreCard, f: dict, s) -> bool:
    """Hard eligibility for 'about to break out'."""
    ok = liquidity_gates(card, f, s)

    ok &= gate(card, "PB_BASE", "Structure", "A consolidation base exists",
               bool(f["base_valid"]),
               ("base of %d bars, %.1f%% deep, price in top %.0f%% of it"
                % (f["base_len"], f["base_depth_pct"], (1 - f["base_position"]) * 100)
                if f["base_valid"] else "no base: %s" % f["base_reason"]))
    if not f["base_valid"]:
        return False

    ok &= gate(card, "PB_BELOW", "Structure", "Still below the pivot (not yet broken out)",
               fin(f["dist_to_pivot_pct"]) and f["dist_to_pivot_pct"] >= -0.5,
               "close %s%.2f vs pivot %s%.2f (%+.2f%% to go)"
               % ("₹", f["close"], "₹", f["pivot"], f["dist_to_pivot_pct"]))

    ok &= gate(card, "PB_NEAR", "Structure", "Within striking distance of the pivot",
               fin(f["dist_to_pivot_pct"]) and f["dist_to_pivot_pct"] <= s.pb_max_dist_to_pivot,
               "%.2f%% below pivot, limit %.1f%%"
               % (f["dist_to_pivot_pct"] if fin(f["dist_to_pivot_pct"]) else 99,
                  s.pb_max_dist_to_pivot))

    ok &= gate(card, "PB_LEN", "Structure", "Base long enough to matter",
               f["base_len"] >= s.pb_min_base_len,
               "%d bars vs min %d" % (f["base_len"], s.pb_min_base_len))

    ok &= gate(card, "PB_DEPTH", "Structure", "Base not too deep",
               fin(f["base_depth_pct"]) and f["base_depth_pct"] <= s.pb_max_base_depth,
               "%.1f%% deep vs max %.0f%%" % (f["base_depth_pct"], s.pb_max_base_depth))

    if s.pb_require_above_sma200:
        ok &= gate(card, "PB_SMA200", "Trend", "Above the 200-day average",
                   bool(f["above_sma200"]),
                   "close %s%.2f vs SMA200 %s%.2f" %
                   ("₹", f["close"], "₹", f["sma200"]))

    ok &= gate(card, "PB_52W", "Trend", "Near the 52-week high",
               fin(f["off_52w_high_pct"]) and f["off_52w_high_pct"] <= s.pb_max_off_52w_high,
               "%.1f%% below 52w high, limit %.0f%%"
               % (f["off_52w_high_pct"] if fin(f["off_52w_high_pct"]) else 99,
                  s.pb_max_off_52w_high))

    ok &= gate(card, "PB_LEG", "Trend", "A prior advance leads into the base",
               fin(f["prior_leg_pct"]) and f["prior_leg_pct"] >= s.pb_min_prior_leg,
               "prior leg %.1f%% vs min %.0f%% (breakouts continue trends, they rarely start them)"
               % (f["prior_leg_pct"] if fin(f["prior_leg_pct"]) else 0.0, s.pb_min_prior_leg))

    ok &= gate(card, "PB_AGE", "Structure", "Resistance level is established",
               f["pivot_age"] >= s.min_pivot_age,
               "the pivot high was printed %d sessions ago (needs %d): a level set "
               "days ago is just the top of an ongoing run, not resistance"
               % (f["pivot_age"], s.min_pivot_age))

    ok &= gate(card, "PB_RSI", "Momentum", "Momentum not broken",
               fin(f["rsi"]) and f["rsi"] >= s.pb_min_rsi,
               "RSI(14) %.1f vs min %.0f" % (f["rsi"] if fin(f["rsi"]) else 0, s.pb_min_rsi))
    return bool(ok)


def pre_breakout_signals(card: ScoreCard, f: dict, s) -> None:
    """The quality score: what separates a coiled spring from a random range."""
    # --- volatility contraction: the single most reliable pre-breakout tell
    comp = f["atr_compression"]
    scored(card, "PB_ATR", "Volatility", "Volatility contracting (VCP)",
           ramp(comp, 1.00, s.pb_atr_compression - 0.15), 12.0,
           "ATR%% %.2f%% now vs %.2f%% 40 bars ago (ratio %.2f, target <%.2f)"
           % (f["atr_pct"], f["atr_pct_40ago"], comp if fin(comp) else 9.99,
              s.pb_atr_compression) if fin(comp) else "ATR history unavailable")

    scored(card, "PB_SQUEEZE", "Volatility", "Bollinger squeeze",
           ramp(f["bbw_rank"], 60.0, 10.0), 6.0,
           "band width in the %.0fth percentile of the last 250 days"
           % f["bbw_rank"] if fin(f["bbw_rank"]) else "band width unavailable")

    # --- volume dry-up: sellers exhausted inside the base
    scored(card, "PB_DRYUP", "Volume", "Volume drying up in the base",
           ramp(f["vol_dryup"], 1.10, s.pb_vol_dryup - 0.15), 10.0,
           "10d avg volume is %.0f%% of the 50d average (target <%.0f%%)"
           % (f["vol_dryup"] * 100, s.pb_vol_dryup * 100) if fin(f["vol_dryup"])
           else "volume history unavailable")

    # --- tightness
    tight = ramp(f["base_tightness_pct"], s.pb_max_tightness + 1.5, 0.6)
    nr = min((f["nr7_count"] + f["inside_days"]) / 5.0, 1.0)
    scored(card, "PB_TIGHT", "Volatility", "Closes are tight",
           0.7 * tight + 0.3 * nr, 8.0,
           "last 10 closes vary %.2f%% (limit %.1f%%); %d NR7 + %d inside days in 15"
           % (f["base_tightness_pct"], s.pb_max_tightness, f["nr7_count"], f["inside_days"]))

    scored(card, "PB_VCP3", "Volatility", "Successive contractions inside the base",
           1.0 if f["base_vcp"] else 0.0, 6.0,
           "third-by-third ranges %s%s" % (f["base_contractions"],
                                           "" if f["base_vcp"] else " (not monotonically tighter)"))

    # --- structure quality
    scored(card, "PB_TOUCH", "Structure", "Resistance level is well established",
           ramp(f["base_touches"], 1.0, 3.0), 8.0,
           "%d swing high(s) within %.0f%% of %s%.2f; level last touched %d bars ago"
           % (f["base_touches"], s.pb_pivot_tolerance, "₹", f["pivot"], f["pivot_age"]))

    scored(card, "PB_HL", "Structure", "Higher lows into resistance",
           1.0 if f["higher_lows"] else 0.0, 6.0,
           "last three swing lows ascending" if f["higher_lows"]
           else "swing lows are not ascending (buyers not yet stepping up)")

    scored(card, "PB_POS", "Structure", "Price sitting at the top of the base",
           ramp(f["base_position"], 0.55, 0.95), 4.0,
           "close is %.0f%% of the way up the base" % (f["base_position"] * 100)
           if fin(f["base_position"]) else "base position unavailable")

    scored(card, "PB_PROX", "Structure", "Close to the trigger",
           ramp(f["dist_to_pivot_pct"], s.pb_max_dist_to_pivot, 0.2), 8.0,
           "%.2f%% below the pivot" % f["dist_to_pivot_pct"]
           if fin(f["dist_to_pivot_pct"]) else "distance unavailable")

    # --- trend alignment
    stack = 0.0
    stack += 0.35 if f["above_ema20"] else 0.0
    stack += 0.25 if f["above_sma50"] else 0.0
    stack += 0.20 if f["above_sma200"] else 0.0
    stack += 0.20 if (fin(f["sma50_slope"]) and f["sma50_slope"] > 0) else 0.0
    scored(card, "PB_STACK", "Trend", "Moving averages aligned and rising",
           stack, 10.0,
           "close %s EMA20, %s SMA50, %s SMA200; SMA50 slope %+.3f%%/bar"
           % ("above" if f["above_ema20"] else "below",
              "above" if f["above_sma50"] else "below",
              "above" if f["above_sma200"] else "below",
              f["sma50_slope"] if fin(f["sma50_slope"]) else 0.0))

    scored(card, "PB_LEGQ", "Trend", "Strong prior advance",
           ramp(f["prior_leg_pct"], s.pb_min_prior_leg, 60.0), 6.0,
           "price advanced %.0f%% into this base" % f["prior_leg_pct"]
           if fin(f["prior_leg_pct"]) else "prior leg unavailable")

    # --- relative strength
    rs_credit = 0.6 * ramp(f["rs60"], -2.0, 20.0) + (0.4 if f["rs_line_at_high"] else 0.0)
    scored(card, "PB_RS", "Relative strength", "Outperforming the market",
           rs_credit, 12.0,
           "60d relative return %+.1f%% vs Nifty 500; RS line %s"
           % (f["rs60"] if fin(f["rs60"]) else 0.0,
              "at a 60-day high (leadership before price confirms)" if f["rs_line_at_high"]
              else "not at a new high"))

    # --- accumulation footprint
    acc = f["acc_days_25"]
    dist = f["dist_days_25"]
    acc_credit = 0.0
    acc_credit += 0.45 * ramp(acc - dist, -1.0, 4.0)
    acc_credit += 0.30 * ramp(f["updown_vol"], 0.8, 1.6)
    acc_credit += 0.25 * ramp(f["obv_slope20"], -0.10, 0.20)
    scored(card, "PB_ACC", "Volume", "Accumulation under the surface",
           acc_credit, 10.0,
           "%d accumulation vs %d distribution days in 25; up/down volume %.2f; "
           "OBV slope %+.3f%%/bar"
           % (acc, dist, f["updown_vol"] if fin(f["updown_vol"]) else 0.0,
              f["obv_slope20"] if fin(f["obv_slope20"]) else 0.0))

    # --- ADX coiling: low ADX with buyers in control is a spring, not a trend
    coil = 0.0
    if fin(f["adx"]):
        coil = ramp(f["adx"], 30.0, 12.0)
        if fin(f["di_plus"]) and fin(f["di_minus"]) and f["di_plus"] > f["di_minus"]:
            coil = min(1.0, coil + 0.25)
    scored(card, "PB_ADX", "Momentum", "Trend energy coiled, buyers in control",
           coil, 4.0,
           "ADX %.1f (low = consolidation), DI+ %.1f vs DI- %.1f"
           % (f["adx"], f["di_plus"], f["di_minus"]) if fin(f["adx"]) else "ADX unavailable")

    # --- Minervini trend template
    t = minervini_template(f)
    scored(card, "PB_TEMPLATE", "Trend", "Minervini trend template",
           t["passed"] / t["total"], 8.0,
           "%d of %d conditions met: %s" % (t["passed"], t["total"], t["summary"]))

    # --- named pattern bonus
    # Flattened deliberately. Backtested over 10 years, no pattern reliably beat a
    # plain range consolidation, and bull flag / flat base underperformed it in BOTH
    # folds - while this table used to score them 0.75-0.80 against range's 0.25.
    # The tilt was removed rather than inverted: the honest reading is that the pattern
    # label is descriptive, not predictive. See BACKTEST.md section 6.
    strong = {"VCP (contracting volatility)": 0.60, "Cup with handle": 0.60,
              "Darvas box": 0.60, "Flat base": 0.50, "Ascending triangle": 0.55,
              "Bull flag": 0.50, "Range consolidation": 0.50}
    scored(card, "PB_PATTERN", "Structure", "Recognised chart pattern",
           strong.get(f["pattern"], 0.5), 4.0,
           "pattern read as %s%s" % (f["pattern"],
                                     (" (also: %s)" % ", ".join(f["patterns"][1:]))
                                     if len(f["patterns"]) > 1 else ""))


def pre_breakout_warnings(card: ScoreCard, f: dict, s) -> None:
    """Things that are wrong with an otherwise-listed setup."""
    warn(card, "W_ATR_EXP", "Volatility", "Volatility expanding, not contracting",
         fin(f["atr_compression"]) and f["atr_compression"] > 1.05,
         "ATR%% ratio %.2f - range is widening, which is churn rather than coiling"
         % f["atr_compression"] if fin(f["atr_compression"]) else "")

    warn(card, "W_DISTRIB", "Volume", "Distribution inside the base",
         f["dist_days_25"] > f["acc_days_25"] and f["dist_days_25"] >= 3,
         "%d distribution vs %d accumulation days in 25 sessions - supply is winning"
         % (f["dist_days_25"], f["acc_days_25"]))

    warn(card, "W_DOWNVOL", "Volume", "Down days carry more volume",
         fin(f["updown_vol"]) and f["updown_vol"] < 0.85,
         "up/down volume ratio %.2f over 20 days" % f["updown_vol"]
         if fin(f["updown_vol"]) else "")

    warn(card, "W_EMA20", "Trend", "Trading below the 20-day EMA",
         not f["above_ema20"],
         "close %s%.2f vs EMA20 %s%.2f - short-term demand has faded"
         % ("₹", f["close"], "₹", f["ema20"]))

    warn(card, "W_SMA50", "Trend", "Below the 50-day average",
         not f["above_sma50"],
         "close %s%.2f vs SMA50 %s%.2f" % ("₹", f["close"], "₹", f["sma50"]))

    warn(card, "W_SUPPLY", "Structure", "Heavy overhead supply above the pivot",
         fin(f["overhead_supply_pct"]) and f["overhead_supply_pct"] >= 25.0,
         "%.0f%% of the last year's volume traded in the 8%% band above %s%.2f - "
         "trapped holders will sell into the breakout"
         % (f["overhead_supply_pct"], "₹", f["pivot"])
         if fin(f["overhead_supply_pct"]) else "")

    # Depth alone is not the problem - the stop is set from the recent swing low and
    # ATR, not the base low. What hurts is a deep base whose closes are still choppy,
    # i.e. price is swinging inside the range rather than coiling at the top of it.
    warn(card, "W_DEEP", "Structure", "Base is wide and still choppy",
         (fin(f["base_depth_pct"]) and f["base_depth_pct"] > 20.0
          and fin(f["base_tightness_pct"]) and f["base_tightness_pct"] > 2.5),
         "%.1f%% deep over %d bars and the last 10 closes still vary %.2f%% - price is "
         "swinging inside the range rather than coiling under the level"
         % (f["base_depth_pct"], f["base_len"], f["base_tightness_pct"]))

    warn(card, "W_DEATH", "Trend", "50-day average is rolling toward the 200-day",
         (fin(f["golden_gap_pct"]) and 0 < f["golden_gap_pct"] < s.wk_death_cross_gap
          and fin(f["sma50_slope"]) and f["sma50_slope"] < 0),
         "SMA50 only %.1f%% above SMA200 and falling" % f["golden_gap_pct"]
         if fin(f["golden_gap_pct"]) else "")

    warn(card, "W_GAPDN", "Risk", "Recent gap down",
         fin(f["gap_pct"]) and f["gap_pct"] < -5.0,
         "gapped %.1f%% lower on the latest bar" % f["gap_pct"] if fin(f["gap_pct"]) else "")

    warn(card, "W_RSDOWN", "Relative strength", "Lagging the market",
         fin(f["rs20"]) and f["rs20"] < -3.0,
         "20d relative return %+.1f%% vs Nifty 500" % f["rs20"] if fin(f["rs20"]) else "")

    warn(card, "W_DIVERGE", "Momentum", "Bearish RSI divergence",
         bool(f["rsi_div_bear"]),
         f["rsi_div_detail"] or "price making higher highs on weakening momentum")

    warn(card, "W_STALE", "Structure", "Resistance level is old",
         f["pivot_age"] > 90,
         "the pivot high was printed %d bars ago; the level may no longer be defended"
         % f["pivot_age"])


def minervini_template(f: dict) -> dict:
    """The classic 8-point stage-2 uptrend checklist."""
    c = f["close"]
    checks = [
        ("above SMA150", fin(f["sma150"]) and c > f["sma150"]),
        ("above SMA200", fin(f["sma200"]) and c > f["sma200"]),
        ("SMA150 above SMA200", fin(f["sma150"]) and fin(f["sma200"])
         and f["sma150"] > f["sma200"]),
        ("SMA200 rising", fin(f["sma200_slope"]) and f["sma200_slope"] > 0),
        ("SMA50 above SMA150", fin(f["sma50"]) and fin(f["sma150"])
         and f["sma50"] > f["sma150"]),
        ("price above SMA50", fin(f["sma50"]) and c > f["sma50"]),
        ("30%+ above 52w low", fin(f["above_52w_low_pct"]) and f["above_52w_low_pct"] >= 30),
        ("within 25% of 52w high", fin(f["off_52w_high_pct"]) and f["off_52w_high_pct"] <= 25),
    ]
    passed = [n for n, ok in checks if ok]
    failed = [n for n, ok in checks if not ok]
    return {"passed": len(passed), "total": len(checks),
            "summary": ("all conditions met" if not failed
                        else "missing " + ", ".join(failed))}


# ================================================================== TAB 2: broken out
def breakout_gates(card: ScoreCard, f: dict, s) -> bool:
    ok = liquidity_gates(card, f, s)
    bo = f.get("breakout")

    ok &= gate(card, "BO_EVENT", "Structure", "A breakout occurred recently",
               bo is not None,
               ("cleared %s%.2f on %s (%d session%s ago)"
                % ("₹", bo["pivot"], bo["date"].strftime("%d %b %Y"),
                   bo["days_since"], "" if bo["days_since"] == 1 else "s")) if bo
               else "no bar in the last %d sessions cleared a valid base"
                    % s.bo_lookback_days)
    if bo is None:
        return False

    ok &= gate(card, "BO_CLEAR", "Structure", "Cleared the pivot decisively",
               bo["clear_pct"] >= s.bo_min_close_above_pivot,
               "closed %+.2f%% through the pivot (min %.1f%%)"
               % (bo["clear_pct"], s.bo_min_close_above_pivot))

    still = f["close"] > bo["pivot"]
    ok &= gate(card, "BO_HOLD", "Structure", "Still holding above the pivot",
               bool(still),
               "close %s%.2f vs pivot %s%.2f (%+.2f%%)"
               % ("₹", f["close"], "₹", bo["pivot"],
                  (f["close"] - bo["pivot"]) / bo["pivot"] * 100.0))

    if s.bo_require_volume:
        ok &= gate(card, "BO_VOL", "Volume", "Breakout confirmed by volume",
                   fin(bo["rvol"]) and bo["rvol"] >= s.bo_min_breakout_volume,
                   "breakout-day volume %.2fx the 50-day average (min %.1fx) - "
                   "a break on average volume is the commonest failure mode"
                   % (bo["rvol"] if fin(bo["rvol"]) else 0.0, s.bo_min_breakout_volume))

    ok &= gate(card, "BO_TREND", "Trend", "Trend structure intact",
               bool(f["above_sma50"] and f["above_sma200"]),
               "close %s SMA50 and %s SMA200"
               % ("above" if f["above_sma50"] else "below",
                  "above" if f["above_sma200"] else "below"))
    return bool(ok)


def breakout_signals(card: ScoreCard, f: dict, s) -> None:
    bo = f["breakout"]

    scored(card, "BO_RVOL", "Volume", "Volume surge on the breakout",
           ramp(bo["rvol"], 1.0, 3.0), 18.0,
           "%.2fx the 50-day average volume on the breakout bar" % bo["rvol"]
           if fin(bo["rvol"]) else "breakout volume unavailable")

    scored(card, "BO_CLOSE", "Structure", "Closed strong on the breakout bar",
           ramp(bo["close_range_pos"], 0.4, 0.95), 8.0,
           "closed at %.0f%% of that day's range (buyers held the highs into the bell)"
           % (bo["close_range_pos"] * 100) if fin(bo["close_range_pos"])
           else "range position unavailable")

    ext = (f["close"] - bo["pivot"]) / bo["pivot"] * 100.0
    scored(card, "BO_FOLLOW", "Structure", "Holding and following through",
           0.5 * ramp(ext, -0.5, 6.0) + 0.5 * ramp(bo["days_since"], 0, 3), 10.0,
           "%+.2f%% above the pivot, %d session(s) after the break"
           % (ext, bo["days_since"]))

    scored(card, "BO_FRESH", "Structure", "Entry still timely",
           ramp(ext, s.bo_max_extension, 1.0), 8.0,
           "%+.2f%% past the pivot (chase risk beyond %.0f%%)" % (ext, s.bo_max_extension))

    postvol = 0.5 * ramp(f["updown_vol"], 0.8, 1.8) + 0.5 * ramp(-f["dist_days_10"], -4, 0)
    scored(card, "BO_POSTVOL", "Volume", "Healthy volume behaviour since the break",
           postvol, 10.0,
           "up/down volume %.2f; %d distribution day(s) in the last 10"
           % (f["updown_vol"] if fin(f["updown_vol"]) else 0.0, f["dist_days_10"]))

    rs_credit = 0.6 * ramp(f["rs60"], -2.0, 25.0) + (0.4 if f["rs_line_at_high"] else 0.0)
    scored(card, "BO_RS", "Relative strength", "Leading the market",
           rs_credit, 12.0,
           "60d relative return %+.1f%%; RS line %s"
           % (f["rs60"] if fin(f["rs60"]) else 0.0,
              "at a 60-day high" if f["rs_line_at_high"] else "not at a new high"))

    newhigh = 1.0 if f["at_all_time_high"] else (0.7 if f["at_52w_high"] else
                                                ramp(-f["off_52w_high_pct"], -20.0, -2.0))
    scored(card, "BO_HIGH", "Trend", "Breaking into new-high territory",
           newhigh, 8.0,
           "%.1f%% below the 52-week high%s"
           % (f["off_52w_high_pct"],
              "; at all-time highs (no overhead supply at all)" if f["at_all_time_high"]
              else "; at 52-week highs" if f["at_52w_high"] else ""))

    adx_credit = 0.6 * ramp(f["adx"], 15.0, 30.0)
    if fin(f["di_plus"]) and fin(f["di_minus"]) and f["di_plus"] > f["di_minus"]:
        adx_credit += 0.4
    scored(card, "BO_ADX", "Momentum", "Trend strength expanding",
           adx_credit, 6.0,
           "ADX %.1f (slope %+.2f), DI+ %.1f vs DI- %.1f"
           % (f["adx"], f["adx_slope"] if fin(f["adx_slope"]) else 0.0,
              f["di_plus"], f["di_minus"]) if fin(f["adx"]) else "ADX unavailable")

    mom = 0.0
    if fin(f["macd_hist"]) and f["macd_hist"] > 0:
        mom += 0.5
        if not f["macd_hist_falling"]:
            mom += 0.2
    if fin(f["rsi"]) and 55 <= f["rsi"] <= 80:
        mom += 0.3
    scored(card, "BO_MOM", "Momentum", "Momentum confirming, not exhausted",
           mom, 6.0,
           "MACD histogram %+.3f (%s), RSI %.1f"
           % (f["macd_hist"] if fin(f["macd_hist"]) else 0.0,
              "falling" if f["macd_hist_falling"] else "rising",
              f["rsi"] if fin(f["rsi"]) else 0.0))

    scored(card, "BO_STACK", "Trend", "Moving averages aligned",
           1.0 if f["ma_stack"] else (0.5 if f["above_sma50"] else 0.0), 8.0,
           "close %s EMA20 %s SMA50 %s SMA200" %
           (">" if f["close"] > f["ema20"] else "<",
            ">" if f["ema20"] > f["sma50"] else "<",
            ">" if f["sma50"] > f["sma200"] else "<"))

    gapq = 1.0
    if fin(bo["gap_pct"]):
        if bo["gap_pct"] > 5.0:
            gapq = 0.3          # a big gap is an exhaustion risk, not a gift
        elif bo["gap_pct"] > 1.0:
            gapq = 0.8
    scored(card, "BO_GAP", "Structure", "Breakout not a runaway gap",
           gapq, 4.0,
           "opened %+.2f%% versus the prior close" % bo["gap_pct"]
           if fin(bo["gap_pct"]) else "gap unavailable")

    scored(card, "BO_TURN", "Volume", "Participation expanding",
           ramp(f["rvol"], 0.7, 1.8), 4.0,
           "latest volume %.2fx the 50-day average" % f["rvol"]
           if fin(f["rvol"]) else "volume unavailable")


def breakout_warnings(card: ScoreCard, f: dict, s) -> None:
    bo = f["breakout"]
    ext = (f["close"] - bo["pivot"]) / bo["pivot"] * 100.0

    warn(card, "BW_WEAKVOL", "Volume", "Breakout volume was unconvincing",
         fin(bo["rvol"]) and bo["rvol"] < s.bo_min_breakout_volume,
         "%.2fx average versus the %.1fx benchmark" % (bo["rvol"], s.bo_min_breakout_volume)
         if fin(bo["rvol"]) else "")

    warn(card, "BW_WICK", "Structure", "Breakout bar closed weakly",
         fin(bo["close_range_pos"]) and bo["close_range_pos"] < s.bo_min_close_range_pos,
         "closed at only %.0f%% of the breakout day's range" % (bo["close_range_pos"] * 100)
         if fin(bo["close_range_pos"]) else "")

    warn(card, "BW_EXT", "Risk", "Extended from the pivot - chase risk",
         ext > s.bo_max_extension,
         "%+.1f%% past the pivot; wait for a pullback to the 20-day EMA" % ext)

    warn(card, "BW_ATREXT", "Risk", "Stretched from the 20-day EMA",
         fin(f["atr_above_ema20"]) and f["atr_above_ema20"] > s.bo_max_atr_extension,
         "%.1f ATRs above the EMA20" % f["atr_above_ema20"]
         if fin(f["atr_above_ema20"]) else "")

    warn(card, "BW_CLIMAX", "Risk", "Climax risk",
         fin(f["rsi"]) and f["rsi"] > s.bo_max_rsi,
         "RSI %.1f above %.0f with a %.1f%% 10-day gain"
         % (f["rsi"], s.bo_max_rsi, f["roc10"] if fin(f["roc10"]) else 0.0))

    warn(card, "BW_DIST", "Volume", "Distribution since the breakout",
         f["dist_days_10"] >= s.bo_max_distribution_days,
         "%d distribution days in the last 10 sessions" % f["dist_days_10"])

    warn(card, "BW_SUPPLY", "Structure", "Overhead supply still above",
         fin(f["overhead_supply_pct"]) and f["overhead_supply_pct"] >= 25.0,
         "%.0f%% of yearly volume sits in the 8%% band above the pivot"
         % f["overhead_supply_pct"] if fin(f["overhead_supply_pct"]) else "")

    warn(card, "BW_DIVERGE", "Momentum", "Bearish momentum divergence already",
         bool(f["rsi_div_bear"]), f["rsi_div_detail"] or "")


def breakout_status(f: dict, s) -> str:
    bo = f["breakout"]
    ext = (f["close"] - bo["pivot"]) / bo["pivot"] * 100.0
    if f["close"] < bo["pivot"]:
        return "Failed"
    if ext > s.bo_max_extension:
        return "Extended"
    if bo["days_since"] <= 2:
        return "Fresh"
    return "Holding"


# ================================================================== TAB 3: weakening
#  Each entry is (id, category, label, points, predicate, detail-builder).
#  Risk score = min(100, sum of triggered points).
def weakening_signals(card: ScoreCard, f: dict, s) -> tuple[float, list]:
    tripped: list = []

    def risk(sid, cat, label, points, cond, detail):
        points = WGT.resolve(sid, points)
        if cond:
            sig = Signal(sid, cat, label, detail, "warn", points, points)
            card.add(sig)
            tripped.append(sig)
        else:
            card.add(Signal(sid, cat, label, detail, "pass", points, 0.0))

    bo = f.get("breakout")

    risk("WK_RSIDIV", "Momentum", "Bearish RSI divergence", 12.0,
         bool(f["rsi_div_bear"]),
         f["rsi_div_detail"] or "no divergence between price and RSI")

    risk("WK_OBVDIV", "Volume", "Bearish OBV divergence", 10.0,
         bool(f["obv_div_bear"]),
         f["obv_div_detail"] or "on-balance volume is confirming price")

    risk("WK_MACD", "Momentum", "MACD rolled over", 10.0,
         bool(f["macd_bear_cross"]),
         "MACD line %.3f crossed below its signal %.3f within the last 3 sessions"
         % (f["macd_line"], f["macd_signal"]) if f["macd_bear_cross"]
         else "MACD line %.3f vs signal %.3f - no bearish cross"
              % (f["macd_line"] if fin(f["macd_line"]) else 0.0,
                 f["macd_signal"] if fin(f["macd_signal"]) else 0.0))

    risk("WK_MACDFADE", "Momentum", "MACD histogram shrinking while price holds up", 4.0,
         bool(f["macd_hist_falling"] and fin(f["macd_hist"]) and f["macd_hist"] > 0),
         "histogram %+.3f, down from %+.3f - the push is weakening"
         % (f["macd_hist"], f["macd_hist_prev"])
         if fin(f["macd_hist"]) and fin(f["macd_hist_prev"]) else "histogram unavailable")

    risk("WK_DIST", "Volume", "Institutional distribution", 14.0,
         f["dist_days_15"] >= s.wk_min_distribution_days,
         "%d heavy-volume down-closes in the last %d sessions (threshold %d)"
         % (f["dist_days_15"], s.wk_distribution_window, s.wk_min_distribution_days))

    risk("WK_EMA20", "Trend", "Lost the 20-day EMA", 10.0,
         bool(not f["above_ema20"]),
         "close %s%.2f below EMA20 %s%.2f (EMA20 slope %+.3f%%/bar)"
         % ("₹", f["close"], "₹", f["ema20"],
            f["ema20_slope"] if fin(f["ema20_slope"]) else 0.0)
         if not f["above_ema20"]
         else "holding above EMA20 for %d sessions" % f["days_above_ema20"])

    risk("WK_SMA50", "Trend", "Below the 50-day average", 12.0,
         bool(not f["above_sma50"]),
         "close %s%.2f vs SMA50 %s%.2f" % ("₹", f["close"], "₹", f["sma50"])
         if not f["above_sma50"] else "still above SMA50")

    risk("WK_SMA50SLOPE", "Trend", "50-day average turning down", 8.0,
         bool(fin(f["sma50_slope"]) and f["sma50_slope"] < 0),
         "SMA50 slope %+.3f%%/bar over 20 bars" % f["sma50_slope"]
         if fin(f["sma50_slope"]) else "slope unavailable")

    risk("WK_DEATH", "Trend", "Death-cross risk", 10.0,
         bool(fin(f["golden_gap_pct"]) and 0 < f["golden_gap_pct"] < s.wk_death_cross_gap
              and fin(f["sma50_slope"]) and f["sma50_slope"] < 0),
         "SMA50 is only %.2f%% above SMA200 and falling" % f["golden_gap_pct"]
         if fin(f["golden_gap_pct"]) else "gap unavailable")

    risk("WK_LH", "Structure", "Lower swing highs", 8.0,
         bool(f["lower_highs"]),
         "the last two swing highs are descending" if f["lower_highs"]
         else "swing highs are not descending")

    risk("WK_RS", "Relative strength", "Relative strength breaking down", 10.0,
         bool(fin(f["rs20"]) and f["rs20"] < 0),
         "20d relative return %+.1f%% vs Nifty 500 (60d %+.1f%%)"
         % (f["rs20"], f["rs60"] if fin(f["rs60"]) else 0.0)
         if fin(f["rs20"]) else "relative strength unavailable")

    risk("WK_UDVOL", "Volume", "Down days carrying the volume", 8.0,
         bool(fin(f["updown_vol"]) and f["updown_vol"] < s.wk_updown_vol_ratio),
         "up/down volume ratio %.2f over 20 sessions (threshold %.2f)"
         % (f["updown_vol"], s.wk_updown_vol_ratio) if fin(f["updown_vol"])
         else "ratio unavailable")

    risk("WK_CLIMAX", "Risk", "Parabolic / exhaustion move", 12.0,
         bool(f["parabolic"] and fin(f["atr_above_ema20"])
              and f["atr_above_ema20"] > s.wk_parabolic_atr),
         "up %.1f%% in 10 sessions and %.1f ATRs above the EMA20 - vertical moves "
         "mean-revert hard" % (f["roc10"] if fin(f["roc10"]) else 0.0,
                               f["atr_above_ema20"] if fin(f["atr_above_ema20"]) else 0.0))

    risk("WK_FAILBO", "Structure", "Failed breakout", 14.0,
         bool(bo is not None and f["close"] < bo["pivot"]),
         "broke %s%.2f on %s and has closed back below it"
         % ("₹", bo["pivot"], bo["date"].strftime("%d %b")) if bo is not None
         and f["close"] < bo["pivot"] else "no failed breakout in the lookback")

    risk("WK_ADX", "Momentum", "Trend strength fading", 8.0,
         bool((fin(f["adx"]) and fin(f["adx_10ago"]) and f["adx_10ago"] > 35
               and f["adx"] < f["adx_10ago"] - 3)
              or (fin(f["di_plus"]) and fin(f["di_minus"]) and f["di_minus"] > f["di_plus"])),
         "ADX %.1f (was %.1f ten bars ago); DI+ %.1f vs DI- %.1f"
         % (f["adx"] if fin(f["adx"]) else 0.0, f["adx_10ago"] if fin(f["adx_10ago"]) else 0.0,
            f["di_plus"] if fin(f["di_plus"]) else 0.0,
            f["di_minus"] if fin(f["di_minus"]) else 0.0))

    risk("WK_CANDLE", "Structure", "Bearish reversal bar at the highs", 8.0,
         bool(f["shooting_star"] or f["bear_engulfing"] or f["wide_red_bar"]),
         ", ".join([n for n, ok in [("shooting star", f["shooting_star"]),
                                    ("bearish engulfing", f["bear_engulfing"]),
                                    ("wide-range down bar", f["wide_red_bar"])] if ok])
         or "no reversal bar in the last 3 sessions")

    risk("WK_GAPDN", "Risk", "Gap down on volume", 8.0,
         bool(fin(f["gap_pct"]) and f["gap_pct"] < -3.0
              and fin(f["rvol"]) and f["rvol"] > 1.2),
         "gapped %.1f%% lower on %.2fx average volume"
         % (f["gap_pct"], f["rvol"]) if fin(f["gap_pct"]) and fin(f["rvol"])
         else "no volume gap-down")

    risk("WK_DONCHIAN", "Structure", "Broke the 20-day low", 10.0,
         bool(f["below_donchian20"]),
         "close %s%.2f below the 20-day low %s%.2f"
         % ("₹", f["close"], "₹", f["donchian_low20"])
         if f["below_donchian20"] else "holding above the 20-day low")

    risk("WK_CHANNEL", "Structure", "Broke the rising channel", 10.0,
         bool(f["below_channel"]),
         "close %s%.2f below the 60-day regression channel floor %s%.2f"
         % ("₹", f["close"], "₹", f["chan_lower"])
         if f["below_channel"] else "inside the 60-day regression channel")

    total = sum(sig.points for sig in tripped)
    return float(min(100.0, total)), tripped


def severity_of(risk_score: float, n_signals: int) -> str:
    if risk_score >= 65 or n_signals >= 7:
        return "Exit signal"
    if risk_score >= 45:
        return "High risk"
    if risk_score >= 25:
        return "Caution"
    return "Watch"
