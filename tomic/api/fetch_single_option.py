"""Standalone script to fetch option chain data step by step via the TWS API."""

from __future__ import annotations

import csv
import os
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper
from ibapi.ticktype import TickTypeEnum
from loguru import logger


class StepByStepClient(EWrapper, EClient):
    """Minimal IB client that retrieves option chain data step by step."""

    def __init__(self, symbol: str) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self.symbol = symbol
        self.req_id = 0
        self.connected = threading.Event()
        self.spot_event = threading.Event()
        self.details_event = threading.Event()
        self.params_event = threading.Event()
        self.market_event = threading.Event()
        self.spot_price: float | None = None
        self.con_id: int | None = None
        self.trading_class: str | None = None
        self.primary_exchange: str | None = None
        self.all_strikes: List[float] = []
        self.all_expiries: List[str] = []
        self.strikes: List[float] = []
        self.expiries: List[str] = []
        self.option_info: Dict[int, Dict[str, object]] = {}
        self.market_data: Dict[int, Dict[str, object]] = {}

    # Helpers -----------------------------------------------------
    def _next_id(self) -> int:
        self.req_id += 1
        return self.req_id

    def _stock_contract(self) -> Contract:
        c = Contract()
        c.symbol = self.symbol
        c.secType = "STK"
        c.exchange = "SMART"
        c.currency = "USD"
        return c

    # IB callbacks ------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        if reqId == 1 and tickType in (TickTypeEnum.LAST, TickTypeEnum.DELAYED_LAST):
            if price > 0:
                self.spot_price = price
                self.spot_event.set()
        else:
            rec = self.market_data.setdefault(reqId, {})
            if tickType == TickTypeEnum.BID:
                rec["bid"] = price
            elif tickType == TickTypeEnum.ASK:
                rec["ask"] = price
            if (rec.get("bid") is not None and rec.get("bid") != -1) or (
                rec.get("ask") is not None and rec.get("ask") != -1
            ):
                self.market_event.set()

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
        rec = self.market_data.setdefault(reqId, {})
        rec["iv"] = impliedVol
        rec["delta"] = delta
        rec["gamma"] = gamma
        rec["vega"] = vega
        rec["theta"] = theta

    def contractDetails(self, reqId: int, details) -> None:  # noqa: N802
        con = details.contract
        if con.secType == "STK":
            self.con_id = con.conId
            self.trading_class = con.tradingClass or self.symbol
            self.primary_exchange = con.primaryExchange or "SMART"
            self.details_event.set()
        elif reqId in self.option_info:
            self.market_data.setdefault(reqId, {})["conId"] = con.conId
            self.reqMktData(reqId, con, "", False, False, [])

    def securityDefinitionOptionParameter(
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: List[str],
        strikes: List[float],
    ) -> None:  # noqa: N802
        if not self.all_expiries and expirations:
            self.all_expiries = sorted(expirations)
            self.all_strikes = sorted(strikes)
            self.params_event.set()


def export_csv(app: StepByStepClient, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(
        output_dir,
        f"option_chain_{app.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Symbol",
                "Expiry",
                "Strike",
                "Type",
                "Bid",
                "Ask",
                "IV",
                "Delta",
                "Gamma",
                "Vega",
                "Theta",
            ]
        )
        for rec in app.market_data.values():
            if rec.get("bid") is None and rec.get("ask") is None:
                continue
            writer.writerow(
                [
                    app.symbol,
                    rec.get("expiry"),
                    rec.get("strike"),
                    rec.get("right"),
                    rec.get("bid"),
                    rec.get("ask"),
                    rec.get("iv"),
                    rec.get("delta"),
                    rec.get("gamma"),
                    rec.get("vega"),
                    rec.get("theta"),
                ]
            )
    logger.info(f"✅ SUCCES stap 10 - CSV opgeslagen in {path}")


