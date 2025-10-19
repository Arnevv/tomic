"""Shared helpers for volatility statistics calculations."""
from __future__ import annotations

from typing import Sequence

from tomic.analysis.metrics import historical_volatility


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

    values = list(series)
    if not values:
        return None
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return None
    return (value - lo) / (hi - lo)


def iv_percentile(value: float, series: Sequence[float]) -> float | None:
    """Return the percentile of ``value`` relative to ``series``."""

    values = list(series)
    if not values:
        return None
    count = sum(1 for hv in values if hv < value)
    return count / len(values)


__all__ = ["rolling_hv", "iv_rank", "iv_percentile"]
