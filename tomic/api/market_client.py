from __future__ import annotations

from typing import Any, Dict
import threading
import time
from ibapi.ticktype import TickTypeEnum

from tomic.api.base_client import BaseIBApp
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.cli.daily_vol_scraper import fetch_volatility_metrics
from tomic.models import OptionContract
try:  # pragma: no cover - optional dependency during tests
    from ibapi.contract import Contract
except Exception:  # pragma: no cover - tests provide stubs
    Contract = object  # type: ignore[misc]


class MarketClient(BaseIBApp):
    """Minimal IB client used for market data exports."""

    WARNING_ERROR_CODES: set[int] = getattr(
        BaseIBApp, "WARNING_ERROR_CODES", set()
    ) | {2104, 2106, 2158}

    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol = symbol.upper()
        self.market_data: Dict[int, Dict[str, Any]] = {}
        self.invalid_contracts: set[int] = set()
        self.spot_price: float | None = None
        self.expiries: list[str] = []
        self.connected = threading.Event()

    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        """Placeholder method to initiate market data requests."""
        logger.debug("MarketClient.start_requests called - no-op stub")

    # IB callbacks -----------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        """Called once the connection is established."""
        logger.info(f"✅ Verbonden. OrderId: {orderId}")
        self.connected.set()
        try:
            self.start_requests()
        except Exception as exc:  # pragma: no cover - runtime behaviour
            logger.error(f"start_requests failed: {exc}")

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802 - IB API callback
        if tickType in (TickTypeEnum.LAST, TickTypeEnum.DELAYED_LAST):
            self.spot_price = price
        rec = self.market_data.setdefault(reqId, {})
        rec.setdefault("prices", {})[tickType] = price

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802 - IB API callback
        rec = self.market_data.setdefault(reqId, {})
        rec.setdefault("sizes", {})[tickType] = size


class OptionChainClient(MarketClient):
    """IB client that retrieves a basic option chain."""

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)
        self.con_id: int | None = None
        self.trading_class: str | None = None
        self.strikes: list[float] = []
        self._req_id = 50

    # Helpers -----------------------------------------------------
    def _stock_contract(self) -> Contract:
        c = Contract()
        c.symbol = self.symbol
        c.secType = "STK"
        c.exchange = "SMART"
        c.primaryExchange = "SMART"
        c.currency = "USD"
        logger.debug(
            "Stock contract built: symbol=%s secType=%s exchange=%s primaryExchange=%s currency=%s",
            c.symbol,
            c.secType,
            c.exchange,
            c.primaryExchange,
            c.currency,
        )
        return c

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    # IB callbacks ------------------------------------------------
    def contractDetails(self, reqId: int, details):  # noqa: N802
        con = details.contract
        if con.secType == "STK" and self.con_id is None:
            self.con_id = con.conId
            self.trading_class = con.tradingClass or self.symbol
            self.reqSecDefOptParams(self._next_id(), self.symbol, "", "STK", self.con_id)

    def securityDefinitionOptionParameter(
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: list[str],
        strikes: list[float],
    ) -> None:  # noqa: N802
        if self.expiries:
            return
        self.expiries = sorted(expirations)
        logger.info(f"Expiries: {', '.join(self.expiries)}")
        center = round(self.spot_price or 0)
        self.strikes = sorted(s for s in strikes if center - 10 <= s <= center + 10)[:10]
        self.trading_class = tradingClass
        self._request_option_data()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: D401
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        if errorCode == 200:
            self.invalid_contracts.add(reqId)

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

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        super().tickPrice(reqId, tickType, price, attrib)
        rec = self.market_data.setdefault(reqId, {})
        if tickType == TickTypeEnum.BID:
            rec["bid"] = price
        elif tickType == TickTypeEnum.ASK:
            rec["ask"] = price

    def tickGeneric(self, reqId: int, tickType: int, value: float) -> None:  # noqa: N802
        if tickType == 100:
            self.market_data.setdefault(reqId, {})["volume"] = int(value)

    # Request orchestration --------------------------------------
    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        threading.Thread(target=self._init_requests, daemon=True).start()

    def _init_requests(self) -> None:
        self.reqMarketDataType(2)
        stk = self._stock_contract()
        logger.debug("Requesting stock quote with contract: %s", stk)
        spot_id = self._next_id()
        self.reqMktData(spot_id, stk, "", False, False, [])
        logger.debug(
            "reqMktData sent: id=%s snapshot=False for stock contract", spot_id
        )
        start = time.time()

        #TODO dit vervangen als onderstaande werkt
        #while self.spot_price is None and time.time() - start < 5:
        #    time.sleep(0.1)

        timeout = cfg_get("SPOT_TIMEOUT", 20)
        while self.spot_price is None and time.time() - start < timeout:
            time.sleep(0.1)

        self.cancelMktData(spot_id)
        self.reqContractDetails(self._next_id(), stk)
        logger.debug("reqContractDetails sent for: %s", stk)

    def _request_option_data(self) -> None:
        if not self.expiries or not self.strikes or self.trading_class is None:
            logger.debug(
                "Request option data skipped: expiries=%s strikes=%s trading_class=%s",
                self.expiries,
                self.strikes,
                self.trading_class,
            )
            return
        logger.debug(
            "Requesting option data for expiries=%s strikes=%s", self.expiries, self.strikes
        )
        for expiry in self.expiries:
            for strike in self.strikes:
                for right in ("C", "P"):
                    info = OptionContract(
                        self.symbol,
                        expiry,
                        strike,
                        right,
                        trading_class=self.trading_class,
                    )
                    logger.debug(
                        "Building option contract: %s %s %s %s",
                        info.symbol,
                        expiry,
                        strike,
                        right,
                    )
                    c = info.to_ib()
                    logger.debug("Requesting market data with contract: %s", c)
                    req_id = self._next_id()
                    self.market_data[req_id] = {
                        "expiry": expiry,
                        "strike": strike,
                        "right": right,
                    }
                    self.reqMktData(req_id, c, "", True, False, [])



