from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LegView:
    """Normalized snapshot of an option leg used for pricing decisions."""

    strike: float | None
    right: str | None
    expiry: str | None
    signed_position: float
    abs_qty: float
    mid: float | None
    mid_source: str | None
    quote_age: float | None

    def as_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the leg."""

        return {
            "strike": self.strike,
            "right": self.right,
            "expiry": self.expiry,
            "signed_position": self.signed_position,
            "abs_qty": self.abs_qty,
            "mid": self.mid,
            "mid_source": self.mid_source,
            "quote_age": self.quote_age,
        }
