"""Formatting helpers shared between reporting modules."""
from __future__ import annotations

from typing import Any


def format_leg_position(raw: Any) -> str:
    """Return ``S``/``L`` indicator for a leg position value."""

    try:
        num = float(raw)
    except (TypeError, ValueError):
        return "?"
    return "S" if num < 0 else "L"


__all__ = ["format_leg_position"]
