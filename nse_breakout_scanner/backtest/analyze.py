"""Run the full analysis over the saved event datasets and optionally install weights.

Run:  python -m backtest.analyze [--save] [--label trade_R|exc10|R]

Prints, for each of the two scanners:
  1. dataset description and realised trade statistics
  2. does the *current* score rank outcomes at all (IC, quantile table, per-year IC)
  3. per-factor univariate edge
  4. a walk-forward weight fit with shrinkage selected out-of-sample
  5. the resulting weight table

`--save` writes the selected weights to fitted_weights.json, but only for the scanners
where the out-of-sample improvement actually cleared the baseline's confidence interval.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import weights as WGT              # noqa: E402
from backtest import optimize as O           # noqa: E402
from backtest import stats as ST             # noqa: E402
from backtest.collect import OUT_DIR         # noqa: E402

pd.set_option("display.width", 200)

# `label` is the decision-relevant outcome, used for the descriptive statistics and for
# judging the score as it stands. `fit_label` is what the WEIGHT FIT regresses on, and it
# is deliberately different: trade_R is coupled to the trade plan's geometry - entering
# further above the pivot mechanically shortens the distance to target, inflating hit rate
# without improving expectancy - so fitting on it rewards extension for reasons that have
# nothing to do with forecasting. Benchmark-excess return has no such coupling.
# See BACKTEST.md section 4.
SPECS = {
    "breakout": {"file": "events_breakout.parquet", "name": "TAB 2 - CONFIRMED BREAKOUTS",
                 "label": "trade_R", "fit_label": "exc20"},
    "prebreakout": {"file": "events_prebreakout.parquet",
                    "name": "TAB 1 - PRE-BREAKOUT CANDIDATES", "label": "R",
                    "fit_label": "exc20"},
}


def load(kind: str) -> pd.DataFrame:
    path = os.path.join(OUT_DIR, SPECS[kind]["file"])
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    return df


def analyse(kind: str, label_col: str | None = None) -> dict:
    spec = SPECS[kind]
    label_col = label_col or spec["label"]
    df = load(kind)
    if df.empty:
        print("\n%s: no dataset found - run `python -m backtest.collect` first" % spec["name"])
        return {}

    credit_cols = sorted(c for c in df.columns if c.startswith("c_"))
    print(O.describe(df, label_col, spec["name"]))

    # ---- 2. does the score as it stands rank outcomes?
    y = df[label_col].to_numpy(dtype=float)
    ic = ST.spearman(df["score"].to_numpy(dtype=float), y)
    lo, hi = ST.spearman_ci(df["score"].to_numpy(dtype=float), y)
    print("\n  CURRENT SCORE vs %s" % label_col)
    print("    pooled IC = %.4f  (90%% CI %.4f .. %.4f)" % (ic, lo, hi))
    for alt in ("exc10", "exc20"):
        if alt in df:
            print("    IC vs %-6s = %.4f" % (alt, ST.spearman(df["score"], df[alt])))
    qt = ST.quantile_table(df["score"], y, 5)
    if not qt.empty:
        print("\n  outcome by score quintile:")
        print(qt.to_string(index=False).replace("\n", "\n    ").rjust(0))
    yic = O.yearly_ic(df, df["score"].to_numpy(dtype=float), label_col)
    if not yic.empty:
        pos = (yic["IC"] > 0).sum()
        print("\n  IC by calendar year (%d of %d years positive):" % (pos, len(yic)))
        print("    " + yic.to_string(index=False).replace("\n", "\n    "))

    # ---- 3. per-factor edge
    fr = O.factor_report(df, credit_cols, label_col)
    print("\n  PER-FACTOR univariate edge (IC = rank corr with %s):" % label_col)
    print("    " + fr.to_string(index=False).replace("\n", "\n    "))

    # ---- 4. walk-forward fit, on the uncontaminated label
    fit_label = spec.get("fit_label", label_col)
    print("\n  WALK-FORWARD WEIGHT FIT")
    if fit_label != label_col:
        print("    fitting on '%s', not '%s': the R multiple is coupled to the trade "
              "plan's geometry\n    and would reward extension for non-predictive "
              "reasons (BACKTEST.md s4)." % (fit_label, label_col))
    res = O.walk_forward(df, credit_cols, fit_label, kind)
    print(O.summarise(res, kind))

    wt = O.weight_table(res)
    if not wt.empty:
        print("\n  weights (total held at %.0f):" % res["total_weight"])
        print("    " + wt.to_string(index=False).replace("\n", "\n    "))
    return res


def main(argv) -> None:
    save = "--save" in argv
    label = None
    if "--label" in argv:
        label = argv[argv.index("--label") + 1]

    results = {}
    for kind in ("breakout", "prebreakout"):
        results[kind] = analyse(kind, label)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    to_save = {}
    for kind, res in results.items():
        if not res or "error" in res or res.get("best") is None:
            print("  %-12s : no usable fit (%s)"
                  % (kind, res.get("error", "no dataset") if res else "no dataset"))
            continue
        base_ic = res["baseline"]["IC_test"]
        best = res["best"]
        if res["significant"] and best["lambda"] > 0:
            print("  %-12s : fitted weights improve out-of-sample IC %.4f -> %.4f "
                  "(lambda %.2f) - ADOPT" % (kind, base_ic, best["IC_test"], best["lambda"]))
            to_save.update(best["weights"])
        else:
            print("  %-12s : conventional IC %.4f, best blend %.4f (lambda %.2f) - "
                  "inside the noise band, KEEP CONVENTIONAL"
                  % (kind, base_ic, best["IC_test"], best["lambda"]))

    if save and to_save:
        meta = {"label": "fitted", "source": "backtest.analyze",
                "scanners": [k for k, r in results.items()
                             if r and r.get("significant") and r["best"]["lambda"] > 0]}
        path = WGT.save({k[2:]: v for k, v in to_save.items()}, meta)
        print("\n  wrote %s" % path)
    elif save:
        print("\n  nothing worth saving - conventional weights retained")


if __name__ == "__main__":
    main(sys.argv[1:])
