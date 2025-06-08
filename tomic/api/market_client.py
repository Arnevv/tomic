"""Placeholder utilities for market data operations."""

from __future__ import annotations

import threading
import time
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


def start_app(app: MarketClient) -> None:
    """Connect ``app`` to TWS and start the network thread."""
    app.connect("127.0.0.1", 7497, 1)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    start = time.time()
    while app.next_valid_id is None and time.time() - start < 5:
        time.sleep(0.1)


def await_market_data(app: MarketClient, symbol: str, timeout: int = 10) -> bool:
    """Wait until some market data has been received or timeout occurs."""
    start = time.time()
    while time.time() - start < timeout:
        if app.market_data:
            return True
        time.sleep(0.1)
    return False


def fetch_market_metrics(symbol: str):
    """Fetch minimal market metrics for ``symbol``."""
    app = MarketClient(symbol)
    start_app(app)
    if hasattr(app, "start_requests"):
        app.start_requests()
    if not await_market_data(app, symbol):
        app.disconnect()
        return None
    metrics = {
        "spot_price": app.spot_price,
        "hv30": None,
        "atr14": None,
        "vix": None,
        "skew": None,
        "term_m1_m2": None,
        "term_m1_m3": None,
        "iv_rank": None,
        "implied_volatility": None,
        "iv_percentile": None,
    }
    app.disconnect()
    return metrics


__all__ = ["MarketClient", "start_app", "await_market_data", "fetch_market_metrics"]
