"""Runtime-overridable rule weights.

The conventional weights stay written as literals at their call sites in `rules.py`,
where they are readable next to the rule they belong to. This module lets a fitted set
override them by rule id, so the backtest can install optimised weights without editing
rule code and the app can offer both.

`resolve(rule_id, default)` is called from inside the `scored()` / `risk()` helpers, so
no call site needs to change.
"""
from __future__ import annotations

import json
import os

_overrides: dict[str, float] = {}
_label: str = "conventional"

WEIGHTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "fitted_weights.json")


def resolve(rule_id: str, default: float) -> float:
    """The active weight for a rule: an override if one is installed, else the literal."""
    v = _overrides.get(rule_id)
    return float(default) if v is None else float(v)


def set_overrides(d: dict | None, label: str = "fitted") -> None:
    global _overrides, _label
    _overrides = {str(k): float(v) for k, v in (d or {}).items()}
    _label = label if _overrides else "conventional"


def clear() -> None:
    set_overrides(None)


def active() -> dict:
    return dict(_overrides)


def label() -> str:
    return _label


def save(d: dict, meta: dict | None = None, path: str = None) -> str:
    path = path or WEIGHTS_FILE
    payload = {"weights": {k: round(float(v), 3) for k, v in d.items()},
               "meta": meta or {}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def load(path: str = None, install: bool = True) -> tuple[dict, dict]:
    """Load a fitted weight file. Returns (weights, meta); ({}, {}) when absent."""
    path = path or WEIGHTS_FILE
    if not os.path.exists(path):
        return {}, {}
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        w = {str(k): float(v) for k, v in payload.get("weights", {}).items()}
        meta = payload.get("meta", {})
        if install and w:
            set_overrides(w, label=meta.get("label", "fitted"))
        return w, meta
    except Exception:
        return {}, {}


def available() -> bool:
    return os.path.exists(WEIGHTS_FILE)
