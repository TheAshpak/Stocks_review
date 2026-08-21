"""NSE Breakout Scanner - a local Streamlit tool for the Indian market.

Three screens:
  1. About to break out   - stocks coiling under resistance
  2. Broken out & bullish - confirmed breakouts still acting well
  3. Turning non-bullish  - uptrends showing early deterioration

Run with:  streamlit run app.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from core import charts as CH
from core import columns as COL
from core import config as CFG
from core import data as D
from core import features as F
from core import market as MK
from core import rules as R
from core import scanners as SC
from core import universe as U
from core import weights as WGT

st.set_page_config(page_title="NSE Breakout Scanner", page_icon="📈",
                   layout="wide", initial_sidebar_state="expanded")

CAT_ICON = {"Trend": "📈", "Volatility": "🎯", "Volume": "📊", "Structure": "🏗️",
            "Momentum": "⚡", "Relative strength": "🥇", "Liquidity": "💧", "Risk": "⚠️"}

st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; padding-bottom: 3rem;}
  div[data-testid="stMetricValue"] {font-size: 1.35rem;}
  .reason {padding: 2px 0; font-size: 0.9rem;}
  .pill {display:inline-block; padding:1px 8px; border-radius:10px; font-size:0.75rem;
         font-weight:600; margin-right:6px;}
</style>
""", unsafe_allow_html=True)


# ==================================================================== sidebar
def sidebar() -> tuple:
    st.sidebar.title("📈 NSE Breakout Scanner")
    st.sidebar.caption("Daily EOD screening for NSE equities. Educational tool - "
                       "not investment advice.")

    uni = st.sidebar.selectbox("Universe", list(U.UNIVERSES),
                               index=list(U.UNIVERSES).index("Nifty 500"))
    cap = st.sidebar.slider("Cap universe size (0 = no cap)", 0, 2500, 0, 50,
                            help="Scan only the first N symbols. Useful for a fast "
                                 "first look before committing to the full list.")
    preset_name = st.sidebar.radio("Strictness preset", ["Strict", "Balanced", "Loose"],
                                   index=1, horizontal=True)
    s = CFG.preset(preset_name)

    with st.sidebar.expander("Liquidity filters (all tabs)"):
        s = CFG.override(
            s,
            min_price=st.number_input("Minimum price (₹)", 1.0, 5000.0,
                                      float(s.min_price), 5.0),
            min_avg_volume=st.number_input("Min 20d average volume", 0, 10_000_000,
                                           int(s.min_avg_volume), 50_000),
            min_turnover_cr=st.number_input("Min 20d median turnover (₹ cr)", 0.0, 500.0,
                                            float(s.min_turnover_cr), 0.5),
        )

    with st.sidebar.expander("Tab 1 - about to break out"):
        s = CFG.override(
            s,
            pb_max_dist_to_pivot=st.slider("Max distance to pivot (%)", 0.5, 12.0,
                                           float(s.pb_max_dist_to_pivot), 0.5),
            pb_min_base_len=st.slider("Min base length (bars)", 8, 60,
                                      int(s.pb_min_base_len), 1),
            pb_max_base_depth=st.slider("Max base depth (%)", 8.0, 45.0,
                                        float(s.pb_max_base_depth), 1.0),
            pb_max_off_52w_high=st.slider("Max % below 52-week high", 5.0, 60.0,
                                          float(s.pb_max_off_52w_high), 1.0),
            pb_min_prior_leg=st.slider("Min prior advance into base (%)", 0.0, 60.0,
                                       float(s.pb_min_prior_leg), 5.0),
            pb_atr_compression=st.slider("ATR compression target (now ÷ 40 bars ago)",
                                         0.40, 1.20, float(s.pb_atr_compression), 0.05),
            pb_vol_dryup=st.slider("Volume dry-up target (10d ÷ 50d)", 0.40, 1.20,
                                   float(s.pb_vol_dryup), 0.05),
            pb_min_rsi=st.slider("Min RSI(14)", 20.0, 70.0, float(s.pb_min_rsi), 1.0),
            pb_min_score=st.slider("Min setup score", 0.0, 95.0,
                                   float(s.pb_min_score), 5.0),
            pb_require_above_sma200=st.checkbox("Require close above SMA200",
                                                bool(s.pb_require_above_sma200)),
        )

    with st.sidebar.expander("Tab 2 - broken out & bullish"):
        s = CFG.override(
            s,
            bo_lookback_days=st.slider("Breakout within last N sessions", 1, 30,
                                       int(s.bo_lookback_days), 1),
            bo_min_breakout_volume=st.slider("Min breakout volume (× 50d avg)", 1.0, 4.0,
                                             float(s.bo_min_breakout_volume), 0.1),
            bo_require_volume=st.checkbox("Volume confirmation is a hard requirement",
                                          bool(s.bo_require_volume)),
            bo_max_extension=st.slider("Max % above pivot before 'extended'", 3.0, 40.0,
                                       float(s.bo_max_extension), 1.0),
            bo_min_score=st.slider("Min breakout score", 0.0, 95.0,
                                   float(s.bo_min_score), 5.0),
        )

    with st.sidebar.expander("Tab 3 - turning non-bullish"):
        s = CFG.override(
            s,
            wk_min_signals=st.slider("Min deterioration signals", 1, 8,
                                     int(s.wk_min_signals), 1),
            wk_min_risk_score=st.slider("Min risk score", 0.0, 90.0,
                                        float(s.wk_min_risk_score), 5.0),
            wk_min_distribution_days=st.slider("Distribution days that count as heavy",
                                               1, 8, int(s.wk_min_distribution_days), 1),
        )

    with st.sidebar.expander("Market regime"):
        s = CFG.override(
            s,
            regime_scales_score=st.checkbox("Let the market regime scale scores",
                                            bool(s.regime_scales_score)),
        )

    with st.sidebar.expander("Advanced — how the base is chosen"):
        choice = st.radio(
            "Which consolidation defines the pivot?",
            ["Most significant level", "Tightest recent base"],
            index=0,
            help="Significant level takes the longest qualifying consolidation, so the "
                 "pivot is a major multi-month high — bigger measured-move targets and "
                 "better reward:risk. Tightest base takes the narrowest recent box, "
                 "which surfaces bull flags and short coils with closer stops but "
                 "smaller targets.")
        s = CFG.override(
            s,
            base_select="longest" if choice == "Most significant level" else "quality",
        )

    if WGT.available():
        with st.sidebar.expander("Rule weights"):
            _w, _meta = WGT.load(install=False)
            mode = st.radio("Which weight set scores the setups?",
                            ["Conventional", "Backtest-fitted"], index=0,
                            help="Conventional weights encode standard breakout practice. "
                                 "Fitted weights come from the walk-forward backtest in "
                                 "backtest/ — they are only written to disk when they beat "
                                 "the conventional set out-of-sample. See BACKTEST.md.")
            s = CFG.override(s, weights_mode="fitted" if mode == "Backtest-fitted"
                             else "conventional")
            if _meta:
                st.caption("fitted set covers: %s"
                           % ", ".join(_meta.get("scanners", [])) or "n/a")

    st.sidebar.divider()
    run = st.sidebar.button("▶ Run scan", type="primary", width="stretch")
    refresh = st.sidebar.button("⟳ Re-download prices (slow)", width="stretch")
    return uni, cap, s, run, refresh


