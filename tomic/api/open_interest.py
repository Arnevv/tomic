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

    def _log_request(self) -> None:
        logger.debug(
            f"Requesting open interest for {self.symbol} "
            f"{self.expiry} {self.strike:.2f}{self.right}"
        )

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        contract = create_option_contract(
            self.symbol, self.expiry, self.strike, self.right
        )
        # Request volume (100) and open interest (101) generic ticks. Some
        # brokers send open interest via tick types 86/87 instead of 101.
        self._log_request()
        # Ensure we receive frozen market data so open interest is returned
        self.reqMarketDataType(2)
        self.reqMktData(1001, contract, "100,101", False, False, [])

    def tickGeneric(
        self, reqId: int, tickType: int, value: float
    ) -> None:  # noqa: N802
        if tickType == 101:
            self.open_interest = int(value)
            self.open_interest_event.set()
        logger.debug(
            f"tickGeneric: reqId={reqId} tickType={tickType} value={value}"
        )

    def tickPrice(
        self, reqId: int, tickType: int, price: float, attrib
    ) -> None:  # noqa: N802
        if tickType in (86, 87):  # option call/put open interest
            self.open_interest = int(price)
            self.open_interest_event.set()
        logger.debug(
            f"tickPrice: reqId={reqId} tickType={tickType} price={price}"
        )


WAIT_TIMEOUT = 20


def fetch_open_interest(
    symbol: str, expiry: str, strike: float, right: str
) -> int | None:
    """Return open interest for the specified option contract."""

    expiry = expiry.replace("-", "")
    app = _OpenInterestApp(symbol.upper(), expiry, strike, right.upper())
    start_app(app)

    logger.debug(f"Waiting up to {WAIT_TIMEOUT} seconds for open interest data")

    if not app.open_interest_event.wait(timeout=WAIT_TIMEOUT):
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