def run(symbol: str, output_dir: str) -> None:
    symbol = symbol.strip().upper()
    logger.info("▶️ START stap 1 - Invoer van symbool")
    if not symbol.isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool")
        return
    logger.info(f"✅ Symbool: {symbol}")

    logger.info("▶️ START stap 2 - Verbinding met IB")
    app = StepByStepClient(symbol)
    app.connect("127.0.0.1", 7497, 100)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    if not app.connected.wait(5):
        logger.error("❌ FAIL stap 2: geen bevestiging van IB")
        return
    logger.info("✅ SUCCES stap 2 - Verbonden")

    logger.info("▶️ START stap 3 - Spotprijs ophalen")
    spot_id = 1
    app.reqMarketDataType(1)
    app.reqMktData(spot_id, app._stock_contract(), "", False, False, [])
    if not app.spot_event.wait(10):
        logger.error("❌ FAIL stap 3: geen spotprijs ontvangen")
        app.disconnect()
        return
    app.cancelMktData(spot_id)
    logger.info(f"✅ SUCCES stap 3 - Spotprijs {app.spot_price}")

    logger.info("▶️ START stap 4 - Contractdetails ophalen")
    req_id = app._next_id()
    app.reqContractDetails(req_id, app._stock_contract())
    if not app.details_event.wait(10):
        logger.error("❌ FAIL stap 4: geen contractdetails")
        app.disconnect()
        return
    logger.info(
        f"✅ SUCCES stap 4 - conId {app.con_id}, tradingClass {app.trading_class}"
    )

    logger.info("▶️ START stap 5 - Optieparameters ophalen")
    req_id = app._next_id()
    app.reqSecDefOptParams(req_id, symbol, "", "STK", int(app.con_id))
    if not app.params_event.wait(10):
        logger.error("❌ FAIL stap 5: geen optieparameters")
        app.disconnect()
        return
    logger.info(
        f"✅ SUCCES stap 5 - {len(app.all_expiries)} expiries, {len(app.all_strikes)} strikes"
    )

    logger.info("▶️ START stap 6 - Selectie van relevante expiries en strikes")
    center = round(app.spot_price or 0)
    app.strikes = [s for s in app.all_strikes if abs(round(s) - center) <= 10]
    app.expiries = app.all_expiries[:1]
    if not app.strikes or not app.expiries:
        logger.error("❌ FAIL stap 6: geen geldige strikes/expiries")
        app.disconnect()
        return
    logger.info(
        f"✅ SUCCES stap 6 - {len(app.expiries)} expiries, {len(app.strikes)} strikes"
    )

    logger.info("▶️ START stap 7 - Optiecontracten bouwen")
    for expiry in app.expiries:
        for strike in app.strikes:
            for right in ("C", "P"):
                c = Contract()
                c.symbol = symbol
                c.secType = "OPT"
                c.exchange = app.primary_exchange or "SMART"
                c.currency = "USD"
                c.lastTradeDateOrContractMonth = expiry
                c.strike = strike
                c.right = right
                c.tradingClass = app.trading_class
                req_id = app._next_id()
                app.option_info[req_id] = {
                    "expiry": expiry,
                    "strike": strike,
                    "right": right,
                }
                app.reqContractDetails(req_id, c)

    logger.info("▶️ START stap 8 - Wachten op contractdetails voor opties")
    time.sleep(2)  # small delay for callbacks

    logger.info("▶️ START stap 9 - Ontvangen van market data")
    if not app.market_event.wait(20):
        logger.error("❌ FAIL stap 9: geen market data")
        app.disconnect()
        return
    logger.info("✅ SUCCES stap 9 - Market data ontvangen")

    export_csv(app, output_dir)
    app.disconnect()


def main(argv: List[str] | None = None) -> None:
    from loguru import logger as _logger

    _logger.remove()
    _logger.add(sys.stderr, level="INFO", format="{level} - {time:HH:mm:ss}: {message}")

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("Usage: fetch_single_option.py SYMBOL [OUTPUT_DIR]")
        return
    symbol = argv[0]
    output = argv[1] if len(argv) > 1 else "exports"
    run(symbol, output)


if __name__ == "__main__":
    main()
