from __future__ import annotations

from typing import Any, Dict
import threading
import time
from datetime import datetime
from ibapi.ticktype import TickTypeEnum
from datetime import timedelta

try:  # pragma: no cover - optional dependency during tests
    from ibapi.utils import floatMaxString
except Exception:  # pragma: no cover - tests provide stub

    def floatMaxString(val: float) -> str:  # type: ignore[misc]
        return str(val)


from tomic.api.base_client import BaseIBApp
from tomic.config import get as cfg_get
from tomic.logutils import logger, log_result
from tomic.cli.daily_vol_scraper import fetch_volatility_metrics
from tomic.models import OptionContract
from tomic.utils import (
    extract_weeklies,
    extract_monthlies,
    filter_future_expiries,
)

try:  # pragma: no cover - optional dependency during tests
    from ibapi.contract import Contract
except Exception:  # pragma: no cover - tests provide stubs
    Contract = object  # type: ignore[misc]


def contract_repr(contract):
    return (
        f"{contract.secType} {contract.symbol} "
        f"{contract.lastTradeDateOrContractMonth or ''} "
        f"{contract.right or ''}{floatMaxString(contract.strike)} "
        f"{contract.exchange or ''} {contract.currency or ''} "
        f"(conId={contract.conId})"
    ).strip()


class MarketClient(BaseIBApp):
    """Minimal IB client used for market data exports."""

    WARNING_ERROR_CODES: set[int] = getattr(BaseIBApp, "WARNING_ERROR_CODES", set()) | {
        2104,
        2106,
        2158,
    }

    def __init__(self, symbol: str, primary_exchange: str | None = None) -> None:
        super().__init__()
        self.symbol = symbol.upper()
        self.primary_exchange = primary_exchange or cfg_get("PRIMARY_EXCHANGE", "SMART")
        self.stock_con_id: int | None = None
        self.market_data: Dict[int, Dict[str, Any]] = {}
        self.invalid_contracts: set[int] = set()
        self.spot_price: float | None = None
        self.expiries: list[str] = []
        self.connected = threading.Event()
        self.data_event = threading.Event()
        self._req_id = 50
        self._spot_req_id: int | None = None

    # Helpers -----------------------------------------------------
    @log_result
    def _stock_contract(self) -> Contract:
        c = Contract()
        c.symbol = self.symbol
        c.secType = "STK"
        c.exchange = "SMART"
        c.primaryExchange = self.primary_exchange
        c.currency = "USD"
        if self.stock_con_id is not None:
            c.conId = self.stock_con_id
        logger.debug(
            f"Stock contract built: symbol={c.symbol} secType={c.secType} "
            f"exchange={c.exchange} primaryExchange={c.primaryExchange} "
            f"currency={c.currency} conId={getattr(c, 'conId', None)}"
        )
        return c

    @log_result
    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    @log_result
    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        """Request a basic stock quote for ``self.symbol``."""
        contract = self._stock_contract()
        self.reqMarketDataType(2)
        req_id = self._next_id()
        logger.debug(f"Requesting stock quote for symbol={contract.symbol} id={req_id}")
        self.reqMktData(req_id, contract, "", False, False, [])
        self._spot_req_id = req_id
        timeout = cfg_get("SPOT_TIMEOUT", 10)
        self.data_event.clear()
        self.data_event.wait(timeout)
        if self.spot_price is not None:
            self.cancelMktData(req_id)

    # IB callbacks -----------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        """Called once the connection is established."""
        logger.info(f"✅ [stap 2] Verbonden. OrderId: {orderId}")
        self.connected.set()
        try:
            self.start_requests()
        except Exception as exc:  # pragma: no cover - runtime behaviour
            logger.error(f"start_requests failed: {exc}")

    def tickPrice(
        self, reqId: int, tickType: int, price: float, attrib
    ) -> None:  # noqa: N802 - IB API callback
        if tickType in (TickTypeEnum.LAST, TickTypeEnum.DELAYED_LAST):
            self.spot_price = price
            if price > 0:
                logger.info(f"✅ [stap 3] Spotprijs: {price}")
        if tickType in (
            TickTypeEnum.LAST,
            TickTypeEnum.BID,
            TickTypeEnum.ASK,
            getattr(TickTypeEnum, "DELAYED_LAST", TickTypeEnum.LAST),
            getattr(TickTypeEnum, "DELAYED_BID", TickTypeEnum.BID),
            getattr(TickTypeEnum, "DELAYED_ASK", TickTypeEnum.ASK),
        ):
            self.data_event.set()
        rec = self.market_data.setdefault(reqId, {})
        rec.setdefault("prices", {})[tickType] = price

    def tickSize(
        self, reqId: int, tickType: int, size: int
    ) -> None:  # noqa: N802 - IB API callback
        rec = self.market_data.setdefault(reqId, {})
        rec.setdefault("sizes", {})[tickType] = size


