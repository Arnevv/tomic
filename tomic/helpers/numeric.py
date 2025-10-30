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
    allow_none: bool = True,
    allow_bool: bool = True,
    fallback: float | None = None,
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
    allow_none:
        Controls how ``None`` inputs are treated.  When ``True`` (default)
        ``None`` is returned as-is.  When ``False`` the ``fallback`` value is
        returned instead.
    allow_bool:
        When ``False`` boolean inputs are considered invalid and yield the
        ``fallback`` value.
    fallback:
        Value returned when the input cannot be coerced.  The fallback itself is
        coerced via :func:`safe_float`, allowing the same parsing rules to be
        applied.  Defaults to ``None``.
    """

    if fallback is None:
        fallback_result: float | None = None
    else:
        fallback_result = safe_float(
            fallback,
            allow_strings=allow_strings,
            allow_signed=allow_signed,
            accept_nan=accept_nan,
            allow_none=True,
            allow_bool=True,
            fallback=None,
        )

    if value is None:
        if allow_none:
            return None
        return fallback_result

    if isinstance(value, bool):
        if not allow_bool:
            return fallback_result
        return float(value)

    if isinstance(value, (int, float)):
        number = float(value)
        if not accept_nan and math.isnan(number):
            return fallback_result
        return number

    decimal_value = _coerce_decimal(value)
    if decimal_value is not None:
        if not accept_nan and math.isnan(decimal_value):
            return fallback_result
        return decimal_value

    if not allow_strings:
        return fallback_result

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive guard
            return fallback_result

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return fallback_result

        cleaned = cleaned.replace("%", "")
        cleaned = _CLEAN_RE.sub("", cleaned)

        if not allow_signed and any(sign in cleaned for sign in "+-"):
            return fallback_result

        candidate = parse_euro_float(cleaned)
        if candidate is None:
            # ``parse_euro_float`` handles most cases, but fall back to ``float``
            try:
                candidate = float(cleaned)
            except (TypeError, ValueError):
                return fallback_result

        if not accept_nan and (candidate is None or math.isnan(candidate)):
            return fallback_result
        return candidate

    if hasattr(value, "__float__"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback_result
        if not accept_nan and math.isnan(number):
            return fallback_result
        return number

    return fallback_result


def as_float(
    value: Any,
    *,
    allow_strings: bool = True,
    allow_signed: bool = True,
    accept_nan: bool = False,
    allow_none: bool = True,
    allow_bool: bool = True,
    fallback: float | None = None,
) -> float | None:
    """Alias for :func:`safe_float` kept for readability in call sites."""

    return safe_float(
        value,
        allow_strings=allow_strings,
        allow_signed=allow_signed,
        accept_nan=accept_nan,
        allow_none=allow_none,
        allow_bool=allow_bool,
        fallback=fallback,
    )


__all__ = ["safe_float", "as_float"]

