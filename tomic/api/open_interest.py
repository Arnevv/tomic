"""Retrieve open interest for a single option contract."""

from __future__ import annotations

import threading
import time
from typing import Optional

from ibapi.contract import Contract
from tomic.api.market_client import MarketClient, start_app
from tomic.config import get as cfg_get
from tomic.api.ib_connection import connect_ib
from tomic.models import OptionContract


def _create_option_contract(info: OptionContract) -> Contract:
    """Return an IB ``Contract`` for the given option info."""

    return info.to_ib()
from tomic.logutils import logger


class _OpenInterestApp(MarketClient):
    """Minimal IB app to fetch open interest."""

    def __init__(self, symbol: str, expiry: str, strike: float, right: str, primary_exchange: str | None = None) -> None:
        super().__init__(symbol, primary_exchange=primary_exchange)
        self.symbol = symbol
        self.expiry = expiry
        self.strike = strike
        self.right = right
        self.open_interest: Optional[int] = None
        self.open_interest_event = threading.Event()
        self.open_interest_source: Optional[str] = None
        self.received_ticks: list[str] = []

    def _log_request(self, contract) -> None:
        logger.debug(
            f"Requesting open interest for {self.symbol} "
            f"{self.expiry} {self.strike:.2f}{self.right}"
        )
        logger.debug(f"Contract details: {contract}")

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        contract = _create_option_contract(self.contract)
        # Request volume (100) and open interest (101) generic ticks. Some
        # brokers send open interest via tick types 86/87 instead of 101.
        self._log_request(contract)
        # Request delayed market data for open interest
        self.reqMarketDataType(3)
        logger.debug("reqMarketDataType(3) - delayed")
        self.reqMktData(1001, contract, "100,101", False, False, [])
        logger.debug(
            "reqMktData sent: id=1001 tickList=100,101 snapshot=False regulatory=False"
        )

    def tickGeneric(
        self, reqId: int, tickType: int, value: float
    ) -> None:  # noqa: N802
        if tickType == 101:
            logger.success(f"✅ Open Interest (tickGeneric 101): {value}")
            self.open_interest = int(value)
            self.open_interest_source = "tickGeneric 101"
            self.open_interest_event.set()
        elif tickType == 100:
            logger.info(f"ℹ️ Volume (tickGeneric 100): {value}")
        self.received_ticks.append(f"G{tickType}")
        logger.debug(
            f"tickGeneric: reqId={reqId} tickType={tickType} value={value}"
        )

    def tickPrice(
        self, reqId: int, tickType: int, price: float, attrib
    ) -> None:  # noqa: N802
        if tickType in (86, 87):  # option call/put open interest
            logger.warning(
                f"⚠️ Open Interest mogelijk via tickPrice {tickType}: {price}"
            )
            self.open_interest = int(price)
            self.open_interest_source = f"tickPrice {tickType}"
            self.open_interest_event.set()
        self.received_ticks.append(f"P{tickType}")
        logger.debug(
            f"tickPrice: reqId={reqId} tickType={tickType} price={price}"
        )


WAIT_TIMEOUT = 20


def fetch_open_interest(
    symbol: str, expiry: str, strike: float, right: str
) -> int | None:
    """Return open interest for the specified option contract."""

    expiry = expiry.replace("-", "")
    info = OptionContract(
        symbol.upper(),
        expiry,
        strike,
        right.upper(),
        exchange=cfg_get("OPTIONS_EXCHANGE", "SMART"),
        primary_exchange=cfg_get("OPTIONS_PRIMARY_EXCHANGE", "ARCA"),
    )
    app = _OpenInterestApp(
        info.symbol,
        info.expiry,
        info.strike,
        info.right,
        primary_exchange=cfg_get("UNDERLYING_PRIMARY_EXCHANGE", "ARCA"),
    )

    try:
        probe = connect_ib()
        probe.disconnect()
    except Exception:
        return None

    start_app(app)
    app.reqIds(1)

    logger.debug(f"Waiting up to {WAIT_TIMEOUT} seconds for open interest data")
    start = time.time()
    while not app.open_interest_event.is_set():
        if time.time() - start > WAIT_TIMEOUT:
            logger.error("❌ Geen open interest ontvangen.")
            logger.debug(
                f"Ontvangen tick types tijdens wachten: {', '.join(app.received_ticks)}"
            )
            app.disconnect()
            return None
        time.sleep(0.1)

    oi = app.open_interest
    app.disconnect()
    logger.info(f"Open interest ontvangen via: {app.open_interest_source}")
    logger.info(
        f"Open interest voor {symbol.upper()} {expiry} {strike}{right.upper()}: {oi}"
    )
    return oi


__all__ = ["fetch_open_interest"]