# ==================================================================== scan driver
def run_scan(uni: str, cap: int, s, refresh: bool) -> None:
    prog = st.progress(0.0, text="starting…")

    symbols, meta, note = U.get_universe(uni, refresh=refresh)
    if cap and cap < len(symbols):
        symbols = symbols[:cap]
        meta = meta.head(cap)
    prog.progress(0.05, text=f"universe: {len(symbols)} symbols ({note})")

    def dl(frac, msg):
        prog.progress(0.05 + 0.55 * frac, text=f"prices: {msg}")

    prices, info = D.load_prices(uni, symbols, period="2y", refresh=refresh,
                                 progress_cb=dl)
    if not prices:
        prog.empty()
        st.error("No price data could be loaded. Check the internet connection and "
                 "try ⟳ Re-download prices.")
        return

    bench_df = D.load_index(U.BENCHMARK, refresh=refresh)
    bench = bench_df["Close"] if len(bench_df) else None

    def an(frac, msg):
        prog.progress(0.60 + 0.35 * frac, text=f"analysis: {msg}")

    feats, skipped = F.bulk_features(prices, bench, s, progress_cb=an)
    prog.progress(0.97, text="assessing market regime…")
    regime = MK.assess(feats, s, refresh=refresh)

    st.session_state.update(
        prices=prices, feats=feats, meta=meta, regime=regime, settings=s,
        info=info, note=note, skipped=skipped, universe=uni, bench=bench,
        n_symbols=len(symbols),
    )
    prog.progress(1.0, text="done")
    prog.empty()


# Settings that feed the feature engine itself. Changing any of these invalidates the
# cached features, so the scanners alone are not enough - the features must be rebuilt
# (from cached prices, so it costs seconds, not a download).
FEATURE_KEYS = ("min_bars", "pb_min_base_len", "pb_max_base_len", "pb_max_base_depth",
                "pb_pivot_tolerance", "bo_lookback_days", "base_select")


def _feature_key(s) -> tuple:
    return tuple(getattr(s, k) for k in FEATURE_KEYS)


