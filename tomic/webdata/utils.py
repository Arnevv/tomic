"""Utility helpers for working with web-derived data."""

from __future__ import annotations

from typing import Optional

from tomic.helpers.numeric import safe_float
from tomic.logutils import logger


def to_float(value: object) -> Optional[float]:
    """Return ``value`` cast to ``float`` when possible."""

    if value is None:
        return None
    number = safe_float(value)
    if number is None:
        logger.debug(f"Failed numeric conversion for value '{value}'")
    return number


__all__ = ["to_float"]
