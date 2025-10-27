"""Shared helpers for volatility statistics calculations."""
from __future__ import annotations

from pathlib import Path
from numbers import Number
from typing import Iterable, Sequence

from tomic.analysis.metrics import historical_volatility
from tomic.helpers.price_utils import cfg_get as price_cfg_get
from tomic.journal.utils import load_json
from tomic.utils import load_price_history


def _numeric_values(series: Iterable[object]) -> list[float]:
    """Return numeric values from ``series`` cast to ``float``."""

    values: list[float] = []
    for value in series:
        if isinstance(value, Number):
            values.append(float(value))
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _get_closes(symbol: str) -> list[float]:
    """Return list of close prices for ``symbol`` sorted by date."""

    data = load_price_history(symbol)
    if not data:
        base = price_cfg_get("PRICE_HISTORY_DIR")
        if base:
            path = Path(base) / f"{symbol}.json"
            try:
                raw = load_json(path)
            except Exception:
                raw = None
            if isinstance(raw, list):
                raw.sort(key=lambda rec: rec.get("date", ""))
                data = raw
    closes: list[float] = []
    for rec in data:
        try:
            closes.append(float(rec.get("close", 0)))
        except (TypeError, ValueError):
            continue
    return closes


def rolling_hv(closes: Sequence[float], window: int) -> list[float]:
    """Return historical volatility values for rolling windows."""

    result: list[float] = []
    for idx in range(window, len(closes) + 1):
        hv = historical_volatility(closes[idx - window : idx], window=window)
        if hv is not None:
            result.append(hv)
    return result


def iv_rank(value: float, series: Sequence[float]) -> float | None:
    """Return the IV rank for ``value`` relative to ``series``."""

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    values = _numeric_values(series)
    if not values:
        return None
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return None
    return (numeric_value - lo) / (hi - lo)


def iv_percentile(value: float, series: Sequence[float]) -> float | None:
    """Return the percentile of ``value`` relative to ``series``."""

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    values = _numeric_values(series)
    if not values:
        return None
    count = sum(1 for hv in values if hv < numeric_value)
    return count / len(values)


__all__ = ["_get_closes", "rolling_hv", "iv_rank", "iv_percentile"]