class OptionChainClient(MarketClient):
    """IB client that retrieves a basic option chain."""

    def __init__(self, symbol: str, primary_exchange: str | None = None) -> None:
        super().__init__(symbol, primary_exchange=primary_exchange)
        self.con_id: int | None = None
        self.trading_class: str | None = None
        self.strikes: list[float] = []
        self._strike_lookup: dict[float, float] = {}
        self.weeklies: list[str] = []
        self.monthlies: list[str] = []

        # Voor foutopsporing van contracten
        self._pending_details: dict[int, OptionContract] = {}

        # Voor synchronisatie van option param callback
        self.option_params_complete = threading.Event()
        self._logged_data: set[int] = set()
        self._step6_logged = False
        self._step7_logged = False
        self._step8_logged = False
        self._step9_logged = False

    # IB callbacks ------------------------------------------------
    @log_result
    def contractDetails(self, reqId: int, details):  # noqa: N802
        con = details.contract
        logger.debug(
            f"contractDetails callback: reqId={reqId}, conId={con.conId}, type={con.secType}"
        )
        if con.secType == "STK" and self.con_id is None:
            self.con_id = con.conId
            self.stock_con_id = con.conId
            self.trading_class = con.tradingClass or self.symbol
            logger.info(
                f"✅ [stap 4] ConId: {self.con_id}, TradingClass: {self.trading_class}. primaryExchange: {con.primaryExchange}"
            )
            logger.info("▶️ START stap 5 - reqSecDefOptParams() voor optieparameters")
            self.reqSecDefOptParams(
                self._next_id(), self.symbol, "", "STK", self.con_id
            )

        elif reqId in self._pending_details:
            if not self._step8_logged:
                logger.info("▶️ START stap 8 - Callback: contractDetails() voor opties")
                self._step8_logged = True
            logger.debug(
                f"contractDetails received for reqId={reqId} conId={con.conId}"
            )
            self.market_data.setdefault(reqId, {})["conId"] = con.conId
            # Log contract fields returned by IB before requesting market data
            logger.debug(
                f"Using contract for reqId={reqId}: "
                f"conId={con.conId} symbol={con.symbol} "
                f"expiry={con.lastTradeDateOrContractMonth} strike={con.strike} "
                f"right={con.right} exchange={con.exchange} primaryExchange={con.primaryExchange} "
                f"tradingClass={getattr(con, 'tradingClass', '')} multiplier={getattr(con, 'multiplier', '')}"
            )
            # Request market data with validated contract
            logger.debug(f"reqMktData sent for: {contract_repr(con)}")
            self.reqMktData(reqId, con, "", True, False, [])
            logger.info(
                f"✅ [stap 8] reqMktData sent for {con.symbol} {con.lastTradeDateOrContractMonth} {con.strike} {con.right}"
            )
            self._pending_details.pop(reqId, None)
            logger.debug(
                f"contractDetails ontvangen: {con.symbol} {con.lastTradeDateOrContractMonth} {con.strike} {con.right}"
            )

    @log_result
    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId in self._pending_details:
            info = self._pending_details.pop(reqId)
            logger.warning(
                f"Geen contractdetails gevonden voor {info.symbol} {info.expiry} {info.strike} {info.right}"
            )
            self.invalid_contracts.add(reqId)

    @log_result
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

        # ``expirations`` is returned as a ``set`` by the IB API.  It cannot be
        # sliced directly, so convert it to a sorted list first for logging and
        # further processing.
        exp_list = sorted(expirations)
        logger.debug(f"spot_price={self.spot_price}, expirations={exp_list[:5]}")

        logger.info(
            f"✅ [stap 5] Optieparameters ontvangen: {len(expirations)} expiries, {len(strikes)} strikes"
        )

        # Zorg dat spot_price beschikbaar is
        if self.spot_price is None:
            logger.warning(
                "Spot price not yet available. Waiting for spot price before processing expiries."
            )
            self.data_event.clear()
            self.data_event.wait(10)

        # Stop als spot_price nog steeds ontbreekt
        if self.spot_price is None:
            logger.error(
                "❌ FAIL stap 3: Spot price not available after timeout. "
                "Skipping option data request."
            )
            return

        if not self._step6_logged:
            logger.info(
                "▶️ START stap 6 - Selectie van relevante expiries + strikes (binnen ±10 pts spot)"
            )
            self._step6_logged = True
        future = filter_future_expiries(exp_list)
        self.monthlies = extract_monthlies(future, 3)
        self.weeklies = extract_weeklies(future, 4)
        unique = {
            datetime.strptime(e, "%Y%m%d").date()
            for e in self.monthlies + self.weeklies
        }
        self.expiries = [d.strftime("%Y%m%d") for d in sorted(unique)]
        logger.info(f"✅ [stap 6] Geselecteerde expiries: {', '.join(self.expiries)}")

        center = round(self.spot_price or 0)
        strike_map: dict[float, float] = {}
        for strike in sorted(strikes):
            rounded = round(strike)
            if abs(rounded - center) <= 10:
                strike_map.setdefault(rounded, strike)
        self.strikes = sorted(strike_map.keys())
        self._strike_lookup = strike_map
        self.trading_class = tradingClass
        logger.info(
            f"✅ [stap 6] Geselecteerde strikes: {', '.join(str(s) for s in self.strikes)}"
        )

    def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:  # noqa: N802
        """Mark option parameter retrieval as complete."""
        logger.debug(f"securityDefinitionOptionParameterEnd received for reqId={reqId}")
        self.option_params_complete.set()

    @log_result
    def error(
        self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""
    ):  # noqa: D401
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        if errorCode == 200:
            info = self._pending_details.get(reqId)
            if info is not None:
                logger.debug(f"Invalid contract for id {reqId}: {info}")
            self.invalid_contracts.add(reqId)

    @log_result
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
        if reqId != self._spot_req_id and reqId not in self._logged_data:
            if not self._step9_logged:
                logger.info(
                    "▶️ START stap 9 - Ontvangen van market data (bid/ask/Greeks)"
                )
                self._step9_logged = True
            details = []
            if "bid" in rec:
                details.append(f"bid={rec['bid']}")
            if "ask" in rec:
                details.append(f"ask={rec['ask']}")
            if "iv" in rec:
                details.append(f"iv={rec['iv']}")
            if "delta" in rec:
                details.append(f"delta={rec['delta']}")
            if "gamma" in rec:
                details.append(f"gamma={rec['gamma']}")
            if "vega" in rec:
                details.append(f"vega={rec['vega']}")
            if "theta" in rec:
                details.append(f"theta={rec['theta']}")
            info = ", ".join(details)
            logger.info(f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}")
            self._logged_data.add(reqId)
        logger.debug(
            "tickOptionComputation reqId={} type={} iv={} delta={} gamma={} vega={} theta={}".format(
                reqId,
                TickTypeEnum.toStr(tickType),
                impliedVol,
                delta,
                gamma,
                vega,
                theta,
            )
        )

    @log_result
    def tickPrice(
        self, reqId: int, tickType: int, price: float, attrib
    ) -> None:  # noqa: N802
        super().tickPrice(reqId, tickType, price, attrib)
        rec = self.market_data.setdefault(reqId, {})
        if tickType == TickTypeEnum.BID:
            rec["bid"] = price
        elif tickType == TickTypeEnum.ASK:
            rec["ask"] = price
        if price == -1 and tickType in (TickTypeEnum.BID, TickTypeEnum.ASK):
            self.invalid_contracts.add(reqId)
        if (
            price != -1
            and tickType in (TickTypeEnum.BID, TickTypeEnum.ASK)
            and reqId not in self._logged_data
            and reqId != self._spot_req_id
        ):
            if not self._step9_logged:
                logger.info(
                    "▶️ START stap 9 - Ontvangen van market data (bid/ask/Greeks)"
                )
                self._step9_logged = True
            details = []
            if "bid" in rec:
                details.append(f"bid={rec['bid']}")
            if "ask" in rec:
                details.append(f"ask={rec['ask']}")
            info = ", ".join(details)
            logger.info(f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}")
            self._logged_data.add(reqId)
        logger.debug(
            f"tickPrice reqId={reqId} type={TickTypeEnum.toStr(tickType)} price={price}"
        )

    @log_result
    def tickGeneric(
        self, reqId: int, tickType: int, value: float
    ) -> None:  # noqa: N802
        if tickType == 100:
            self.market_data.setdefault(reqId, {})["volume"] = int(value)
            logger.debug(f"tickGeneric reqId={reqId} type={tickType} value={value}")

    # Request orchestration --------------------------------------
    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        threading.Thread(target=self._init_requests, daemon=True).start()

    @log_result
    def _init_requests(self) -> None:
        stk = self._stock_contract()
        logger.debug(f"Requesting stock quote with contract: {stk}")

        logger.info("▶️ START stap 3 - Spot price ophalen")

        data_type_success = None
        short_timeout = cfg_get("DATA_TYPE_TIMEOUT", 2)
        for data_type in (1, 3, 4):
            self.reqMarketDataType(data_type)
            logger.debug(f"reqMarketDataType({data_type})")
            spot_id = self._next_id()
            self.reqMktData(spot_id, stk, "", False, False, [])
            self._spot_req_id = spot_id
            logger.debug(
                f"reqMktData sent: id={spot_id} snapshot=False for stock contract"
            )
            start = time.time()
            while self.spot_price is None and time.time() - start < short_timeout:
                time.sleep(0.1)
            self.cancelMktData(spot_id)
            if self.spot_price is not None:
                data_type_success = data_type
                logger.debug(f"Market data type {data_type} succeeded")
                break

        if self.spot_price is None:
            start = time.time()
            timeout = cfg_get("SPOT_TIMEOUT", 20)
            while self.spot_price is None and time.time() - start < timeout:
                time.sleep(0.1)
            self.cancelMktData(spot_id)

        if self.spot_price is None:
            logger.error("❌ FAIL stap 3: Spot price not available after all retries")

        if self.con_id is None:
            logger.info("▶️ START stap 4 - ContractDetails ophalen voor STK")
            logger.debug(
                f"Requesting contract details for: symbol={stk.symbol}, expiry={stk.lastTradeDateOrContractMonth}, strike={floatMaxString(stk.strike)}, right={stk.right}"
            )
            self.reqContractDetails(self._next_id(), stk)
            logger.debug(f"reqContractDetails sent for: {contract_repr(stk)}")

        # Wait until all option parameters have been received before
        # requesting option market data
        if not self.option_params_complete.wait(timeout=20):
            logger.error("❌ FAIL stap 5: Timeout waiting for option parameters")
            return

        self._request_option_data()

    @log_result
    def _request_option_data(self) -> None:
        if not self.expiries or not self.strikes or self.trading_class is None:
            logger.debug(
                f"Request option data skipped: expiries={self.expiries} "
                f"strikes={self.strikes} trading_class={self.trading_class}"
            )
            return
        logger.debug(f"Spot price at _request_option_data: {self.spot_price}")
        logger.debug(
            f"Requesting option data for expiries={self.expiries} strikes={self.strikes}"
        )
        if not self._step7_logged:
            logger.info(
                "▶️ START stap 7 - Per combinatie optiecontract bouwen en reqContractDetails()"
            )
            self._step7_logged = True
        for expiry in self.expiries:
            for strike in self.strikes:
                actual = self._strike_lookup.get(strike, strike)
                for right in ("C", "P"):
                    info = OptionContract(
                        self.symbol,
                        expiry,
                        actual,
                        right,
                        trading_class=self.trading_class,
                    )
                    logger.debug(
                        f"Building option contract: {info.symbol} {expiry} {actual} {right}"
                    )
                    c = info.to_ib()
                    req_id = self._next_id()
                    logger.debug(
                        f"reqId for {c.symbol} {c.lastTradeDateOrContractMonth} {c.strike} {c.right} is {req_id}"
                    )
                    self.market_data[req_id] = {
                        "expiry": expiry,
                        "strike": strike,
                        "right": right,
                    }
                    self._pending_details[req_id] = info
                    # Request contract details first to validate the option
                    self.reqContractDetails(req_id, c)
                    logger.info(
                        f"✅ [stap 7] reqId {req_id} contract {c.symbol} {c.lastTradeDateOrContractMonth} {c.strike} {c.right} sent"
                    )

        logger.debug(
            f"Aantal contractdetails aangevraagd: {len(self._pending_details)}"
        )


