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


# Minimum number of IV history records required for reliable rank/percentile
MIN_IV_HISTORY_DAYS = 252


def get_historical_iv_series(
    symbol: str,
    *,
    exclude_date: str | None = None,
) -> list[float]:
    """Return historical ATM IV values for ``symbol`` from iv_daily_summary.

    Parameters
    ----------
    symbol
        Ticker symbol to load IV history for.
    exclude_date
        Optional date string (YYYY-MM-DD) to exclude from the series.
        Useful when calculating rank/percentile for a specific date to avoid
        including that date's IV in the comparison series.

    Returns
    -------
    list[float]
        List of ATM IV values (as percentages, e.g. 20.5 for 20.5%) sorted by date.
        Returns empty list if no data available.
    """
    base = price_cfg_get("IV_DAILY_SUMMARY_DIR") or price_cfg_get("IV_SUMMARY_DIR")
    if not base:
        base = "tomic/data/iv_daily_summary"

    path = Path(base) / f"{symbol}.json"
    try:
        raw = load_json(path)
    except Exception:
        return []

    if not isinstance(raw, list):
        return []

    # Sort by date to ensure chronological order
    raw.sort(key=lambda rec: rec.get("date", ""))

    iv_values: list[float] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        # Skip the excluded date if specified
        if exclude_date and rec.get("date") == exclude_date:
            continue
        atm_iv = rec.get("atm_iv")
        if atm_iv is None:
            continue
        try:
            # Convert to percentage if stored as decimal (e.g., 0.20 -> 20.0)
            iv_float = float(atm_iv)
            if iv_float < 1:  # Stored as decimal, convert to percentage
                iv_float *= 100
            iv_values.append(iv_float)
        except (TypeError, ValueError):
            continue

    return iv_values


def has_sufficient_iv_history(symbol: str, min_days: int = MIN_IV_HISTORY_DAYS) -> bool:
    """Check if symbol has sufficient IV history for reliable rank/percentile.

    Parameters
    ----------
    symbol
        Ticker symbol to check.
    min_days
        Minimum number of IV history records required. Defaults to 252 (1 year).

    Returns
    -------
    bool
        True if sufficient history exists, False otherwise.
    """
    iv_series = get_historical_iv_series(symbol)
    return len(iv_series) >= min_days


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


__all__ = [
    "_get_closes",
    "rolling_hv",
    "iv_rank",
    "iv_percentile",
    "get_historical_iv_series",
    "has_sufficient_iv_history",
    "MIN_IV_HISTORY_DAYS",
]
