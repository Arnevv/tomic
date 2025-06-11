from __future__ import annotations

"""Market data clients for retrieving spot prices and option chains.

``OptionChainClient.contractDetails`` stores the underlying's
``trading_class`` and ``primary_exchange`` when it receives details for the
stock contract.  ``OptionContract.to_ib`` then uses these values when building
option contracts so that requests match the underlying's market data.
"""

from typing import Any, Dict
import threading
import time
from datetime import datetime, timedelta
from ibapi.ticktype import TickTypeEnum

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
    _is_weekly,
    _is_third_friday,
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
        f"(conId={getattr(contract, 'conId', None)})"
    ).strip()


def is_market_open(trading_hours: str, now: datetime) -> bool:
    """Return ``True`` if ``now`` falls within ``trading_hours``."""

    day = now.strftime("%Y%m%d")
    for part in trading_hours.split(";"):
        if ":" not in part:
            continue
        date_part, hours_part = part.split(":", 1)
        if date_part != day:
            continue
        if hours_part == "CLOSED":
            return False
        for session in hours_part.split(","):
            try:
                start_str, end_str = session.split("-")
            except ValueError:
                continue
            # remove any appended date information (e.g. "1700-0611:2000")
            start_str = start_str.split(":")[-1][:4]
            end_str = end_str.split(":")[0][:4]
            start_dt = datetime.strptime(day + start_str, "%Y%m%d%H%M")
            end_dt = datetime.strptime(day + end_str, "%Y%m%d%H%M")
            # handle sessions that cross midnight
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            if start_dt <= now <= end_dt:
                return True
        return False
    return False


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
        self.trading_hours: str | None = None
        self.server_time: datetime | None = None
        self._time_event = threading.Event()
        self._details_event = threading.Event()
        self.market_open: bool = False

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
        """Request a basic stock quote for ``self.symbol`` with data type fallback."""
        contract = self._stock_contract()

        # Determine whether the market is currently open
        self._details_event.clear()
        self.reqContractDetails(self._next_id(), contract)
        self._details_event.wait(2)
        self._time_event.clear()
        self.reqCurrentTime()
        self._time_event.wait(2)

        market_open = False
        if self.trading_hours and self.server_time:
            market_open = is_market_open(self.trading_hours, self.server_time)
        self.market_open = market_open

        data_type_success = None
        short_timeout = cfg_get("DATA_TYPE_TIMEOUT", 2)
        data_types = (1, 2, 3) if market_open else (3,)
        for data_type in data_types:
            self.reqMarketDataType(data_type)
            logger.debug(f"reqMarketDataType({data_type})")
            req_id = self._next_id()
            self.data_event.clear()
            self.reqMktData(req_id, contract, "", False, False, [])
            self._spot_req_id = req_id
            logger.debug(
                f"Requesting stock quote for symbol={contract.symbol} id={req_id}"
            )
            if self.data_event.wait(short_timeout) or self.spot_price is not None:
                data_type_success = data_type
                self.cancelMktData(req_id)
                break
            self.cancelMktData(req_id)

        if self.spot_price is None:
            timeout = cfg_get("SPOT_TIMEOUT", 10)
            self.data_event.clear()
            if data_type_success is not None:
                self.reqMarketDataType(data_type_success)
            self.reqMktData(req_id, contract, "", False, False, [])
            self.data_event.wait(timeout)
            self.cancelMktData(req_id)

        if (self.spot_price is None or self.spot_price <= 0):
            fallback = fetch_volatility_metrics(self.symbol).get("spot_price")
            if fallback is not None:
                try:
                    self.spot_price = float(fallback)
                    logger.info(
                        f"✅ [stap 3] Spotprijs fallback: {self.spot_price}"
                    )
                except (TypeError, ValueError):
                    logger.warning("Fallback spot price could not be parsed")

        if self.spot_price is None:
            logger.error("❌ FAIL stap 3: Spot price not available after all retries")

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
        if (
            reqId == self._spot_req_id
            and tickType in (TickTypeEnum.LAST, TickTypeEnum.DELAYED_LAST)
        ):
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

    def currentTime(self, time: int) -> None:  # noqa: N802
        self.server_time = datetime.fromtimestamp(time)
        self._time_event.set()

    def contractDetails(self, reqId: int, details) -> None:  # noqa: N802
        self.trading_hours = getattr(details, "tradingHours", "")
        self._details_event.set()