def rescan(s) -> None:
    """Re-apply the regime and scanners to cached features (no re-download)."""
    # weights affect scoring only, never the features, so this belongs here
    if getattr(s, "weights_mode", "conventional") == "fitted":
        WGT.load()
    else:
        WGT.clear()
    feats, meta = st.session_state["feats"], st.session_state["meta"]
    regime = MK.assess(feats, s)
    st.session_state["regime"] = regime
    st.session_state["pb"] = SC.scan_pre_breakout(feats, s, regime, meta)
    st.session_state["bo"] = SC.scan_breakouts(feats, s, regime, meta)
    st.session_state["wk"] = SC.scan_weakening(feats, s, regime, meta)
    st.session_state["applied"] = s


def recompute_features(s) -> None:
    """Rebuild features from the cached prices, then rescan."""
    feats, skipped = F.bulk_features(st.session_state["prices"],
                                     st.session_state.get("bench"), s)
    st.session_state["feats"] = feats
    st.session_state["skipped"] = skipped
    st.session_state["fkey"] = _feature_key(s)
    rescan(s)


# ==================================================================== regime banner
def regime_banner(regime: dict) -> None:
    state = regime["state"]
    colour = {"Risk-On": "🟢", "Neutral": "🟡", "Risk-Off": "🔴"}[state]
    idx, br = regime["index"], regime["breadth"]

    c = st.columns([1.25, 1, 1, 1, 1, 1.1])
    c[0].metric(f"{colour} Market regime", state,
                delta=f"score multiplier ×{regime['multiplier']:.2f}",
                delta_color="off")
    c[1].metric("Nifty 50", f"{idx['close']:,.0f}" if np.isfinite(idx["close"]) else "n/a",
                delta=f"{idx['chg_pct']:+.2f}%" if np.isfinite(idx["chg_pct"]) else None)
    c[2].metric("India VIX", f"{regime['vix']:.1f}" if np.isfinite(regime["vix"]) else "n/a",
                delta=f"{regime['vix_chg']:+.1f}% (5d)"
                if np.isfinite(regime["vix_chg"]) else None, delta_color="inverse")
    c[3].metric("Above 50-DMA", f"{br['above_sma50']:.0f}%"
                if np.isfinite(br["above_sma50"]) else "n/a", help="Market breadth")
    c[4].metric("Above 200-DMA", f"{br['above_sma200']:.0f}%"
                if np.isfinite(br["above_sma200"]) else "n/a")
    c[5].metric("Advancing today", f"{br['advancing']:.0f}%"
                if np.isfinite(br["advancing"]) else "n/a")

    with st.expander(f"Why the regime is **{state}** — {regime['note']}"):
        for e in regime["evidence"]:
            st.markdown(f"- {e}")
        st.caption("Breakout failure rates rise when the index is below its own moving "
                   "averages and participation narrows. In Risk-Off every score is cut "
                   "15%; in Risk-On it is lifted 5%. Toggle this off in the sidebar.")


# ==================================================================== reason panel
def reason_panel(card: R.ScoreCard, kind: str = "score") -> None:
    if kind == "risk":
        tripped = [x for x in card.signals if x.status == "warn"]
        clean = [x for x in card.signals if x.status == "pass" and x.weight > 0]
        st.markdown(f"**{len(tripped)} deterioration signal(s) triggered** — "
                    f"risk score {card.score:.0f}/100 ({card.grade})")
        for sig in sorted(tripped, key=lambda x: -x.points):
            st.markdown(f"<div class='reason'>🔴 <b>{CAT_ICON.get(sig.category,'')} "
                        f"{sig.label}</b> <code>+{sig.points:.0f}</code><br>"
                        f"<span style='color:#64748b'>{sig.detail}</span></div>",
                        unsafe_allow_html=True)
        if clean:
            with st.expander(f"{len(clean)} checks that are still healthy"):
                for sig in clean:
                    st.markdown(f"<div class='reason'>🟢 {sig.label} — "
                                f"<span style='color:#64748b'>{sig.detail}</span></div>",
                                unsafe_allow_html=True)
        return

    passes, misses, warns = card.passes, card.misses, card.warnings
    gates = [x for x in card.signals if x.weight == 0 and x.status == "pass"]

    st.markdown(f"**Score {card.score:.1f}/100 · grade {card.grade}** "
                f"— {len(passes)} supporting factors, {len(warns)} warning(s)")

    st.markdown("##### ✅ Why it qualified")
    for sig in sorted(passes, key=lambda x: -x.points):
        pct = sig.points / sig.weight * 100 if sig.weight else 0
        st.markdown(f"<div class='reason'>✓ <b>{CAT_ICON.get(sig.category,'')} "
                    f"{sig.label}</b> "
                    f"<code>{sig.points:.1f}/{sig.weight:.0f} pts ({pct:.0f}%)</code><br>"
                    f"<span style='color:#64748b'>{sig.detail}</span></div>",
                    unsafe_allow_html=True)

    if warns:
        st.markdown("##### ⚠️ Warnings — read these before entering")
        for sig in warns:
            st.markdown(f"<div class='reason'>⚠️ <b>{sig.label}</b><br>"
                        f"<span style='color:#92400e'>{sig.detail}</span></div>",
                        unsafe_allow_html=True)

    if misses:
        with st.expander(f"❌ {len(misses)} quality factor(s) it scored poorly on"):
            for sig in misses:
                st.markdown(f"<div class='reason'>✗ <b>{sig.label}</b> "
                            f"<code>{sig.points:.1f}/{sig.weight:.0f}</code><br>"
                            f"<span style='color:#64748b'>{sig.detail}</span></div>",
                            unsafe_allow_html=True)

    if gates:
        with st.expander(f"🔒 {len(gates)} hard eligibility gate(s) passed"):
            for sig in gates:
                st.markdown(f"<div class='reason'>🔒 <b>{sig.label}</b> — "
                            f"<span style='color:#64748b'>{sig.detail}</span></div>",
                            unsafe_allow_html=True)


