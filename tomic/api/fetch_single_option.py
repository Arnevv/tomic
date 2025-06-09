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
from ibapi.contract import ContractDetails
from loguru import logger


class StepByStepClient(EWrapper, EClient):
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
        self.option_info: Dict[int, ContractDetails] = {}
        self.market_data: Dict[int, Dict[str, object]] = {}
        self.contract_received: threading.Event = threading.Event()

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

    def nextValidId(self, orderId: int) -> None:
        self.connected.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:
        if reqId == 1 and tickType in (TickTypeEnum.LAST, TickTypeEnum.DELAYED_LAST):
            if price > 0:
                self.spot_price = price
                self.spot_event.set()
        elif reqId != 1:
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
    ) -> None:
        rec = self.market_data.setdefault(reqId, {})
        rec["iv"] = impliedVol
        rec["delta"] = delta
        rec["gamma"] = gamma
        rec["vega"] = vega
        rec["theta"] = theta

    def contractDetails(self, reqId: int, details: ContractDetails) -> None:
        con = details.contract
        if con.secType == "STK":
            self.con_id = con.conId
            self.trading_class = con.tradingClass or self.symbol
            self.primary_exchange = con.primaryExchange or "SMART"
            self.details_event.set()
        elif con.secType == "OPT":
            self.option_info[reqId] = details
            rec = self.market_data.setdefault(reqId, {})
            rec.update({
                "conId": con.conId,
                "expiry": con.lastTradeDateOrContractMonth,
                "strike": con.strike,
                "right": con.right,
            })
            self.reqMktData(reqId, con, "", False, False, [])
            logger.info(f"✅ contractDetails ontvangen voor reqId {reqId} ({con.localSymbol})")
            self.contract_received.set()

    def contractDetailsEnd(self, reqId: int):
        self.contract_received.set()

    def securityDefinitionOptionParameter(
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: List[str],
        strikes: List[float],
    ) -> None:
        if not self.all_expiries and expirations:
            self.all_expiries = sorted(expirations)
            self.all_strikes = sorted(strikes)
            self.params_event.set()


# --- geen wijzigingen nodig voor export_csv en main (deze blijven zoals ze zijn) ---

# --- Stap 7a: test met volledig opgebouwd contract ---
def test_contractdetails_manueel(client: StepByStepClient):
    logger.info("▶️ START stap 7a - Test contractDetails met volledige parameters")
    c = Contract()
    c.symbol = "MSFT"
    c.secType = "OPT"
    c.exchange = "SMART"
    c.currency = "USD"
    c.lastTradeDateOrContractMonth = "20250620"
    c.strike = 472.5
    c.right = "C"
    c.multiplier = "100"
    c.tradingClass = "MSFT"
    req_id = client._next_id()
    client.reqContractDetails(req_id, c)
    client.contract_received.wait(timeout=10)
    logger.info("✅ Test stap 7a afgerond")


# --- Stap 7b: test met alleen conId ---
def test_contractdetails_conid(client: StepByStepClient):
    logger.info("▶️ START stap 7b - Test contractDetails met alleen conId")
    c = Contract()
    c.conId = 785501851
    c.secType = "OPT"
    c.exchange = "SMART"
    c.currency = "USD"
    req_id = client._next_id()
    client.reqContractDetails(req_id, c)
    client.contract_received.wait(timeout=10)
    logger.info("✅ Test stap 7b afgerond")


# --- Aangepaste run-functie ---
def run_tests():
    logger.info("🧪 Testmodus actief - stap 7 tijdelijk overgeslagen")
    client = StepByStepClient(symbol="MSFT")
    client.connect("127.0.0.1", 7497, 999)
    client_thread = threading.Thread(target=client.run, daemon=True)
    client_thread.start()
    client.connected.wait(timeout=5)
    test_contractdetails_manueel(client)
    test_contractdetails_conid(client)
    client.disconnect()


def export_csv(app: StepByStepClient, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(
        output_dir,
        f"option_chain_{app.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Symbol", "Expiry", "Strike", "Type", "Bid", "Ask", "IV", "Delta", "Gamma", "Vega", "Theta"])
        for req_id, rec in app.market_data.items():
            if req_id == 1:
                continue  # skip spotprijs request
            if rec.get("bid") is None and rec.get("ask") is None:
                continue
            writer.writerow([
                app.symbol, rec.get("expiry"), rec.get("strike"), rec.get("right"),
                rec.get("bid"), rec.get("ask"), rec.get("iv"), rec.get("delta"),
                rec.get("gamma"), rec.get("vega"), rec.get("theta")])
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
    logger.info(f"✅ SUCCES stap 4 - conId {app.con_id}, tradingClass {app.trading_class}, primaryExchange {app.primary_exchange}")

    logger.info("▶️ START stap 5 - Optieparameters ophalen")
    req_id = app._next_id()
    app.reqSecDefOptParams(req_id, symbol, "", "STK", int(app.con_id))
    if not app.params_event.wait(10):
        logger.error("❌ FAIL stap 5: geen optieparameters")
        app.disconnect()
        return
    logger.info(f"✅ SUCCES stap 5 - {len(app.all_expiries)} expiries, {len(app.all_strikes)} strikes")

    logger.info("▶️ START stap 6 - Selectie van relevante expiries en strikes")
    center = round(app.spot_price or 0)
    app.strikes = [s for s in app.all_strikes if abs(round(s) - center) <= 10]
    app.expiries = app.all_expiries[:4]
    if not app.strikes or not app.expiries:
        logger.error("❌ FAIL stap 6: geen geldige strikes/expiries")
        app.disconnect()
        return
    logger.info(f"✅ SUCCES stap 6 - {len(app.expiries)} expiries, {len(app.strikes)} strikes")

    logger.info("▶️ START stap 7 - Optiecontracten ophalen via IB")
    contracts_requested = 0
    for expiry in app.expiries:
        for strike in app.strikes:
            for right in ("C", "P"):
                c = Contract()
                c.symbol = symbol
                c.secType = "OPT"
                c.currency = "USD"
                c.exchange = "SMART"
                c.lastTradeDateOrContractMonth = expiry
                c.strike = strike
                c.right = right
                c.tradingClass = app.trading_class
                req_id = app._next_id()
                app.contract_received.clear()
                app.reqContractDetails(req_id, c)
                if not app.contract_received.wait(2):
                    logger.warning(f"❌ contractDetails MISSING voor reqId {req_id}")
                contracts_requested += 1
    received = len(app.option_info)
    logger.info(f"✅ SUCCES stap 7 - {received}/{contracts_requested} contractdetails ontvangen")

    if received == 0:
        logger.error("❌ FAIL stap 8: geen geldige optiecontractdetails ontvangen")
        app.disconnect()
        return

    logger.info("▶️ START stap 9 - Ontvangen van market data")
    if not app.market_event.wait(20):
        logger.error("❌ FAIL stap 9: geen market data")
        app.disconnect()
        return
    logger.info("✅ SUCCES stap 9 - Market data ontvangen")

    logger.info("▶️ START stap 10 - Export naar CSV")
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
