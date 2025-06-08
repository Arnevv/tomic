"""Fetch option data for a single contract via IB API."""

from __future__ import annotations

import threading
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum

from tomic.api.base_client import BaseIBApp
from tomic.api.market_client import start_app
from tomic.logutils import setup_logging, logger


class SingleOptionClient(BaseIBApp):
    """Client to retrieve bid/ask and Greeks for one option contract."""

    def __init__(self, symbol: str, expiry: str, strike: float, right: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.expiry = expiry
        self.strike = strike
        self.right = right.upper()
        self.con_id: int | None = None
        self.data: dict[str, float] = {}
        self.req_id = 1
        self.done = threading.Event()
        self.connected = threading.Event()

    # IB callbacks -------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        super().nextValidId(orderId)
        self.connected.set()  # ← toevoegen
        logger.info("Stap 1: contractdetails opvragen")
        c = Contract()
        c.symbol = self.symbol
        c.secType = "OPT"
        c.exchange = "SMART"
        c.primaryExchange = "SMART"
        c.currency = "USD"
        c.lastTradeDateOrContractMonth = self.expiry
        c.strike = self.strike
        c.right = self.right
        logger.debug(f"=> reqContractDetails {c}")
        self.reqContractDetails(self.req_id, c)

    def contractDetails(self, reqId: int, details) -> None:  # noqa: N802
        self.con_id = details.contract.conId
        logger.debug(f"<= contractDetails conId={self.con_id}")
        logger.info("Stap 2: optie data opvragen")
        c = details.contract
        logger.debug(f"=> reqMktData {c}")
        self.reqMktData(self.req_id, c, "", False, False, [])

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        if tickType == TickTypeEnum.BID:
            self.data["bid"] = price
        elif tickType == TickTypeEnum.ASK:
            self.data["ask"] = price
        if self._all_received():
            self.done.set()

    def tickOptionComputation(
        self,
        reqId: int,
        tickType: int,
        tickAttrib,
        impliedVol: float,
        delta: float,
        optPrice: float,
        pvDividend: float,
        gamma: float,
        vega: float,
        theta: float,
        undPrice: float,
    ) -> None:  # noqa: N802
        self.data.update({
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
        })
        logger.debug(
            "<= optionComputation delta=%s gamma=%s vega=%s theta=%s",
            delta,
            gamma,
            vega,
            theta,
        )
        if self._all_received():
            self.done.set()

    def _all_received(self) -> bool:
        keys = {"bid", "ask", "delta", "gamma", "vega", "theta"}
        return keys.issubset(self.data.keys())


def fetch_single_option(symbol: str, expiry: str, strike: float, right: str) -> dict[str, float] | None:
    """Return bid/ask and Greeks for ``symbol expiry strike right``."""
    setup_logging()
    app = SingleOptionClient(symbol, expiry, strike, right)
    logger.info(f"🚀 Ophalen van {symbol} {expiry} {strike}{right}")
    start_app(app)
    app.done.wait(timeout=15)
    app.disconnect()
    logger.info(f"Ontvangen data: {app.data}")
    return app.data if app.data else None


def run() -> None:
    fetch_single_option("MSFT", "20250620", 470, "C")


if __name__ == "__main__":
    run()
