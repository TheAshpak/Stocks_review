"""Plotly chart builders.

The chart is part of the explanation: the pivot line, the shaded base box and the
breakout bar marker are drawn from the same numbers the rules were scored on, so
what the table claims can be checked by eye in one glance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import indicators as I

UP = "#16a34a"
DOWN = "#dc2626"
PIVOT = "#f59e0b"
HILITE = "#111827"        # near-black outline for the breakout candle/ring
BASE_FILL = "rgba(245, 158, 11, 0.10)"
GRID = "rgba(128,128,128,0.18)"


def price_chart(df: pd.DataFrame, f: dict, bars: int = 220,
                plan: dict | None = None, title: str = "") -> go.Figure:
    """Candles + moving averages + pivot + base box + volume, with the breakout marked."""
    # If the breakout is older than the default window, widen the view so the marked bar
    # is always on screen - a marker off the edge of the chart is worse than none.
    bo_pre = f.get("breakout")
    if bo_pre is not None:
        try:
            pos = df.index.get_loc(bo_pre["date"])
            need = (len(df) - 1 - int(pos)) + 40
            bars = max(bars, min(need, len(df)))
        except Exception:
            pass
    d = df.tail(bars).copy()
    c = df["Close"]
    d["EMA20"] = I.ema(c, 20).tail(bars)
    d["SMA50"] = I.sma(c, 50).tail(bars)
    d["SMA200"] = I.sma(c, 200).tail(bars)
    d["VolSMA50"] = I.sma(df["Volume"], 50).tail(bars)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.74, 0.26])

    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="Price", increasing_line_color=UP, decreasing_line_color=DOWN,
        increasing_fillcolor=UP, decreasing_fillcolor=DOWN, line=dict(width=1)),
        row=1, col=1)

    for col, colour, width in (("EMA20", "#3b82f6", 1.3),
                               ("SMA50", "#a855f7", 1.3),
                               ("SMA200", "#64748b", 1.6)):
        fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, mode="lines",
                                 line=dict(color=colour, width=width),
                                 hovertemplate=col + ": %{y:.2f}<extra></extra>"),
                      row=1, col=1)

    # the base box: exactly the window the scanner measured
    base = f.get("base")
    if base is not None and getattr(base, "valid", False):
        start_pos = max(0, len(df) - base.length)
        x0 = df.index[start_pos]
        if x0 < d.index[0]:
            x0 = d.index[0]
        # plain datetimes: scalar pandas Timestamps break some plotly serialisers
        x0p = pd.Timestamp(x0).to_pydatetime()
        x1p = pd.Timestamp(d.index[-1]).to_pydatetime()
        fig.add_shape(type="rect", xref="x", yref="y", x0=x0p, x1=x1p,
                      y0=base.low, y1=base.high, fillcolor=BASE_FILL,
                      line=dict(color=PIVOT, width=1, dash="dot"), layer="below",
                      row=1, col=1)
        fig.add_annotation(x=x0p, y=base.high, text=f"base {base.length} bars, "
                                                    f"{base.depth_pct:.1f}% deep",
                           showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(size=10, color=PIVOT), row=1, col=1)

    pivot = f.get("pivot")
    bo = f.get("breakout")
    if bo is not None:
        pivot = bo["pivot"]
    if pivot is not None and np.isfinite(pivot):
        fig.add_hline(y=pivot, line=dict(color=PIVOT, width=1.6, dash="dash"),
                      annotation_text=f"pivot {pivot:,.2f}",
                      annotation_position="top left",
                      annotation_font=dict(size=11, color=PIVOT), row=1, col=1)

    if bo is not None:
        bdate = bo["date"]
        # plain datetime, not pandas Timestamp: some plotly serialisers (kaleido's JSON
        # path) refuse Timestamp objects in shape/annotation coordinates
        bx = pd.Timestamp(bdate).to_pydatetime()
        failed = np.isfinite(f.get("close", np.nan)) and f["close"] < bo["pivot"]
        colour = DOWN if failed else UP
        rvol = bo.get("rvol", float("nan"))
        label = "%s %s%s" % ("FAILED break" if failed else "BREAKOUT",
                             pd.Timestamp(bdate).strftime("%d %b"),
                             "  ·  %.1f× vol" % rvol if np.isfinite(rvol) else "")

        if bdate >= d.index[0]:
            # A shaded band across BOTH panels so the bar is unmistakable.
            # exclude_empty_subplots=False matters: the volume panel has no traces yet at
            # this point, and plotly silently skips empty subplots by default.
            half = pd.Timedelta(hours=14)
            for r in (1, 2):
                fig.add_vrect(x0=bx - half, x1=bx + half,
                              fillcolor=colour, opacity=0.12, line_width=0,
                              layer="below", row=r, col=1,
                              exclude_empty_subplots=False)

            # 1. redraw the breakout candle itself with a bold outline so the bar that
            #    did the work is the most prominent thing on the chart
            if bdate in d.index:
                bar = d.loc[[bdate]]
                fig.add_trace(go.Candlestick(
                    x=bar.index, open=bar["Open"], high=bar["High"],
                    low=bar["Low"], close=bar["Close"],
                    increasing_line_color=HILITE, decreasing_line_color=HILITE,
                    increasing_fillcolor=colour, decreasing_fillcolor=colour,
                    line=dict(width=2.5), showlegend=False, name="Breakout candle",
                    hoverinfo="skip"), row=1, col=1)

            # 2. a ring at the exact point where price crossed the level - this is
            #    literally "the breakout point"
            fig.add_trace(go.Scatter(
                x=[bx], y=[bo["pivot"]], mode="markers",
                marker=dict(symbol="circle-open", size=20, color=HILITE,
                            line=dict(width=3.5)),
                name="Breakout point", showlegend=False,
                hovertemplate=("<b>breakout point</b><br>crossed the pivot %.2f here"
                               "<extra></extra>") % bo["pivot"]),
                row=1, col=1)

            # 3. an arrow labelling it, anchored on the crossing point
            fig.add_annotation(
                x=bx, y=bo["pivot"], text=label, showarrow=True, arrowhead=2,
                arrowsize=1.1, arrowwidth=2, arrowcolor=colour, ax=-62, ay=46,
                font=dict(size=11, color=colour, family="Arial Black"),
                bgcolor="rgba(255,255,255,0.82)", bordercolor=colour, borderwidth=1,
                borderpad=3, row=1, col=1)

            # 4. the close of the breakout bar, with the full detail on hover
            fig.add_trace(go.Scatter(
                x=[bx], y=[bo["bar_close"]], mode="markers",
                marker=dict(symbol="triangle-up" if not failed else "triangle-down",
                            size=15, color=colour, line=dict(color="white", width=1.5)),
                name="Breakout bar", legendrank=1,
                hovertemplate=("<b>%s</b><br>%%{x|%%d %%b %%Y}<br>close %%{y:.2f}"
                               "<br>pivot %.2f (cleared %+.2f%%)"
                               "<br>volume %.2f× the 50-day average"
                               "<br>closed at %.0f%% of the day's range<extra></extra>")
                              % ("Failed breakout" if failed else "Breakout bar",
                                 bo["pivot"], bo.get("clear_pct", float("nan")),
                                 rvol if np.isfinite(rvol) else 0.0,
                                 (bo.get("close_range_pos") or 0) * 100)),
                row=1, col=1)


    if plan:
        for key, colour, dash, label in (("entry", "#0ea5e9", "dot", "entry"),
                                         ("stop", DOWN, "dot", "stop"),
                                         ("target", UP, "dot", "target")):
            val = plan.get(key)
            if val is not None and np.isfinite(val):
                fig.add_hline(y=val, line=dict(color=colour, width=1, dash=dash),
                              annotation_text=f"{label} {val:,.2f}",
                              annotation_position="bottom right",
                              annotation_font=dict(size=10, color=colour), row=1, col=1)

    colours = np.where(d["Close"].to_numpy() >= d["Open"].to_numpy(),
                       "rgba(22,163,74,0.55)", "rgba(220,38,38,0.55)")
    fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="Volume",
                         marker_color=colours, marker_line_width=0,
                         hovertemplate="vol %{y:,.0f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["VolSMA50"], name="Vol SMA50", mode="lines",
                             line=dict(color="#f59e0b", width=1.2),
                             hovertemplate="avg vol %{y:,.0f}<extra></extra>"),
                  row=2, col=1)

    # the breakout day's volume bar, drawn last so it sits on top of the others
    if bo is not None and bo["date"] in d.index:
        fig.add_trace(go.Bar(
            x=[bo["date"]], y=[float(d.loc[bo["date"], "Volume"])],
            marker=dict(color=DOWN if (np.isfinite(f.get("close", np.nan))
                                       and f["close"] < bo["pivot"]) else UP,
                        line=dict(color="white", width=1.2)),
            name="Breakout volume", showlegend=False,
            hovertemplate="breakout-day volume %{y:,.0f}<extra></extra>"),
            row=2, col=1)

    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        height=560, margin=dict(l=10, r=10, t=44, b=10),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=10)),
        hovermode="x unified", template="plotly_white", bargap=0.1,
        dragmode="pan",
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID, title_text="Price", row=1, col=1)
    fig.update_yaxes(gridcolor=GRID, title_text="Volume", row=2, col=1)
    return fig


def rs_chart(df: pd.DataFrame, bench: pd.Series, bars: int = 220) -> go.Figure:
    """Relative-strength line versus the Nifty 500. A new RS high before a price high
    is the classic leadership tell."""
    b = bench.reindex(df.index).ffill()
    rs = (df["Close"] / b).replace([np.inf, -np.inf], np.nan).dropna().tail(bars)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rs.index, y=rs, mode="lines", name="RS vs Nifty 500",
                             line=dict(color="#0ea5e9", width=1.6)))
    if len(rs) > 20:
        fig.add_trace(go.Scatter(x=rs.index, y=I.sma(rs, 20), mode="lines",
                                 name="RS 20-SMA",
                                 line=dict(color="#94a3b8", width=1, dash="dot")))
    fig.update_layout(height=210, margin=dict(l=10, r=10, t=28, b=10),
                      template="plotly_white", showlegend=False,
                      title=dict(text="Relative strength vs Nifty 500",
                                 font=dict(size=12)))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig
