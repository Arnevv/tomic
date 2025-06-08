"""Placeholder utilities for market data operations."""

from __future__ import annotations

from typing import Any, Dict
import threading
import time

from .base_client import BaseIBApp
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.cli.daily_vol_scraper import fetch_volatility_metrics


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
    """Connect to TWS/IB Gateway and start ``app`` in a background thread."""

    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    client_id = int(cfg_get("IB_CLIENT_ID", 100))

    app.connect(host, port, client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()


def await_market_data(app: MarketClient, symbol: str, timeout: int = 10) -> bool:
    """Wait until market data has been populated or timeout occurs."""

    start = time.time()
    while time.time() - start < timeout:
        if app.market_data or app.spot_price is not None:
            return True
        time.sleep(0.1)
    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


def fetch_market_metrics(symbol: str):
    """Return key volatility metrics scraped from Barchart."""

    data = fetch_volatility_metrics(symbol.upper())
    metrics: Dict[str, Any] = {
        "spot_price": data.get("spot_price"),
        "hv30": data.get("hv30"),
        "atr14": None,
        "vix": None,
        "skew": data.get("skew"),
        "term_m1_m2": None,
        "term_m1_m3": None,
        "iv_rank": data.get("iv_rank"),
        "implied_volatility": data.get("implied_volatility"),
        "iv_percentile": data.get("iv_percentile"),
    }
    logger.debug(f"Fetched metrics for {symbol}: {metrics}")
    return metrics


__all__ = ["MarketClient", "start_app", "await_market_data", "fetch_market_metrics"]