def detail_view(sym: str, card: R.ScoreCard, plan: dict | None, kind: str = "score") -> None:
    feats = st.session_state["feats"]
    prices = st.session_state["prices"]
    f = feats[sym]

    left, right = st.columns([1.55, 1])
    with left:
        title = f"{sym} — ₹{f['close']:,.2f}  ({f['chg_pct']:+.2f}%)"
        st.plotly_chart(CH.price_chart(prices[sym], f, plan=plan, title=title),
                        width="stretch", key=f"chart_{kind}_{sym}")
        bench = st.session_state.get("bench")
        if bench is not None:
            st.plotly_chart(CH.rs_chart(prices[sym], bench),
                            width="stretch", key=f"rs_{kind}_{sym}")
    with right:
        if plan:
            m = st.columns(2)
            m[0].metric("Entry", f"₹{plan['entry']:,.2f}")
            m[1].metric("Stop", f"₹{plan['stop']:,.2f}"
                        if np.isfinite(plan["stop"]) else "n/a",
                        delta=f"-{plan['risk_pct']:.2f}% risk"
                        if np.isfinite(plan["risk_pct"]) else None, delta_color="off")
            m2 = st.columns(2)
            m2[0].metric("Target (measured move)",
                         f"₹{plan['target']:,.2f}" if np.isfinite(plan["target"]) else "n/a")
            m2[1].metric("Reward : risk",
                         f"{plan['rr']:.2f} : 1" if np.isfinite(plan["rr"]) else "n/a")
            if np.isfinite(plan.get("risk_pct", np.nan)) and plan["risk_pct"] > 8:
                st.warning(f"Stop is {plan['risk_pct']:.1f}% away — wider than the 8% "
                           f"rule of thumb. Size the position down or wait for a "
                           f"tighter entry.")
        reason_panel(card, kind=kind)


# ==================================================================== table helper
def column_config(df: pd.DataFrame) -> dict:
    """Build per-column tooltips and formats.

    The `help` text renders as a tooltip when the cursor hovers the column header, so
    every non-obvious column can explain itself in place. Definitions live in
    `core/columns.py`.
    """
    cfg: dict = {}
    for c in df.columns:
        kwargs: dict = {}
        if c in COL.HELP:
            kwargs["help"] = COL.HELP[c]
        if c in COL.PINNED:
            kwargs["pinned"] = True
        fmt = COL.FORMAT.get(c)
        if fmt and pd.api.types.is_numeric_dtype(df[c]):
            cfg[c] = st.column_config.NumberColumn(format=fmt, **kwargs)
        elif kwargs:
            cfg[c] = st.column_config.Column(**kwargs)
    return cfg


def result_table(df: pd.DataFrame, cols: list, key: str, height: int = 380):
    """Show a selectable table; returns the selected symbol or None."""
    show = [c for c in cols if c in df.columns]
    view = df[show]
    event = st.dataframe(view, width="stretch", hide_index=True,
                         height=height, on_select="rerun",
                         selection_mode="single-row", key=key,
                         column_config=column_config(view))
    rows = event.selection.rows if event and event.selection else []
    if rows:
        return str(df.iloc[rows[0]]["Symbol"])
    return None


def plain_table(df: pd.DataFrame, height: int | None = None) -> None:
    """A non-selectable table that still carries the column tooltips."""
    kw = {"height": height} if height else {}   # None is not a valid height
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config=column_config(df), **kw)


def download_button(df: pd.DataFrame, name: str, key: str) -> None:
    st.download_button(f"⬇ Download {name} as CSV",
                       df.to_csv(index=False).encode("utf-8"),
                       file_name=name, mime="text/csv", key=key)


