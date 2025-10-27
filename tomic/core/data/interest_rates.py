"""Interest rate provider abstractions for pricing services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...config import get as cfg_get


@dataclass(frozen=True)
class InterestRateQuote:
    """Resolved interest rate value with provenance metadata."""

    value: float
    source: str


class InterestRateProvider:
    """Provide short-term interest rate quotes used for pricing."""

    def __init__(self, *, default_source: str = "config") -> None:
        self._default_source = default_source

    def current(self, *, override: Optional[float] = None, source: str | None = None) -> InterestRateQuote:
        """Return the current interest rate.

        Parameters
        ----------
        override:
            Explicit interest rate provided by the caller. When supplied this
            value is returned unchanged and the ``source`` metadata is marked as
            ``"override"`` unless explicitly specified.
        source:
            Optional source tag to use when ``override`` is provided.
        """

        if override is not None:
            try:
                value = float(override)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                value = float(cfg_get("INTEREST_RATE", 0.05))
            return InterestRateQuote(value=value, source=source or "override")

        raw = cfg_get("INTEREST_RATE", 0.05)
        try:
            value = float(raw)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            value = 0.05
        return InterestRateQuote(value=value, source=self._default_source)


__all__ = ["InterestRateProvider", "InterestRateQuote"]
