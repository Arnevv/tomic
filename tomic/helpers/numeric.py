"""Numeric parsing and normalization helpers."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from .csv_utils import parse_euro_float

_CLEAN_RE = re.compile(r"[^0-9,\.\-+]")


def _coerce_decimal(value: Any) -> float | None:
    """Return ``value`` coerced to ``float`` when it is a :class:`Decimal`."""

    if isinstance(value, Decimal):
        if value.is_nan():
            return math.nan
        try:
            return float(value)
        except (OverflowError, ValueError):  # pragma: no cover - defensive
            return None
    return None


def safe_float(
    value: Any,
    *,
    allow_strings: bool = True,
    allow_signed: bool = True,
    accept_nan: bool = False,
) -> float | None:
    """Return ``value`` coerced to ``float`` with consistent semantics.

    Parameters
    ----------
    value:
        Incoming object to coerce. ``None`` and empty strings result in ``None``.
    allow_strings:
        When ``True`` (default) string inputs are cleaned and parsed, supporting
        both US and European decimal separators as well as percentage symbols.
    allow_signed:
        When ``False`` signed numeric representations (``+``/``-``) return
        ``None``.
    accept_nan:
        When ``True`` ``float('nan')`` values are propagated instead of being
        converted to ``None``.
    """

    if value is None:
        return None

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        number = float(value)
        if not accept_nan and math.isnan(number):
            return None
        return number

    decimal_value = _coerce_decimal(value)
    if decimal_value is not None:
        if not accept_nan and math.isnan(decimal_value):
            return None
        return decimal_value

    if not allow_strings:
        return None

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive guard
            return None

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None

        cleaned = cleaned.replace("%", "")
        cleaned = _CLEAN_RE.sub("", cleaned)

        if not allow_signed and any(sign in cleaned for sign in "+-"):
            return None

        candidate = parse_euro_float(cleaned)
        if candidate is None:
            # ``parse_euro_float`` handles most cases, but fall back to ``float``
            try:
                candidate = float(cleaned)
            except (TypeError, ValueError):
                return None

        if not accept_nan and (candidate is None or math.isnan(candidate)):
            return None
        return candidate

    if hasattr(value, "__float__"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not accept_nan and math.isnan(number):
            return None
        return number

    return None


def as_float(
    value: Any,
    *,
    allow_strings: bool = True,
    allow_signed: bool = True,
    accept_nan: bool = False,
) -> float | None:
    """Alias for :func:`safe_float` kept for readability in call sites."""

    return safe_float(
        value,
        allow_strings=allow_strings,
        allow_signed=allow_signed,
        accept_nan=accept_nan,
    )


__all__ = ["safe_float", "as_float"]

