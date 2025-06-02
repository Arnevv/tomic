"""Retrieve open interest for a single option contract."""

from __future__ import annotations

import threading
from typing import Optional

from tomic.api.base_client import BaseIBApp
from tomic.api.market_utils import create_option_contract, start_app
from tomic.logging import logger


class _OpenInterestApp(BaseIBApp):
    """Minimal IB app to fetch open interest."""

    def __init__(self, symbol: str, expiry: str, strike: float, right: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.expiry = expiry
        self.strike = strike
        self.right = right
        self.open_interest: Optional[int] = None
        self.open_interest_event = threading.Event()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        contract = create_option_contract(
            self.symbol, self.expiry, self.strike, self.right
        )
        self.reqMktData(1001, contract, "101", False, False, [])

    def tickGeneric(
        self, reqId: int, tickType: int, value: float
    ) -> None:  # noqa: N802
        if tickType == 101:
            self.open_interest = int(value)
            self.open_interest_event.set()


def fetch_open_interest(
    symbol: str, expiry: str, strike: float, right: str
) -> int | None:
    """Return open interest for the specified option contract."""

    expiry = expiry.replace("-", "")
    app = _OpenInterestApp(symbol.upper(), expiry, strike, right.upper())
    start_app(app)

    if not app.open_interest_event.wait(timeout=10):
        logger.error("❌ Geen open interest ontvangen.")
        app.disconnect()
        return None

    oi = app.open_interest
    app.disconnect()
    logger.info(
        f"Open interest voor {symbol.upper()} {expiry} {strike}{right.upper()}: {oi}"
    )
    return oi


__all__ = ["fetch_open_interest"]
