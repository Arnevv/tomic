"""Utility helpers for working with web-derived data."""

from __future__ import annotations

import re
from typing import Optional

from tomic.logutils import logger


def to_float(value: object) -> Optional[float]:
    """Return ``value`` cast to ``float`` when possible."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        cleaned = re.sub(r"[^0-9,.-]", "", cleaned)
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            logger.debug(f"Failed numeric conversion for value '{value}'")
            return None
    logger.debug(f"Unsupported type for numeric conversion: {type(value)}")
    return None


__all__ = ["to_float"]