# ==================================================================== tabs
def tab_pre_breakout(s) -> None:
    df, cards, rejects = st.session_state["pb"]
    feats = st.session_state["feats"]

    st.subheader("Stocks about to break out")
    st.caption("Price is coiling in a base directly beneath an established resistance "
               "level, with volatility contracting and volume drying up. The trigger is "
               "the pivot — nothing is confirmed until price closes through it on "
               "expanding volume.")
    st.info("**What the score here means.** Backtested over 10 years and 13,313 "
            "candidates, this score predicts **whether and how soon** a base gives way "
            "(rank correlation +0.06 with triggering, −0.08 with days-to-trigger) — but "
            "it carries **no information about whether the breakout will pay** "
            "(−0.0003 against the R multiple once triggered). Read it as a readiness "
            "ranking for your watchlist, not a profit forecast, and take the entry "
            "decision from volume on the trigger day. See BACKTEST.md.")

    if df.empty:
        st.info("No stock passed the pre-breakout gates with the current settings. "
                f"{len(rejects)} were rejected — expand the rejection log below to see "
                "why, or relax the sidebar thresholds (distance to pivot and minimum "
                "score are the usual culprits).")
    else:
        c = st.columns(5)
        c[0].metric("Candidates", len(df))
        c[1].metric("Grade A / A+", int((df["Grade"].isin(["A", "A+"])).sum()))
        c[2].metric("Median distance to pivot", f"{df['To pivot %'].median():.2f}%")
        c[3].metric("Median R:R", f"{df['R:R'].median():.2f}"
                    if df["R:R"].notna().any() else "n/a")
        c[4].metric("With warnings", int((df["Warnings"] > 0).sum()))

        fc = st.columns([1, 1, 1, 2])
        min_score = fc[0].slider("Min score", 0, 100, 0, 5, key="pb_ms")
        max_dist = fc[1].slider("Max % to pivot", 0.0,
                                float(max(df["To pivot %"].max(), 1.0)),
                                float(max(df["To pivot %"].max(), 1.0)), 0.25,
                                key="pb_md")
        hide_warn = fc[2].checkbox("Hide setups with warnings", False, key="pb_hw")
        pats = sorted(df["Pattern"].unique())
        chosen = fc[3].multiselect("Patterns", pats, pats, key="pb_pat")

        v = df[(df["Score"] >= min_score) & (df["To pivot %"] <= max_dist)
               & (df["Pattern"].isin(chosen))]
        if hide_warn:
            v = v[v["Warnings"] == 0]

        st.markdown(f"**{len(v)} of {len(df)} shown** — click any row for the full "
                    f"reasoning and chart, or hover a column header for what it means.")
        cols = ["Symbol", "Company", "Score", "Grade", "Close", "Pivot", "To pivot %",
                "Pattern", "Base bars", "Base depth %", "Touches", "ATR compr",
                "Vol dryup", "RS 60d %", "RSI", "Entry >", "Stop", "Target", "Risk %",
                "R:R", "Warnings", "Industry"]
        sel = result_table(v, cols, "pb_table")
        download_button(v, "pre_breakout_candidates.csv", "pb_dl")

        if sel:
            st.divider()
            plan = SC._plan_prebreakout(feats[sel])
            detail_view(sel, cards[sel], plan, kind="pb")

    with st.expander(f"🚫 Rejection log — {len(rejects)} symbols filtered out"):
        if len(rejects):
            st.caption("The first gate each symbol failed. This is the audit trail: "
                       "nothing is silently dropped.")
            plain_table(rejects["Failed gate"].value_counts().rename_axis("Gate")
                        .reset_index(name="Symbols rejected"))
            plain_table(rejects, height=260)


