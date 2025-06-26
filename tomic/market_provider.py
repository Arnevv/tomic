from __future__ import annotations

"""Protocol definition for market data providers."""

from typing import Protocol, Any, Dict, List


class MarketDataProvider(Protocol):
    """Protocol for classes offering market data."""

    def connect(self) -> None:
        """Open any required connections."""
        ...

    def disconnect(self) -> None:
        """Close connections and cleanup."""
        ...

    def fetch_option_chain(self, symbol: str) -> List[Dict[str, Any]]:
        """Return option chain data for ``symbol``."""
        ...

    def fetch_market_metrics(self, symbol: str) -> Dict[str, Any]:
        """Return market metrics for ``symbol``."""
        ...
