"""Placeholder utilities for market data operations."""

from __future__ import annotations

from typing import Any

from .base_client import BaseIBApp


class MarketClient(BaseIBApp):
    """Simplified IB app for market data requests."""

    def __init__(self, symbol: str):
        super().__init__()
        self.symbol = symbol
        self.market_data: dict[int, dict[str, Any]] = {}
        self.invalid_contracts: set[int] = set()
        self.spot_price: float | None = None


# The functions below are intentionally minimal. They can be overridden or
# monkeypatched during testing or extended in production code.

def start_app(app: MarketClient) -> None:
    """Start the event loop for ``app`` (stub)."""
    raise NotImplementedError


def await_market_data(app: MarketClient, symbol: str, timeout: int = 10) -> bool:
    """Wait for market data to be received (stub)."""
    raise NotImplementedError


def fetch_market_metrics(symbol: str):
    """Fetch market metrics for ``symbol`` (stub)."""
    raise NotImplementedError


__all__ = ["MarketClient", "start_app", "await_market_data", "fetch_market_metrics"]