def tab_breakouts(s) -> None:
    df, cards, rejects, failed = st.session_state["bo"]
    feats = st.session_state["feats"]

    st.subheader("Stocks that have broken out and are bullish")
    st.caption("A bar within the lookback window closed decisively through a base built "
               "*before* it, on expanding volume, and price is still holding above that "
               "level with the moving-average structure intact.")

    if df.empty:
        st.info("No confirmed breakout passed the gates. "
                f"{len(rejects)} symbols were rejected — the commonest reason is simply "
                "that no bar cleared a valid base in the lookback window.")
    else:
        c = st.columns(5)
        c[0].metric("Confirmed breakouts", len(df))
        c[1].metric("Fresh (≤2 sessions)", int((df["Status"] == "Fresh").sum()))
        c[2].metric("Extended", int((df["Status"] == "Extended").sum()))
        c[3].metric("Median breakout volume", f"{df['BO volume x'].median():.2f}×"
                    if df["BO volume x"].notna().any() else "n/a")
        c[4].metric("At/near 52w high",
                    int((df["Off 52w high %"] <= 2).sum()))

        fc = st.columns([1, 1, 1, 1])
        min_score = fc[0].slider("Min score", 0, 100, 0, 5, key="bo_ms")
        statuses = fc[1].multiselect("Status", sorted(df["Status"].unique()),
                                     sorted(df["Status"].unique()), key="bo_st")
        min_vol = fc[2].slider("Min breakout volume ×", 0.0, 6.0, 0.0, 0.1, key="bo_mv")
        max_ext = fc[3].slider("Max % above pivot", 0.0,
                               float(max(df["Above pivot %"].max(), 1.0)),
                               float(max(df["Above pivot %"].max(), 1.0)), 0.5,
                               key="bo_me")

        v = df[(df["Score"] >= min_score) & (df["Status"].isin(statuses))
               & (df["Above pivot %"] <= max_ext)
               & (df["BO volume x"].fillna(0) >= min_vol)]

        st.markdown(f"**{len(v)} of {len(df)} shown** — click any row for the full "
                    f"reasoning and chart, or hover a column header for what it means.")
        cols = ["Symbol", "Company", "Score", "Grade", "Status", "Close", "Pivot",
                "Above pivot %", "BO date", "Days since", "BO volume x", "BO close pos",
                "Base bars", "Pattern", "RS 60d %", "RSI", "ADX", "Entry", "Stop",
                "Trail (EMA20)", "Target", "Risk %", "R:R", "Warnings", "Industry"]
        sel = result_table(v, cols, "bo_table")
        download_button(v, "confirmed_breakouts.csv", "bo_dl")

        if sel:
            st.divider()
            plan = SC._plan_breakout(feats[sel])
            detail_view(sel, cards[sel], plan, kind="bo")

    st.divider()
    st.markdown("#### ❌ Failed breakouts — what not to buy")
    st.caption("These cleared a level and then closed back below it. Kept visible on "
               "purpose: a failed breakout is the fastest way to learn which volume "
               "signatures do not hold, and it often precedes a sharp reversal.")
    if len(failed):
        plain_table(failed, height=240)
        download_button(failed, "failed_breakouts.csv", "fail_dl")
    else:
        st.success("No failed breakouts in the lookback window.")

    with st.expander(f"🚫 Rejection log — {len(rejects)} symbols filtered out"):
        if len(rejects):
            plain_table(rejects["Failed gate"].value_counts().rename_axis("Gate")
                        .reset_index(name="Symbols rejected"))
            plain_table(rejects, height=260)


def tab_weakening(s) -> None:
    df, cards, skipped = st.session_state["wk"]

    st.subheader("Stocks about to turn non-bullish")
    st.caption("Only stocks **still** in an uptrend are considered — the point is to "
               "catch the turn while there is profit to protect. Signals are weighted "
               "and summed into a risk score; the stage tells you how far the damage "
               "has already spread.")

    if df.empty:
        st.info("No stock in an uptrend is showing enough deterioration to flag.")
    else:
        c = st.columns(5)
        c[0].metric("Flagged", len(df))
        c[1].metric("Exit signals", int((df["Severity"] == "Exit signal").sum()))
        c[2].metric("High risk", int((df["Severity"] == "High risk").sum()))
        c[3].metric("Early warnings", int((df["Stage"] == "Early warning").sum()))
        c[4].metric("Median risk score", f"{df['Risk score'].median():.0f}")

        st.info("**Early warning** is the cohort worth acting on: still above the "
                "20-EMA and 50-SMA, so the chart looks fine, while divergences and "
                "distribution build underneath. **Breaking down** names have already "
                "lost the 50-SMA — the market has noticed.")

        fc = st.columns([1.4, 1.2, 1])
        stages = fc[0].multiselect("Stage", SC.WEAKENING_STAGES, SC.WEAKENING_STAGES,
                                   key="wk_stage")
        sevs = fc[1].multiselect("Severity",
                                 ["Exit signal", "High risk", "Caution", "Watch"],
                                 ["Exit signal", "High risk", "Caution", "Watch"],
                                 key="wk_sev")
        min_sig = fc[2].slider("Min signals", 1, 10, int(s.wk_min_signals), 1,
                               key="wk_msig")

        v = df[df["Stage"].isin(stages) & df["Severity"].isin(sevs)
               & (df["Signals"] >= min_sig)]

        st.markdown(f"**{len(v)} of {len(df)} shown** — click any row for every "
                    f"signal that fired, or hover a column header for what it means.")
        cols = ["Symbol", "Company", "Risk score", "Severity", "Stage", "Signals",
                "Close", "Chg %", "Key signals", "vs EMA20 %", "vs SMA50 %",
                "vs SMA200 %", "Days above EMA20", "Dist days (15)", "RS 20d %", "RSI",
                "Suggested stop", "Off 52w high %", "Industry"]
        sel = result_table(v, cols, "wk_table", height=420)
        download_button(v, "weakening_stocks.csv", "wk_dl")

        if sel:
            st.divider()
            detail_view(sel, cards[sel], None, kind="wk")

    with st.expander(f"ℹ️ {len(skipped)} symbols excluded as already bearish"):
        if len(skipped):
            st.caption("Below both the 50- and 200-day averages: these are downtrends, "
                       "not turns, so they belong to a different screen.")
            plain_table(skipped, height=240)