def start_app(app: MarketClient) -> None:
    """Connect to TWS/IB Gateway and start ``app`` in a background thread."""
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    client_id = int(cfg_get("IB_CLIENT_ID", 100))
    app.connect(host, port, client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    start = time.time()
    while not app.connected.is_set() and time.time() - start < 5:
        time.sleep(0.1)

print("🚨 Hier kom ik!")
def await_market_data(app: MarketClient, symbol: str, timeout: int = 10) -> bool:
    """Wait until market data has been populated or timeout occurs."""
    start = time.time()
    while time.time() - start < timeout:
        if app.market_data.get("bid") is not None:
            return True
        time.sleep(0.1)
    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


def fetch_market_metrics(symbol: str) -> dict[str, Any] | None:
    """Return key volatility metrics scraped from Barchart + optional spot via IB."""
    data = fetch_volatility_metrics(symbol.upper())
    metrics: Dict[str, Any] = {
        "spot_price": data.get("spot_price"),
        "hv30": data.get("hv30"),
        "atr14": data.get("atr14"),
        "vix": data.get("vix"),
        "skew": data.get("skew"),
        "term_m1_m2": data.get("term_m1_m2"),
        "term_m1_m3": data.get("term_m1_m3"),
        "iv_rank": data.get("iv_rank"),
        "implied_volatility": data.get("implied_volatility"),
        "iv_percentile": data.get("iv_percentile"),
    }

    # Probeer live spot price van IB
    app = MarketClient(symbol)
    start_app(app)
    if hasattr(app, "start_requests"):
        app.start_requests()
    if await_market_data(app, symbol):
        metrics["spot_price"] = app.spot_price or metrics["spot_price"]
    app.disconnect()

    logger.debug(f"Fetched metrics for {symbol}: {metrics}")
    return metrics


__all__ = [
    "MarketClient",
    "OptionChainClient",
    "start_app",
    "await_market_data",
    "fetch_market_metrics",
]
