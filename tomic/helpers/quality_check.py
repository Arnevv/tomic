"""Helpers to compute option chain quality metrics."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tomic.helpers.csv_utils import parse_euro_float


def _is_na(value: object) -> bool:
    """Return ``True`` when ``value`` should be treated as missing."""

    if value is None:
        return True
    isna = getattr(pd, "isna", None)
    if callable(isna):
        try:
            return bool(isna(value))
        except TypeError:
            pass
    try:
        return value != value  # NaN check
    except TypeError:  # pragma: no cover - defensive guard
        return False


@dataclass(frozen=True)
class PillarWeights:
    """Relative weight for each quality pillar."""

    coverage: float = 0.4
    pricing: float = 0.4
    greeks: float = 0.2


_WEIGHTS = PillarWeights()
_COVERAGE_FIELDS = ["bid", "ask", "iv", "delta", "gamma", "vega", "theta"]
_GREEK_FIELDS = ["iv", "delta", "gamma", "vega", "theta"]


def _has_value(value: object) -> bool:
    """Return ``True`` when ``value`` contains non-empty data."""

    if _is_na(value):
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _to_float(value: object) -> float | None:
    """Return ``value`` as float when possible."""

    if isinstance(value, (int, float)):
        if _is_na(value):
            return None
        return float(value)
    if isinstance(value, str):
        candidate = parse_euro_float(value)
        if candidate is not None:
            return candidate
        try:
            return float(value.strip()) if value.strip() else None
        except ValueError:
            return None
    return None


def _coverage_score(df: pd.DataFrame) -> float:
    """Return percentage of populated required fields."""

    total_rows = len(df)
    if total_rows == 0:
        return 0.0

    total_fields = total_rows * len(_COVERAGE_FIELDS)
    populated = 0
    for _, row in df.iterrows():
        for field in _COVERAGE_FIELDS:
            if _has_value(row.get(field)):
                populated += 1
    return (populated / total_fields) * 100 if total_fields else 0.0


def _pricing_score(df: pd.DataFrame) -> float:
    """Return percentage of rows with reliable mid price and spread."""

    considered = 0
    valid = 0
    for _, row in df.iterrows():
        bid = _to_float(row.get("bid"))
        ask = _to_float(row.get("ask"))
        if bid is None or ask is None:
            continue
        considered += 1
        if bid <= 0 or ask <= 0:
            continue
        if ask < bid:
            continue
        mid = (bid + ask) / 2
        spread = ask - bid
        if mid <= 0 or spread <= 0:
            continue
        # Guard against extreme or illogical spreads.
        if spread / mid > 0.75 and spread > 0.05:
            continue
        valid += 1
    if considered == 0:
        return 0.0
    return (valid / considered) * 100


def _greeks_score(df: pd.DataFrame) -> float:
    """Return percentage of rows with Greeks inside realistic ranges."""

    considered = 0
    valid = 0
    for _, row in df.iterrows():
        values: dict[str, float] = {}
        missing = False
        for field in _GREEK_FIELDS:
            val = row.get(field)
            if not _has_value(val):
                missing = True
                break
            number = _to_float(val)
            if number is None:
                missing = True
                break
            values[field] = number
        if missing:
            continue
        considered += 1
        iv = values["iv"]
        delta = values["delta"]
        gamma = values["gamma"]
        vega = values["vega"]
        theta = values["theta"]
        if not (0 < iv < 10):
            continue
        if not (-1.05 <= delta <= 1.05):
            continue
        if not (-5 <= gamma <= 5):
            continue
        if not (-50 <= vega <= 50):
            continue
        if not (-25 <= theta <= 25):
            continue
        valid += 1
    if considered == 0:
        return 0.0
    return (valid / considered) * 100


def calculate_csv_quality(df: pd.DataFrame) -> float:
    """Return overall option chain quality score.

    The score is a weighted combination of three transparent pillars:

    * **Data coverage (40%)** – how many required data points are present.
    * **Pricing reliability (40%)** – whether bid/ask pairs form sensible mid prices.
    * **Greeks validation (20%)** – if IV and greeks fall within realistic ranges.
    """

    if df.empty:
        return 0.0

    coverage = _coverage_score(df)
    pricing = _pricing_score(df)
    greeks = _greeks_score(df)
    return (
        coverage * _WEIGHTS.coverage
        + pricing * _WEIGHTS.pricing
        + greeks * _WEIGHTS.greeks
    )