def tab_method() -> None:
    st.subheader("Method — every filter, and why it is there")
    st.markdown("""
A breakout is only tradeable when four things line up: **a base** (price consolidated),
**a level** (resistance that has been tested), **contraction** (volatility and volume
drying up inside the base) and **confirmation** (a decisive close through the level on
expanding volume). Anything missing one of those is noise.

Scoring is transparent: each rule contributes `points / weight`, the score is
`100 × Σpoints / Σweights`, and the market regime multiplies the result. Click any row
in any tab to see every rule with the actual numbers it judged.
""")

    st.markdown("#### Shared hard gates (all tabs)")
    st.table(pd.DataFrame([
        ["Minimum price", "Sub-₹30 stocks have spreads that swallow the edge"],
        ["20-day average volume", "An unfillable breakout is not a breakout"],
        ["20-day median turnover (₹ cr)", "Turnover, not share count, decides whether "
                                          "your size moves the price"],
        ["≥250 bars of history", "SMA200, 52-week stats and percentile ranks all need it"],
    ], columns=["Gate", "Why"]))

    st.markdown("#### Tab 1 — about to break out")
    st.markdown("""
**Hard gates:** a valid base exists (window within the depth limit *with price in the
top 45% of it*) · price still below the pivot · within the distance-to-pivot limit ·
base long enough · base not too deep · above SMA200 · near the 52-week high · a prior
advance leads into the base · RSI not broken.

The pivot is computed **excluding the last two bars**, so a fresh spike cannot invent
the level it is supposedly about to break.

**Scored factors** (weight):
- Volatility contraction, ATR% now vs 40 bars ago (12) — the most reliable pre-breakout tell
- Relative strength vs Nifty 500, plus RS line at a 60-day high (12) — leadership shows in RS before price
- Volume dry-up, 10d vs 50d average (10) — sellers exhausted
- Accumulation footprint: accumulation vs distribution days, up/down volume, OBV slope (10)
- Moving-average alignment and slope (10)
- Tight closes, NR7 and inside days (8) · resistance touch count (8) · proximity to trigger (8) · Minervini template (8)
- Bollinger squeeze percentile (6) · successive contractions (6) · higher lows (6) · prior-leg strength (6)
- Base position (4) · ADX coiling with DI+ > DI− (4) · named pattern (4)

**Warnings** (listed, not hidden): volatility expanding · distribution inside the base ·
down-day volume dominant · below EMA20 or SMA50 · heavy overhead supply above the pivot ·
wide loose base · pending death cross · gap down · lagging the market · bearish RSI
divergence · stale resistance level.
""")

    st.markdown("#### Tab 2 — broken out & bullish")
    st.markdown("""
**Hard gates:** a bar in the lookback window cleared a base built *strictly before it* ·
cleared by the minimum margin · price still above that pivot · breakout volume ≥ the
volume multiple (optional hard gate) · above SMA50 and SMA200.

**Scored factors:** breakout volume surge (18) · relative strength (12) · follow-through
above the pivot (10) · post-breakout volume behaviour (10) · close position on the
breakout bar (8) · entry freshness (8) · new-high territory (8) · MA alignment (8) ·
ADX/DI expansion (6) · MACD and RSI healthy but not climactic (6) · gap quality (4) ·
current participation (4).

**Status:** `Fresh` (≤2 sessions) · `Holding` · `Extended` (chase risk) · `Failed`.
Failed breakouts get their own table because they are the cheapest lesson available.
""")

    st.markdown("#### Tab 3 — about to turn non-bullish")
    st.markdown("""
Restricted to stocks still above the 50- or 200-day average. Each signal adds points;
the risk score is the capped sum.

Bearish RSI divergence (12) · failed breakout (14) · institutional distribution (14) ·
below SMA50 (12) · parabolic/exhaustion move (12) · lost the 20-EMA (10) · OBV
divergence (10) · MACD bearish cross (10) · death-cross risk (10) · broke the 20-day
low (10) · broke the rising channel (10) · relative-strength breakdown (10) · SMA50
turning down (8) · lower swing highs (8) · down-day volume dominant (8) · ADX fading or
DI− above DI+ (8) · bearish reversal bar (8) · volume gap-down (8) · MACD histogram
fading (4).

**Severity:** Watch (<25) · Caution (25–44) · High risk (45–64) · Exit signal (≥65 or
≥7 signals).
""")

    st.markdown("#### Known limitations — read this")
    st.warning("""
- **End-of-day data only**, sourced from Yahoo Finance. Not official NSE data, and not
  live: intraday relative volume during market hours is not available here.
- Prices are **split/bonus adjusted**; volume is not adjusted the same way, so relative
  volume around a corporate action can mislead.
- **Earnings dates are not checked.** A breakout the day before results is a coin flip,
  not a setup. Verify the calendar yourself.
- Pattern detection is heuristic. It flags candidates for *your* eyes; it is not a
  substitute for reading the chart.
- No backtest is included, so none of these weights are optimised — they encode
  conventional breakout practice, not a fitted edge.
- Expect roughly a 40–50% hit rate on good setups. Breakout trading pays through
  asymmetry (small stops, trailed winners), not accuracy.
""")
    st.caption("This tool screens and explains. It does not give investment advice, and "
               "position sizing and risk management remain entirely yours.")