class OptionChainClient(MarketClient):
    """IB client that retrieves a basic option chain."""

    def __init__(
        self,
        symbol: str,
        primary_exchange: str | None = None,
        max_concurrent_requests: int | None = None,
    ) -> None:
        super().__init__(symbol, primary_exchange=primary_exchange)
        if max_concurrent_requests is None:
            max_concurrent_requests = int(cfg_get("MAX_CONCURRENT_REQUESTS", 5))
        self._detail_semaphore = threading.Semaphore(max_concurrent_requests)
        self.con_id: int | None = None
        self.trading_class: str | None = None
        self.strikes: list[float] = []
        self._strike_lookup: dict[float, float] = {}
        self.weeklies: list[str] = []
        self.monthlies: list[str] = []
        self.multiplier: str = "100"

        # Voor foutopsporing van contracten
        self._pending_details: dict[int, OptionContract] = {}

        # ContractDetails info for successfully validated options
        self.option_info: Dict[int, Any] = {}
        self.con_ids: Dict[tuple[str, float, str], int] = {}

        # Voor synchronisatie van option param callback
        self.option_params_complete = threading.Event()
        self.spot_event = threading.Event()
        self.details_event = threading.Event()
        self.params_event = threading.Event()
        self.contract_received = threading.Event()
        self.market_event = threading.Event()
        self.all_data_event = threading.Event()
        self.expected_contracts = 0
        self._completed_requests: set[int] = set()
        self._logged_data: set[int] = set()
        self._step6_logged = False
        self._step7_logged = False
        self._step8_logged = False
        self._step9_logged = False

    def _mark_complete(self, req_id: int) -> None:
        """Record completion of a contract request and set ``all_data_event`` when done."""
        if req_id in self._completed_requests:
            return
        self._completed_requests.add(req_id)
        if self.expected_contracts and len(self._completed_requests) >= self.expected_contracts:
            self.all_data_event.set()

    def all_data_received(self) -> bool:
        """Return ``True`` when all requested option data has been received."""
        return self.all_data_event.is_set()

    # IB callbacks ------------------------------------------------
    @log_result
    def contractDetails(self, reqId: int, details):  # noqa: N802
        con = details.contract
        logger.debug(
            f"contractDetails callback: reqId={reqId}, conId={con.conId}, type={con.secType}"
        )
        if con.secType == "STK" and self.con_id is None:
            self.trading_hours = getattr(details, "tradingHours", "")
            self._details_event.set()
            self.con_id = con.conId
            self.stock_con_id = con.conId
            self.trading_class = con.tradingClass or self.symbol
            if con.primaryExchange:
                self.primary_exchange = con.primaryExchange
            logger.info(
                f"✅ [stap 4] ConId: {self.con_id}, TradingClass: {self.trading_class}. primaryExchange: {con.primaryExchange}"
            )
            self.details_event.set()
            logger.info("▶️ START stap 5 - reqSecDefOptParams() voor optieparameters")
            self.reqSecDefOptParams(
                self._next_id(), self.symbol, "", "STK", self.con_id
            )
            self.contract_received.set()

        elif reqId in self._pending_details:
            if not self._step8_logged:
                logger.info("▶️ START stap 8 - Callback: contractDetails() voor opties")
                self._step8_logged = True
            logger.debug(
                f"contractDetails received for reqId={reqId} conId={con.conId}"
            )
            self.option_info[reqId] = details
            self.market_data.setdefault(reqId, {})["conId"] = con.conId
            info = self._pending_details.get(reqId)
            if info is not None:
                info.con_id = con.conId
                self.con_ids[(info.expiry, info.strike, info.right)] = con.conId
            # Log contract fields returned by IB before requesting market data
            logger.debug(
                f"Using contract for reqId={reqId}: "
                f"conId={con.conId} symbol={con.symbol} "
                f"expiry={con.lastTradeDateOrContractMonth} strike={con.strike} "
                f"right={con.right} exchange={con.exchange} primaryExchange={con.primaryExchange} "
                f"tradingClass={getattr(con, 'tradingClass', '')} multiplier={getattr(con, 'multiplier', '')}"
            )
            # Request option market data using live or delayed quotes
            data_type = 1 if self.market_open else 3
            logger.debug(f"reqMktData sent for: {contract_repr(con)}")
            self.reqMarketDataType(data_type)
            logger.debug(f"reqMarketDataType({data_type})")
            self.reqMktData(reqId, con, "", True, False, [])
            logger.debug(
                f"✅ [stap 8] reqMktData sent for {con.symbol} {con.lastTradeDateOrContractMonth} {con.strike} {con.right}"
            )
            if reqId in self._pending_details:
                self._pending_details.pop(reqId, None)
                self._detail_semaphore.release()
            logger.debug(
                f"contractDetails ontvangen: {con.symbol} {con.lastTradeDateOrContractMonth} {con.strike} {con.right}"
            )
            self.contract_received.set()

    @log_result
    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId in self._pending_details:
            info = self._pending_details.pop(reqId)
            logger.warning(
                f"Geen contractdetails gevonden voor {info.symbol} {info.expiry} {info.strike} {info.right}"
            )
            self.invalid_contracts.add(reqId)
            self._detail_semaphore.release()
        self._mark_complete(reqId)
        self.contract_received.set()

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

        self.multiplier = multiplier

        # ``expirations`` is returned as a ``set`` by the IB API.  It cannot be
        # sliced directly, so convert it to a sorted list first for logging and
        # further processing.
        exp_list = sorted(expirations)
        logger.debug(f"spot_price={self.spot_price}, expirations={exp_list[:5]}")

        logger.info(
            f"✅ [stap 5] Optieparameters ontvangen: {len(expirations)} expiries, {len(strikes)} strikes"
        )

        self.params_event.set()

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

        strike_range = int(cfg_get("STRIKE_RANGE", 10))
        if not self._step6_logged:
            logger.info(
                f"▶️ START stap 6 - Selectie van relevante expiries + strikes (binnen ±{strike_range} pts spot)"
            )
            self._step6_logged = True

        monthlies: list[str] = []
        weeklies: list[str] = []
        for exp in sorted(exp_list):
            try:
                dt = datetime.strptime(exp, "%Y%m%d")
            except Exception:
                continue
            if _is_third_friday(dt) and len(monthlies) < 3:
                monthlies.append(exp)
            elif _is_weekly(dt) and len(weeklies) < 4:
                weeklies.append(exp)
            if len(monthlies) >= 3 and len(weeklies) >= 4:
                break

        self.monthlies = monthlies
        self.weeklies = weeklies
        if monthlies or weeklies:
            unique = {
                datetime.strptime(e, "%Y%m%d").date()
                for e in monthlies + weeklies
            }
            self.expiries = [d.strftime("%Y%m%d") for d in sorted(unique)]
        else:
            self.expiries = exp_list[:4]
        logger.info(f"✅ [stap 6] Geselecteerde expiries: {', '.join(self.expiries)}")

        center = round(self.spot_price or 0)
        strike_map: dict[float, float] = {}
        for strike in sorted(strikes):
            rounded = round(strike)
            if abs(rounded - center) <= strike_range:
                strike_map.setdefault(rounded, strike)
        self.strikes = sorted(strike_map.keys())
        self._strike_lookup = strike_map
        self.trading_class = tradingClass
        logger.info(
            f"✅ [stap 6] Geselecteerde strikes: {', '.join(str(s) for s in self.strikes)}"
        )
        self.expected_contracts = len(self.expiries) * len(self.strikes) * 2
        if self.expected_contracts == 0:
            self.all_data_event.set()

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
                self._detail_semaphore.release()
            self._pending_details.pop(reqId, None)
            self.invalid_contracts.add(reqId)
            self._mark_complete(reqId)

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
        d_min = float(cfg_get("DELTA_MIN", -1))
        d_max = float(cfg_get("DELTA_MAX", 1))
        evt = rec.get("event")
        if delta is not None and (delta < d_min or delta > d_max):
            self.invalid_contracts.add(reqId)
            if isinstance(evt, threading.Event) and not evt.is_set():
                evt.set()
            self._mark_complete(reqId)
            return
        if isinstance(evt, threading.Event):
            if not evt.is_set():
                evt.set()
                self._mark_complete(reqId)
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
            logger.debug(
                f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}"
            )
            self._logged_data.add(reqId)
            self.market_event.set()
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
        if reqId == self._spot_req_id and tickType in (
            TickTypeEnum.LAST,
            getattr(TickTypeEnum, "DELAYED_LAST", TickTypeEnum.LAST),
        ):
            if price > 0:
                self.spot_event.set()
        if tickType == TickTypeEnum.BID:
            rec["bid"] = price
        elif tickType == TickTypeEnum.ASK:
            rec["ask"] = price
        evt = rec.get("event")
        if isinstance(evt, threading.Event):
            if not evt.is_set():
                evt.set()
                self._mark_complete(reqId)
        if price == -1 and tickType in (TickTypeEnum.BID, TickTypeEnum.ASK):
            self.invalid_contracts.add(reqId)
            self._mark_complete(reqId)
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
            logger.debug(
                f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}"
            )
            self._logged_data.add(reqId)
            self.market_event.set()
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

        # Determine market status
        self._details_event.clear()
        self.reqContractDetails(self._next_id(), stk)
        self._details_event.wait(2)
        self._time_event.clear()
        self.reqCurrentTime()
        self._time_event.wait(2)
        market_open = False
        if self.trading_hours and self.server_time:
            market_open = is_market_open(self.trading_hours, self.server_time)
        self.market_open = market_open

        logger.info("▶️ START stap 3 - Spot price ophalen")

        data_type_success = None
        short_timeout = cfg_get("DATA_TYPE_TIMEOUT", 2)
        data_types = (1, 2, 3) if market_open else (3,)
        for data_type in data_types:
            self.reqMarketDataType(data_type)
            logger.debug(f"reqMarketDataType({data_type})")
            spot_id = self._next_id()
            self.spot_event.clear()
            self.reqMktData(spot_id, stk, "", False, False, [])
            self._spot_req_id = spot_id
            logger.debug(
                f"reqMktData sent: id={spot_id} snapshot=False for stock contract"
            )
            if self.spot_event.wait(short_timeout):
                data_type_success = data_type
                self.cancelMktData(spot_id)
                logger.debug(f"Market data type {data_type} succeeded")
                break
            self.cancelMktData(spot_id)

        if self.spot_price is None:
            timeout = cfg_get("SPOT_TIMEOUT", 20)
            self.spot_event.clear()
            spot_id = self._next_id()
            self.reqMktData(spot_id, stk, "", False, False, [])
            self._spot_req_id = spot_id
            self.spot_event.wait(timeout)
            self.cancelMktData(spot_id)
        if (self.spot_price is None or self.spot_price <= 0):
            fallback = fetch_volatility_metrics(self.symbol).get("spot_price")
            if fallback is not None:
                try:
                    self.spot_price = float(fallback)
                    logger.info(f"✅ [stap 3] Spotprijs fallback: {self.spot_price}")
                except (TypeError, ValueError):
                    logger.warning("Fallback spot price could not be parsed")

        if self.spot_price is None:
            logger.error("❌ FAIL stap 3: Spot price not available after all retries")

        if self.con_id is None:
            logger.info("▶️ START stap 4 - ContractDetails ophalen voor STK")
            logger.debug(
                f"Requesting contract details for: symbol={stk.symbol}, expiry={stk.lastTradeDateOrContractMonth}, strike={floatMaxString(stk.strike)}, right={stk.right}"
            )
            self.details_event.clear()
            self.reqContractDetails(self._next_id(), stk)
            logger.debug(f"reqContractDetails sent for: {contract_repr(stk)}")
            if not self.details_event.wait(10):
                logger.error("❌ FAIL stap 4: Timeout waiting for contract details")
                return

        if not self.params_event.wait(10):
            logger.error("❌ FAIL stap 5: geen optieparameters")
            return

        # Wait until all option parameters have been received before
        # requesting option market data
        if not self.option_params_complete.wait(timeout=20):
            logger.error("❌ FAIL stap 5: Timeout waiting for option parameters")
            return

        self._request_option_data()

    def _request_contract_details(self, contract: Contract, req_id: int) -> bool:
        """Request contract details with timeout/retries.

        Returns ``True`` when details were received within the configured
        timeout, otherwise ``False``. The number of retry attempts is
        controlled via the ``CONTRACT_DETAILS_RETRIES`` config option.
        """

        timeout = cfg_get("CONTRACT_DETAILS_TIMEOUT", 2)
        retries = int(cfg_get("CONTRACT_DETAILS_RETRIES", 0))

        for attempt in range(retries + 1):
            self.contract_received.clear()
            self.reqContractDetails(req_id, contract)
            prefix = "✅ [stap 7]" if attempt == 0 else "🔄 retry"
            logger.debug(
                f"{prefix} reqId {req_id} contract {contract.symbol} "
                f"expiry={contract.lastTradeDateOrContractMonth} "
                f"strike={contract.strike} right={contract.right} "
                f"currency={getattr(contract, 'currency', '')} "
                f"multiplier={getattr(contract, 'multiplier', '')} "
                f"exchange={contract.exchange} "
                f"tradingClass={getattr(contract, 'tradingClass', '')} "
                f"primaryExchange={contract.primaryExchange} "
                f"conId={getattr(contract, 'conId', None)} sent"
            )
            logger.debug(
                f"reqContractDetails attempt {attempt + 1} for: {contract_repr(contract)}"
            )

            if self.contract_received.wait(timeout) and req_id in self.option_info:
                return True

            logger.warning(
                f"❌ contractDetails MISSING voor reqId {req_id} na {timeout}s"
                f" (attempt {attempt + 1})"
            )

        return False

    @log_result
    def _request_option_data(self) -> None:
        if not self.expiries or not self.strikes or self.trading_class is None:
            logger.debug(
                f"Request option data skipped: expiries={self.expiries} "
                f"strikes={self.strikes} trading_class={self.trading_class}"
            )
            return
        self.all_data_event.clear()
        self._completed_requests.clear()
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
                        primary_exchange=None,
                        multiplier=self.multiplier,
                        con_id=self.con_ids.get((expiry, strike, right)),
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
                        "event": threading.Event(),
                    }
                    self._pending_details[req_id] = info
                    self._detail_semaphore.acquire()
                    time.sleep(0.01)
                    if not self._request_contract_details(c, req_id):
                        logger.warning(
                            f"⚠️ Geen optiecontractdetails voor reqId {req_id}; marktdata overgeslagen"
                        )
                        self._pending_details.pop(req_id, None)
                        self._detail_semaphore.release()
                        self.invalid_contracts.add(req_id)
                        self._mark_complete(req_id)

        logger.debug(
            f"Aantal contractdetails aangevraagd: {len(self._pending_details)}"
        )


