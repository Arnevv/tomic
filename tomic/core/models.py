from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class OptionLeg:
    """Normalized option leg representation for strategy evaluation."""

    expiry: Optional[str] = None
    type: Optional[str] = None
    strike: Optional[float] = None
    spot: Optional[float] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    model: Optional[float] = None
    edge: Optional[float] = None
    position: int = 1
    quantity: int = 1
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    mid_fallback: Optional[str] = None


__all__ = ["OptionLeg"]
