"""Numeric helpers shared across service modules."""
from __future__ import annotations

from typing import Any


def normalize_percent(value: Any) -> float | None:
    """Return ``value`` as fraction (0-1) if it represents a percentage."""

    if isinstance(value, (int, float)):
        val = float(value)
        if val > 1:
            val /= 100
        if 0 <= val <= 1:
            return val
    return None


__all__ = ["normalize_percent"]