@log_result
def start_app(app: MarketClient, *, client_id: int | None = None) -> None:
    """Connect to TWS/IB Gateway and start ``app`` in a background thread."""

    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    if client_id is None:
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
        if isinstance(app, OptionChainClient):
            event = getattr(app, "all_data_event", app.market_event)
        else:
            event = getattr(app, "market_event", app.data_event)

        event.wait(remaining)

        if isinstance(app, OptionChainClient):
            if getattr(app, "all_data_event", event).is_set() and app.spot_price is not None:
                logger.debug(f"Market data ontvangen binnen {time.time() - start:.2f}s")
                return True
        else:
            if app.spot_price is not None and event.is_set():
                logger.debug(f"Market data ontvangen binnen {time.time() - start:.2f}s")
                return True

            if any("bid" in rec or "ask" in rec for rec in app.market_data.values()):
                logger.debug(f"Bid/ask ontvangen binnen {time.time() - start:.2f}s")
                return True

        event.clear()

    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


@log_result
def compute_iv_term_structure(app: OptionChainClient, *, strike_window: int | None = None) -> dict[str, float]:
    """Return front-month term structure metrics based on retrieved IVs.

    Parameters
    ----------
    app:
        Running :class:`OptionChainClient` with populated ``market_data``.
    strike_window:
        Absolute distance from the spot price used to select strikes. Defaults
        to ``5`` when not provided.
    """

    if app.spot_price is None:
        return {}

    if strike_window is None:
        strike_window = int(cfg_get("TERM_STRIKE_WINDOW", 5))

    grouped: Dict[str, list[float]] = {}
    for req_id, rec in app.market_data.items():
        if req_id in app.invalid_contracts:
            continue
        iv = rec.get("iv")
        strike = rec.get("strike")
        expiry = rec.get("expiry")
        if iv is None or strike is None or expiry is None:
            continue
        if abs(float(strike) - float(app.spot_price)) <= strike_window:
            grouped.setdefault(str(expiry), []).append(float(iv))

    avgs: list[tuple[str, float]] = []
    for expiry, ivs in grouped.items():
        if ivs:
            avgs.append((expiry, sum(ivs) / len(ivs)))

    avgs.sort(key=lambda x: x[0])
    result: Dict[str, float] = {}
    if len(avgs) >= 2:
        result["term_m1_m2"] = round((avgs[0][1] - avgs[1][1]) * 100, 2)
    if len(avgs) >= 3:
        result["term_m1_m3"] = round((avgs[0][1] - avgs[2][1]) * 100, 2)
    return result


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
        if isinstance(app, OptionChainClient):
            term = compute_iv_term_structure(app)
            if metrics.get("term_m1_m2") is None and term.get("term_m1_m2") is not None:
                metrics["term_m1_m2"] = term["term_m1_m2"]
            if metrics.get("term_m1_m3") is None and term.get("term_m1_m3") is not None:
                metrics["term_m1_m3"] = term["term_m1_m3"]

    if owns_app:
        app.disconnect()

    logger.debug(f"Fetched metrics for {symbol}: {metrics}")
    return metrics


__all__ = [
    "MarketClient",
    "OptionChainClient",
    "start_app",
    "await_market_data",
    "compute_iv_term_structure",
    "fetch_market_metrics",
]