@log_result
def start_app(app: MarketClient) -> None:
    """Connect to TWS/IB Gateway and start ``app`` in a background thread."""
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    client_id = int(cfg_get("IB_CLIENT_ID", 100))
    logger.debug(f"Connecting app to host={host} port={port} id={client_id}")
    app.connect(host, port, client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    start = time.time()
    while not app.connected.is_set() and time.time() - start < 5:
        time.sleep(0.1)
    logger.debug(
        "IB app connected" if app.connected.is_set() else "IB app connect timeout"
    )


@log_result
def await_market_data(app: MarketClient, symbol: str, timeout: int = 30) -> bool:
    """Wait until market data has been populated or timeout occurs."""
    start = time.time()

    while time.time() - start < timeout:
        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            break
        app.data_event.wait(remaining)

        if app.spot_price is not None and (
            not isinstance(app, OptionChainClient)
            or any("bid" in rec or "ask" in rec for rec in app.market_data.values())
        ):
            logger.debug(f"Market data ontvangen binnen {time.time() - start:.2f}s")
            return True

        if any("bid" in rec or "ask" in rec for rec in app.market_data.values()):
            logger.debug(f"Bid/ask ontvangen binnen {time.time() - start:.2f}s")
            return True

        app.data_event.clear()

    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


@log_result
def fetch_market_metrics(
    symbol: str, app: MarketClient | None = None
) -> dict[str, Any] | None:
    """Return key volatility metrics scraped from Barchart and optional spot price.

    When ``app`` is provided it must already be connected; this function will use
    it to retrieve the spot price without opening a new IB session. If ``app`` is
    ``None`` a temporary :class:`MarketClient` session is created and closed.
    """

    logger.debug(f"Fetching metrics for {symbol}")
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

    owns_app = False
    if app is None:
        app = MarketClient(symbol)
        start_app(app)
        owns_app = True

    if await_market_data(app, symbol):
        metrics["spot_price"] = app.spot_price or metrics["spot_price"]

    if owns_app:
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
