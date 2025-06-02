from __future__ import annotations

"""Shared base classes for IB API clients."""

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from .market_utils import calculate_atr14, calculate_hv30, count_incomplete


class MarketDataMixin:
    """Mixin providing common market data helpers."""

    def __init__(self) -> None:
        self.market_data: dict[int, dict] = {}
        self.invalid_contracts: set[int] = set()
        self.historical_data: list = []

    def calculate_hv30(self) -> float | None:
        """Return the 30‑day historical volatility."""
        return calculate_hv30(self.historical_data)

    def calculate_atr14(self) -> float | None:
        """Return the 14‑day average true range."""
        return calculate_atr14(self.historical_data)

    def count_incomplete(self) -> int:
        """Return number of market records missing required fields."""
        relevant = [
            d for k, d in self.market_data.items() if k not in self.invalid_contracts
        ]
        return count_incomplete(relevant)


class BaseIBApp(MarketDataMixin, EWrapper, EClient):
    """Minimal base application combining ``EClient`` and ``EWrapper``."""

    def __init__(self) -> None:
        MarketDataMixin.__init__(self)
        EClient.__init__(self, self)


__all__ = ["MarketDataMixin", "BaseIBApp"]