# ==================================================================== main
def main() -> None:
    uni, cap, s, run, refresh = sidebar()

    if run or refresh or "feats" not in st.session_state:
        if "feats" not in st.session_state and not (run or refresh):
            st.title("📈 NSE Breakout Scanner")
            st.markdown("""
Three screens for the Indian market, built on daily NSE end-of-day data:

| Tab | What it finds |
|---|---|
| **About to break out** | Bases coiling under established resistance, with volatility and volume contracting |
| **Broken out & bullish** | Confirmed breakouts on expanding volume that are still holding their pivot |
| **Turning non-bullish** | Uptrends showing early deterioration — divergences, distribution, lost averages |

Every recommendation comes with the full list of rules it passed, the numbers behind
each one, and the warnings against it. Nothing is a black box.

Pick a universe and press **▶ Run scan** in the sidebar. The first run on Nifty 500
downloads two years of daily bars for ~500 symbols (roughly a minute); after that the
day's data is cached and rescans are instant.
""")
            st.info("Tip: to try it quickly, set **Cap universe size** to 100 in the "
                    "sidebar before the first scan.")
            return
        with st.spinner("Scanning…"):
            run_scan(uni, cap, s, refresh)
        if "feats" not in st.session_state:
            return
        st.session_state["fkey"] = _feature_key(s)
        rescan(s)

    # settings changed since the last scan -> re-apply without re-downloading
    if st.session_state.get("fkey") != _feature_key(s):
        with st.spinner("Base/lookback settings changed — rebuilding features…"):
            recompute_features(s)
    elif st.session_state.get("applied") != s or "pb" not in st.session_state:
        rescan(s)

    info, note = st.session_state["info"], st.session_state["note"]
    st.title("📈 NSE Breakout Scanner")
    st.caption(f"**{st.session_state['universe']}** · "
               f"{info['loaded']} of {st.session_state['n_symbols']} symbols with data · "
               f"{len(st.session_state['feats'])} analysed · last bar "
               f"**{info['last_bar']}** · prices {info['source']} "
               f"({info['cached_at']}) · universe {note} · preset "
               f"**{s.label}**")

    regime_banner(st.session_state["regime"])
    st.divider()

    pb_n = len(st.session_state["pb"][0])
    bo_n = len(st.session_state["bo"][0])
    wk_n = len(st.session_state["wk"][0])

    # A segmented control rather than st.tabs, deliberately: selecting a table row calls
    # on_select="rerun", and st.tabs resets to the first tab on every rerun - which made
    # the chart unreachable from tabs 2 and 3. This keeps the section in session_state.
    sections = {
        f"🔥 About to break out ({pb_n})": tab_pre_breakout,
        f"🚀 Broken out & bullish ({bo_n})": tab_breakouts,
        f"⚠️ Turning non-bullish ({wk_n})": tab_weakening,
        "📖 Method & rules": None,
    }
    names = list(sections)
    if st.session_state.get("section") not in names:
        st.session_state["section"] = names[0]
    choice = st.segmented_control("View", names, key="section",
                                  label_visibility="collapsed")
    if choice is None:
        choice = st.session_state["section"] = names[0]

    fn = sections[choice]
    if fn is None:
        tab_method()
    else:
        fn(s)

    skipped = st.session_state.get("skipped", {})
    if skipped:
        with st.expander(f"🔍 {len(skipped)} symbols could not be analysed"):
            plain_table(pd.DataFrame([{"Symbol": k, "Reason": v}
                                      for k, v in skipped.items()]), height=240)


if __name__ == "__main__":
    main()
