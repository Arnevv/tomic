from __future__ import annotations

"""Market data clients for retrieving spot prices and option chains.

``OptionChainClient.contractDetails`` stores the underlying's
``trading_class`` and ``primary_exchange`` when it receives details for the
stock contract.  ``OptionContract.to_ib`` then uses these values when building
option contracts so that requests match the underlying's market data.
"""

import asyncio
import threading
import time
import math
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo
from typing import Any, Dict

from ibapi.ticktype import TickTypeEnum

try:  # pragma: no cover - optional dependency during tests
    from ibapi.utils import floatMaxString
except Exception:  # pragma: no cover - tests provide stub

    def floatMaxString(val: float) -> str:  # type: ignore[misc]
        return str(val)


from tomic.api.base_client import BaseIBApp
from tomic.cli.daily_vol_scraper import fetch_volatility_metrics
from tomic.config import get as cfg_get
from tomic.logutils import log_result, logger
from tomic.models import OptionContract
from tomic.utils import _is_third_friday, _is_weekly, today
from .historical_iv import fetch_historical_option_data

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


def is_market_open(trading_hours: str, now: datetime, tz: tzinfo | None = None) -> bool:
    """Return ``True`` if ``now`` falls within ``trading_hours``.

    ``trading_hours`` should contain **regular** trading sessions only. If a
    string with extended hours is provided, ensure it has been filtered to
    regular hours first.
    """

    tz = tz or now.tzinfo
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
            start_dt = datetime.strptime(day + start_str, "%Y%m%d%H%M").replace(tzinfo=tz)
            end_dt = datetime.strptime(day + end_str, "%Y%m%d%H%M").replace(tzinfo=tz)
            # handle sessions that cross midnight
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            if start_dt <= now <= end_dt:
                return True
        return False
    return False


def market_hours_today(
    trading_hours: str, now: datetime, tz: tzinfo | None = None
) -> tuple[str, str] | None:
    """Return the market open and close time (HH:MM) for ``now``.

    ``trading_hours`` should represent regular trading hours. The function
    returns ``None`` if the market is closed or no session matches ``now``'s
    date.
    """

    tz = tz or now.tzinfo
    day = now.strftime("%Y%m%d")
    for part in trading_hours.split(";"):
        if ":" not in part:
            continue
        date_part, hours_part = part.split(":", 1)
        if date_part != day:
            continue
        if hours_part == "CLOSED":
            return None
        session = hours_part.split(",")[0]
        try:
            start_str, end_str = session.split("-")
        except ValueError:
            return None
        start_str = start_str.split(":")[-1][:4]
        end_str = end_str.split(":")[0][:4]
        start_dt = datetime.strptime(day + start_str, "%Y%m%d%H%M").replace(tzinfo=tz)
        end_dt = datetime.strptime(day + end_str, "%Y%m%d%H%M").replace(tzinfo=tz)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        return start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")
    return None


# Descriptions for Interactive Brokers market data types
DATA_TYPE_DESCRIPTIONS: dict[int, str] = {
    1: "realtime",
    2: "frozen",
    3: "delayed",
    4: "delayed frozen",
}


class MarketClient(BaseIBApp):
    """Minimal IB client used for market data exports.

    The client maintains an internal ``threading.Lock`` for coordinating IB
    requests and exposes ``data_lock`` (a ``threading.RLock``) to guard shared
    market data. When a single instance is shared between threads or
    asynchronous tasks, wrap calls that modify or read these structures with the
    appropriate lock to avoid race conditions.
    """

    WARNING_ERROR_CODES: set[int] = getattr(BaseIBApp, "WARNING_ERROR_CODES", set()) | {
        2104,
        2106,
        2158,
    }

    def __init__(self, symbol: str, primary_exchange: str | None = None) -> None:
        super().__init__()
        self.symbol = symbol.upper()
        self.underlying_exchange = cfg_get("UNDERLYING_EXCHANGE", "SMART")
        self.primary_exchange = (
            primary_exchange
            or cfg_get("UNDERLYING_PRIMARY_EXCHANGE", "ARCA")
        )
        self.options_exchange = cfg_get("OPTIONS_EXCHANGE", "SMART")
        self.options_primary_exchange = cfg_get(
            "OPTIONS_PRIMARY_EXCHANGE",
            "ARCA",
        )
        self.stock_con_id: int | None = None
        self.market_data: Dict[int, Dict[str, Any]] = {}
        self.invalid_contracts: set[int] = set()
        self.spot_price: float | None = None
        self.expiries: list[str] = []
        self.connected = threading.Event()
        self.data_event = threading.Event()
        self._req_id = 50
        self._lock = threading.Lock()
        # Protect access to market data from callback threads
        self.data_lock = threading.RLock()
        self._spot_req_id: int | None = None
        self._spot_req_ids: set[int] = set()
        self.trading_hours: str | None = None
        self.server_time: datetime | None = None
        self.market_tz: tzinfo = timezone.utc
        self._time_event = threading.Event()
        self._details_event = threading.Event()
        self.market_open: bool = False
        self.data_type_success: int | None = None
        self._logged_spot = False

    # Helpers -----------------------------------------------------
    @log_result
    def _stock_contract(self) -> Contract:
        c = Contract()
        c.symbol = self.symbol
        c.secType = "STK"
        c.exchange = self.underlying_exchange
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
        with self._lock:
            self._req_id += 1
            return self._req_id

    @log_result
    def _init_market(self) -> None:
        """Determine market status and retrieve a stock quote."""
        contract = self._stock_contract()

        self._details_event.clear()
        self.reqContractDetails(self._next_id(), contract)
        self._details_event.wait(5)
        self._time_event.clear()
        self.reqCurrentTime()
        self._time_event.wait(5)

        if self.trading_hours is None or self.server_time is None:
            logger.error("❌ FAIL stap 2: Market status kon niet bepaald worden")
            return

        market_time = self.server_time.astimezone(self.market_tz)
        self.market_open = is_market_open(
            self.trading_hours, market_time, tz=self.market_tz
        )

        if self.trading_hours and self.server_time:
            hours = market_hours_today(
                self.trading_hours, market_time, tz=self.market_tz
            )
            now_str = market_time.strftime("%H:%M")
            if hours is not None:
                start, end = hours
                status = "open" if self.market_open else "dicht"
                logger.info(
                    f"✅ [stap 2] De markt ({self.symbol}) is open tussen {start} en {end}, "
                    f"het is nu {now_str} dus de markt is {status}"
                )
            else:
                logger.info(
                    f"✅ [stap 2] De markt ({self.symbol}) is vandaag gesloten, "
                    f"het is nu {now_str}"
                )

        logger.info("▶️ START stap 3 - Spot price ophalen")
        use_snapshot = not self.market_open
        # Store the market data type that succeeded when requesting a stock
        # quote so it can be reused for option requests.
        self.data_type_success = 1 if self.market_open else 2
        self.reqMarketDataType(self.data_type_success)
        logger.info(
            f"reqMarketDataType({self.data_type_success}) - {DATA_TYPE_DESCRIPTIONS.get(self.data_type_success, '')}"
        )

        timeout = cfg_get("SPOT_TIMEOUT", 10)
        self.data_event.clear()
        req_id = self._next_id()
        if use_snapshot:
            generic_ticks = ""
        else:
            tick_cfg = cfg_get("MKT_GENERIC_TICKS", "")
            if tick_cfg:
                generic_ticks = tick_cfg
            else:
                generic_ticks = "100,101,106"
        self.reqMktData(req_id, contract, generic_ticks, use_snapshot, False, [])
        self._spot_req_id = req_id
        self._spot_req_ids.add(req_id)
        logger.debug(f"Requesting stock quote for symbol={contract.symbol} id={req_id}")

        start = time.time()
        received_any = False
        while time.time() - start < timeout and self.spot_price is None:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break
            received = self.data_event.wait(remaining)
            if received:
                received_any = True
                if self.spot_price is None:
                    self.data_event.clear()

        if not received_any and self.spot_price is None:
            logger.warning(
                "No tick received within %ss; waiting short grace period",
                timeout,
            )
            self.data_event.wait(1.5)

        self.cancelMktData(req_id)
        self.invalid_contracts.add(req_id)

        if self.spot_price is None:
            fallback = fetch_volatility_metrics(self.symbol).get("spot_price")
            if fallback is not None:
                try:
                    self.spot_price = float(fallback)
                    logger.info(f"✅ [stap 3] Spotprijs fallback: {self.spot_price}")
                    self._logged_spot = True
                    if hasattr(self, "spot_event"):
                        self.spot_event.set()
                except (TypeError, ValueError):
                    logger.warning("Fallback spot price could not be parsed")

        if self.spot_price is None:
            logger.error("❌ FAIL stap 3: Spot price not available after all retries")

    @log_result
    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        """Request a basic stock quote for ``self.symbol``."""
        self._init_market()

    async def start_requests_async(
        self,
    ) -> None:  # pragma: no cover - runtime behaviour
        """Asynchronous wrapper around :meth:`start_requests`."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.start_requests)

    # IB callbacks -----------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        """Called once the connection is established."""
        logger.info(f"✅ [stap 2] Verbonden. OrderId: {orderId}")
        self.connected.set()
        try:
            self.start_requests()
            if self.trading_hours and self.server_time:
                market_time = self.server_time.astimezone(self.market_tz)
                hours = market_hours_today(
                    self.trading_hours, market_time, tz=self.market_tz
                )
                now_str = market_time.strftime("%H:%M")
                if hours is not None:
                    start, end = hours
                    status = "open" if self.market_open else "dicht"
                    logger.info(
                        f"✅ [stap 2] De markt ({self.symbol}) is open tussen {start} en {end}, "
                        f"het is nu {now_str} dus de markt is {status}"
                    )
                else:
                    logger.info(
                        f"✅ [stap 2] De markt ({self.symbol}) is vandaag gesloten, "
                        f"het is nu {now_str}"
                    )
        except Exception as exc:  # pragma: no cover - runtime behaviour
            logger.error(f"start_requests failed: {exc}")

    def tickPrice(
        self, reqId: int, tickType: int, price: float, attrib
    ) -> None:  # noqa: N802 - IB API callback
        with self.data_lock:
            if reqId == self._spot_req_id and tickType in (
                TickTypeEnum.LAST,
                TickTypeEnum.DELAYED_LAST,
            ):
                self.spot_price = price
                if price > 0 and not self._logged_spot:
                    logger.info(f"✅ [stap 3] Spotprijs: {price}")
                    self._logged_spot = True
            elif (
                reqId == self._spot_req_id
                and tickType == getattr(TickTypeEnum, "CLOSE", 9)
                and self.spot_price is None
            ):
                self.spot_price = price
                if price > 0 and not self._logged_spot:
                    logger.info(f"✅ [stap 3] Spotprijs (CLOSE): {price}")
                    self._logged_spot = True
            if price != -1 and tickType in (
                TickTypeEnum.LAST,
                TickTypeEnum.BID,
                TickTypeEnum.ASK,
                getattr(TickTypeEnum, "DELAYED_LAST", TickTypeEnum.LAST),
                getattr(TickTypeEnum, "DELAYED_BID", TickTypeEnum.BID),
                getattr(TickTypeEnum, "DELAYED_ASK", TickTypeEnum.ASK),
                getattr(TickTypeEnum, "CLOSE", 9),
            ):
                self.data_event.set()
            rec = self.market_data.setdefault(reqId, {})
            rec.setdefault("prices", {})[tickType] = price
            if tickType == getattr(TickTypeEnum, "CLOSE", 9):
                rec["close"] = price

    def tickSize(
        self, reqId: int, tickType: int, size: int
    ) -> None:  # noqa: N802 - IB API callback
        with self.data_lock:
            rec = self.market_data.setdefault(reqId, {})
            rec.setdefault("sizes", {})[tickType] = size

    def currentTime(self, time: int) -> None:  # noqa: N802
        self.server_time = datetime.fromtimestamp(time, timezone.utc)
        self._time_event.set()

    def contractDetails(self, reqId: int, details) -> None:  # noqa: N802
        self.trading_hours = getattr(
            details, "liquidHours", getattr(details, "tradingHours", "")
        )
        tz_id = getattr(details, "timeZoneId", None)
        if tz_id:
            try:
                self.market_tz = ZoneInfo(tz_id)
            except Exception:
                self.market_tz = timezone.utc
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
        self.data_lock = threading.RLock()
        self.con_id: int | None = None
        self.trading_class: str | None = None
        self.strikes: list[float] = []
        self._strike_lookup: dict[float, float] = {}
        self._exp_strike_lookup: dict[str, dict[float, float]] = {}
        self._expiry_min_tick: dict[str, float] = {}
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
        self.iv_event = threading.Event()
        self.expected_contracts = 0
        self._completed_requests: set[int] = set()
        self._logged_data: set[int] = set()
        self._step6_logged = False
        self._step7_logged = False
        self._step8_logged = False
        self._step9_logged = False
        # Timers for delayed invalidation of option market data requests
        self._invalid_timers: dict[int, threading.Timer] = {}
        self._max_data_timer: threading.Timer | None = None
        self._use_snapshot: bool = False
        self._retry_rounds = int(cfg_get("OPTION_DATA_RETRIES", 0))
        self._request_retries: dict[int, int] = {}
        self.use_hist_iv: bool = False

    def _log_step9_start(self) -> None:
        """Log the start of step 9 with a summary of received contract details."""
        logger.info("▶️ START stap 9 - Ontvangen van market data (bid/ask/Greeks)")
        logger.info(
            f"✅ [stap 9] Er zijn {len(self.option_info)} volledige optiecontractdetails ontvangen van de in totaal {self.expected_contracts} mogelijke combinaties"
        )
        self._step9_logged = True

    def _mark_complete(self, req_id: int) -> None:
        """Record completion of a contract request and set ``all_data_event`` when done."""
        with self.data_lock:
            if req_id in self._completed_requests:
                return
            # Cancel streaming market data since generic ticks cannot be
            # requested as snapshots.
            try:
                self.cancelMktData(req_id)
            except Exception:
                pass
            self._request_retries.pop(req_id, None)
            self._completed_requests.add(req_id)
            if (
                self.expected_contracts
                and len(self._completed_requests) >= self.expected_contracts
            ):
                self.all_data_event.set()
                self._stop_max_data_timer()

    def _invalidate_request(self, req_id: int) -> None:
        """Mark request ``req_id`` as invalid and cancel streaming data."""
        with self.data_lock:
            self._invalid_timers.pop(req_id, None)
            self.invalid_contracts.add(req_id)
            rec = self.market_data.get(req_id, {})
            rec["status"] = "timeout"
            evt = rec.get("event")
        if isinstance(evt, threading.Event) and not evt.is_set():
            evt.set()
        self._mark_complete(req_id)

    def _retry_or_invalidate(self, req_id: int) -> None:
        """Retry a request when retries remain; otherwise invalidate it."""
        retries = self._request_retries.get(req_id, 0)
        if retries > 0:
            self._request_retries[req_id] = retries - 1
            self.retry_incomplete_requests([req_id], wait=False)
        else:
            self._invalidate_request(req_id)

    def _cancel_invalid_timer(self, req_id: int) -> None:
        with self.data_lock:
            timer = self._invalid_timers.pop(req_id, None)
            if timer is not None:
                timer.cancel()
            self._request_retries.pop(req_id, None)

    def _schedule_invalid_timer(self, req_id: int) -> None:
        timeout = cfg_get("BID_ASK_TIMEOUT", 5)
        if timeout <= 0:
            self._retry_or_invalidate(req_id)
            return
        timer = threading.Timer(timeout, self._retry_or_invalidate, args=[req_id])
        timer.daemon = True
        with self.data_lock:
            if req_id in self._invalid_timers:
                return
            self._invalid_timers[req_id] = timer
            self._request_retries.setdefault(req_id, self._retry_rounds)
            timer.start()

    def incomplete_requests(self) -> list[int]:
        """Return request IDs missing essential market data."""
        if self.use_hist_iv:
            required = ["iv", "close"]
        else:
            required = ["bid", "ask", "iv", "delta", "gamma", "vega", "theta"]
        with self.data_lock:
            return [
                rid
                for rid, rec in self.market_data.items()
                if rid not in self.invalid_contracts
                and any(rec.get(k) is None for k in required)
            ]

    async def retry_incomplete_requests_async(
        self, ids: list[int] | None = None, *, wait: bool = True
    ) -> bool:
        """Re-request market data for incomplete option contracts."""
        wait_time = int(cfg_get("OPTION_RETRY_WAIT", 1)) if wait else 0
        if ids is None:
            ids = self.incomplete_requests()
        if not ids:
            return False
        logger.info(f"🔄 Retry for {len(ids)} incomplete contracts")

        data_type = (
            self.data_type_success
            if self.data_type_success is not None
            else 1 if self.market_open else 2
        )
        self.reqMarketDataType(data_type)
        sem = asyncio.Semaphore(int(cfg_get("MAX_CONCURRENT_REQUESTS", 5)))

        async def send_request(rid: int) -> None:
            details = self.option_info.get(rid)
            if details is None:
                return
            con = details.contract
            logger.info(
                f"🔄 retry reqId {rid} contract {contract_repr(con)}"
            )
            evt = threading.Event()
            with self.data_lock:
                self.market_data[rid]["event"] = evt
                self.invalid_contracts.discard(rid)
                self._completed_requests.discard(rid)
                try:
                    self.cancelMktData(rid)
                except Exception:
                    pass
            use_snapshot = getattr(self, "_use_snapshot", not self.market_open)
            include_greeks = (
                not cfg_get("INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN", False)
                or self.market_open
            )
            if use_snapshot:
                generic = ""
            else:
                ticks = ["100", "101"]
                if include_greeks:
                    ticks.append("106")
                generic = ",".join(ticks)
            async with sem:
                await asyncio.to_thread(
                    self.reqMktData, rid, con, generic, use_snapshot, False, []
                )
            self._schedule_invalid_timer(rid)

        tasks = [asyncio.create_task(send_request(rid)) for rid in ids]
        await asyncio.gather(*tasks)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        self.all_data_event.clear()
        return True

    def retry_incomplete_requests(
        self, ids: list[int] | None = None, *, wait: bool = True
    ) -> bool:
        return asyncio.run(self.retry_incomplete_requests_async(ids, wait=wait))

    def all_data_received(self) -> bool:
        """Return ``True`` when all requested option data has been received."""
        return self.all_data_event.is_set()

    def _start_max_data_timer(self) -> None:
        limit = int(cfg_get("OPTION_MAX_MARKETDATA_TIME", 0))
        if limit <= 0 or self._max_data_timer is not None:
            return

        def timeout() -> None:
            missing = self.incomplete_requests()
            if missing:
                logger.warning(
                    f"⚠️ Hard timeout na {limit}s: {len(missing)} contracten ontbreken"
                )
            self.all_data_event.set()

        timer = threading.Timer(limit, timeout)
        timer.daemon = True
        self._max_data_timer = timer
        timer.start()

    def _stop_max_data_timer(self) -> None:
        timer = self._max_data_timer
        if timer is not None:
            timer.cancel()
            self._max_data_timer = None

    def _merge_historical_data(
        self,
        contracts: dict[int, Contract],
        results: dict[int, dict[str, float | None]],
    ) -> None:
        """Merge IV and close from historical lookup into ``market_data``."""

        with self.data_lock:
            for req_id, data in results.items():
                if req_id not in self.market_data:
                    logger.warning(
                        "⚠️ historical data for unknown reqId %s", req_id
                    )
                    continue

                rec = self.market_data[req_id]
                rec["iv"] = data.get("iv")
                rec["close"] = data.get("close")
                rec["status"] = "fallback"
                evt = rec.get("event")
                if isinstance(evt, threading.Event) and not evt.is_set():
                    evt.set()

    # IB callbacks ------------------------------------------------
    @log_result
    def contractDetails(self, reqId: int, details):  # noqa: N802
        con = details.contract
        logger.debug(
            f"contractDetails callback: reqId={reqId}, conId={con.conId}, type={con.secType}"
        )
        if con.secType == "STK" and self.con_id is None:
            self.trading_hours = getattr(
                details, "liquidHours", getattr(details, "tradingHours", "")
            )
            tz_id = getattr(details, "timeZoneId", None)
            if tz_id:
                try:
                    self.market_tz = ZoneInfo(tz_id)
                except Exception:
                    self.market_tz = timezone.utc
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
            # Wait for the spot price to become available before requesting
            # option parameters. This prevents ``reqSecDefOptParams`` from being
            # triggered multiple times when the price arrives after the
            # contract details callback.
            if self.spot_price is None:
                logger.debug(
                    "Waiting for spot price before requesting option parameters"
                )
                self.spot_event.wait(2)
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
            with self.data_lock:
                self.market_data.setdefault(reqId, {})["conId"] = con.conId
            info = self._pending_details.get(reqId)
            if info is not None:
                info.con_id = con.conId
                self.con_ids[(info.expiry, info.strike, info.right)] = con.conId
                min_tick = getattr(details, "minTick", None)
                if min_tick and info.expiry not in self._expiry_min_tick:
                    self._expiry_min_tick[info.expiry] = float(min_tick)
                    lookup = {}
                    for s in self.strikes:
                        adj = round(round(s / min_tick) * min_tick, 10)
                        lookup[s] = adj
                    self._exp_strike_lookup[info.expiry] = lookup
            # Log contract fields returned by IB before requesting market data
            logger.debug(
                f"Using contract for reqId={reqId}: "
                f"conId={con.conId} symbol={con.symbol} "
                f"expiry={con.lastTradeDateOrContractMonth} strike={con.strike} "
                f"right={con.right} exchange={con.exchange} primaryExchange={con.primaryExchange} "
                f"tradingClass={getattr(con, 'tradingClass', '')} multiplier={getattr(con, 'multiplier', '')}"
            )
            if not self.use_hist_iv:
                # Request option market data using the type that succeeded for the
                # stock quote fallback, defaulting to live when open or frozen when
                # closed.
                if self.data_type_success is not None:
                    data_type = self.data_type_success
                else:
                    data_type = 1 if self.market_open else 2
                logger.debug(f"reqMktData sent for: {contract_repr(con)}")
                logger.debug(
                    f"[reqId={reqId}] marketDataType={data_type} voor optie {con.symbol} "
                    f"{con.lastTradeDateOrContractMonth} {con.strike} {con.right}"
                )
                use_snapshot = getattr(self, "_use_snapshot", not self.market_open)
                include_greeks = (
                    not cfg_get("INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN", False)
                    or self.market_open
                )
                if use_snapshot:
                    generic_ticks = ""
                else:
                    tick_cfg = cfg_get("MKT_GENERIC_TICKS", "")
                    if tick_cfg:
                        generic_ticks = tick_cfg
                    else:
                        ticks = ["100", "101"]
                        if include_greeks:
                            ticks.append("106")
                        generic_ticks = ",".join(ticks)
                self.reqMktData(reqId, con, generic_ticks, use_snapshot, False, [])
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
            with self.data_lock:
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

        min_dte = int(cfg_get("FIRST_EXPIRY_MIN_DTE", 15))
        if min_dte > 0:
            today_date = today()
            filtered = []
            for exp in exp_list:
                try:
                    dt = datetime.strptime(exp, "%Y%m%d").date()
                except Exception:
                    continue
                if (dt - today_date).days >= min_dte:
                    filtered.append(exp)
            if filtered:
                exp_list = filtered

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
        stddev_mult = float(cfg_get("STRIKE_STDDEV_MULTIPLIER", 1.0))
        if not self._step6_logged:
            logger.info(
                f"▶️ START stap 6 - Selectie van relevante expiries + strikes (binnen ±{strike_range} pts spot)"
            )
            self._step6_logged = True

        reg_count = int(cfg_get("AMOUNT_REGULARS", 3))
        week_count = int(cfg_get("AMOUNT_WEEKLIES", 4))
        monthlies: list[str] = []
        weeklies: list[str] = []
        for exp in sorted(exp_list):
            try:
                dt = datetime.strptime(exp, "%Y%m%d")
            except Exception:
                continue
            if _is_third_friday(dt) and len(monthlies) < reg_count:
                monthlies.append(exp)
            elif _is_weekly(dt) and len(weeklies) < week_count:
                weeklies.append(exp)
            if len(monthlies) >= reg_count and len(weeklies) >= week_count:
                break

        self.monthlies = monthlies
        self.weeklies = weeklies
        if monthlies or weeklies:
            unique = {
                datetime.strptime(e, "%Y%m%d").date() for e in monthlies + weeklies
            }
            self.expiries = [d.strftime("%Y%m%d") for d in sorted(unique)]
        else:
            self.expiries = exp_list[: reg_count + week_count]
        logger.info(f"✅ [stap 6] Geselecteerde expiries: {', '.join(self.expiries)}")

        self.trading_class = tradingClass

        center = self.spot_price or 0.0
        atm_expiry = None
        today_date = today()
        for exp in monthlies:
            try:
                dte = (datetime.strptime(exp, "%Y%m%d").date() - today_date).days
            except Exception:
                continue
            if dte > 15:
                atm_expiry = exp
                break

        atm_strike = min(strikes, key=lambda x: abs(x - center)) if strikes else None

        def finalize(allowed: list[float]) -> None:
            self.strikes = allowed
            self._strike_lookup = {s: s for s in allowed}
            self._exp_strike_lookup = {}
            self._expiry_min_tick = {}
            logger.info(
                f"✅ [stap 6] Geselecteerde strikes: {', '.join(str(s) for s in self.strikes)}"
            )
            self.expected_contracts = len(self.expiries) * len(self.strikes) * 2
            logger.info(
                f"✅ [stap 6] Er zijn {len(self.expiries)} expiries en {len(self.strikes)} strikes dus {self.expected_contracts} combinaties"
            )
            if self.expected_contracts == 0:
                self.all_data_event.set()
                self._stop_max_data_timer()
                self._stop_max_data_timer()
            self.iv_event.set()

        def worker() -> None:
            iv = None
            stddev = None
            if atm_expiry and atm_strike is not None:
                logger.info(
                    f"IV bepaling via expiry {atm_expiry} en ATM strike {atm_strike}"
                )
                iv = self._fetch_iv_for_expiry(atm_expiry, atm_strike)
                if iv is not None:
                    dte = (datetime.strptime(atm_expiry, "%Y%m%d").date() - today_date).days
                    stddev = center * iv * math.sqrt(dte / 365) * stddev_mult
                    logger.info(
                        f"IV ontvangen: {iv} -> stddev {stddev:.2f} (multiplier {stddev_mult})"
                    )
            if iv is None or stddev is None:
                logger.debug("IV niet beschikbaar, fallback naar STRIKE_RANGE")
                allowed = [s for s in sorted(strikes) if abs(s - center) <= strike_range]
            else:
                allowed = [s for s in sorted(strikes) if abs(s - center) <= stddev]
            finalize(allowed)

        self.iv_event.clear()
        threading.Thread(target=worker, daemon=True).start()

    def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:  # noqa: N802
        """Mark option parameter retrieval as complete."""
        logger.debug(f"securityDefinitionOptionParameterEnd received for reqId={reqId}")
        self.option_params_complete.set()

    @log_result
    def error(
        self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""
    ):  # noqa: D401
        if errorCode in {200, 300}:
            logger.debug(f"IB error {errorCode}: {errorString}")
            info = self._pending_details.get(reqId)
            if info is not None:
                logger.debug(f"Invalid contract for id {reqId}: {info}")
                self._detail_semaphore.release()
            self._pending_details.pop(reqId, None)
            with self.data_lock:
                self.invalid_contracts.add(reqId)
                rec = self.market_data.get(reqId, {})
                rec["status"] = "invalid"
                evt = rec.get("event")
            if isinstance(evt, threading.Event) and not evt.is_set():
                evt.set()
            self._mark_complete(reqId)
        elif errorCode == 504:
            logger.error(f"IB error {errorCode}: {errorString}")
            # Connection lost - mark remaining requests complete so waiting loops
            # can exit gracefully
            with self.data_lock:
                pending = set(self.market_data).difference(self._completed_requests)
            for rid in pending:
                self._mark_complete(rid)
            self.all_data_event.set()
            self._stop_max_data_timer()
        else:
            super().error(
                reqId, errorTime, errorCode, errorString, advancedOrderRejectJson
            )

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
        with self.data_lock:
            rec = self.market_data.setdefault(reqId, {})
            self._cancel_invalid_timer(reqId)
            self.log.debug(
                f"[tickOptionComputation] reqId={reqId}, tickType={tickType} | "
                f"IV={impliedVol}, Delta={delta}, Gamma={gamma}, Vega={vega}, "
                f"Theta={theta}, OptPrice={optPrice}, UndPrice={undPrice}"
            )
            rec["iv"] = impliedVol
            rec["delta"] = delta
            rec["gamma"] = gamma
            rec["vega"] = vega
            rec["theta"] = theta
            flags = rec.setdefault("flags", set())
            flags.add("option")
            d_min = float(cfg_get("DELTA_MIN", -1))
            d_max = float(cfg_get("DELTA_MAX", 1))
            evt = rec.get("event")
            if delta is not None and (delta < d_min or delta > d_max):
                self.invalid_contracts.add(reqId)
                if isinstance(evt, threading.Event) and not evt.is_set():
                    evt.set()
                self._mark_complete(reqId)
                return
            if isinstance(evt, threading.Event) and not evt.is_set():
                if {"option"} <= flags and (
                    "close" in flags
                    or {"bid", "ask"} <= flags
                    or (rec.get("iv") is not None and rec.get("delta") is not None)
                ):
                    evt.set()
                    self._mark_complete(reqId)
        if reqId != self._spot_req_id and reqId not in self._logged_data:
            if not self._step9_logged:
                self._log_step9_start()
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
            logger.debug(f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}")
            self._logged_data.add(reqId)
            self.market_event.set()
        if getattr(self, "data_type_success", None) == 2:
            fields = {
                "impliedVol": impliedVol,
                "delta": delta,
                "gamma": gamma,
                "vega": vega,
                "theta": theta,
            }
            missing = [k for k, v in fields.items() if v is None]
            if missing:
                self.log.debug(
                    f"[snapshot] reqId={reqId} missing Greeks: {', '.join(missing)}"
                )
            else:
                self.log.debug(f"[snapshot] reqId={reqId} all IV and Greeks provided")
        self.log.debug(
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
        with self.data_lock:
            spot_was_none = self.spot_price is None
            super().tickPrice(reqId, tickType, price, attrib)
            rec = self.market_data.setdefault(reqId, {})
            if reqId == self._spot_req_id and tickType in (
                TickTypeEnum.LAST,
                getattr(TickTypeEnum, "DELAYED_LAST", TickTypeEnum.LAST),
            ):
                if price > 0:
                    self.spot_event.set()
            flags = rec.setdefault("flags", set())
            if tickType == TickTypeEnum.BID:
                rec["bid"] = price
                flags.add("bid")
                if price == -1:
                    self._schedule_invalid_timer(reqId)
                    if self._use_snapshot:
                        logger.warning(
                            f"⚠️ Snapshot levert geen geldige BID/ASK voor reqId {reqId}"
                        )
                else:
                    self._cancel_invalid_timer(reqId)
            elif tickType == TickTypeEnum.ASK:
                rec["ask"] = price
                flags.add("ask")
                if price == -1:
                    self._schedule_invalid_timer(reqId)
                    if self._use_snapshot:
                        logger.warning(
                            f"⚠️ Snapshot levert geen geldige BID/ASK voor reqId {reqId}"
                        )
                else:
                    self._cancel_invalid_timer(reqId)
            elif tickType == TickTypeEnum.CLOSE:
                rec["close"] = price
                flags.add("close")
                if price != -1:
                    self._cancel_invalid_timer(reqId)
                    if (
                        reqId == self._spot_req_id
                        and spot_was_none
                        and self.spot_price is not None
                        and price > 0
                    ):
                        self.spot_event.set()
            elif tickType in (86, 87):
                rec["open_interest"] = int(price)
            evt = rec.get("event")
            if isinstance(evt, threading.Event) and not evt.is_set():
                if {"option"} <= flags and ({"bid", "ask"} <= flags or "close" in flags):
                    evt.set()
                    self._mark_complete(reqId)
        if (
            price != -1
            and tickType in (TickTypeEnum.BID, TickTypeEnum.ASK)
            and reqId not in self._logged_data
            and reqId != self._spot_req_id
        ):
            if not self._step9_logged:
                self._log_step9_start()
            details = []
            if "bid" in rec:
                details.append(f"bid={rec['bid']}")
            if "ask" in rec:
                details.append(f"ask={rec['ask']}")
            info = ", ".join(details)
            logger.debug(f"✅ [stap 9] Marktdata ontvangen voor reqId {reqId}: {info}")
            self._logged_data.add(reqId)
            self.market_event.set()
        logger.debug(
            f"tickPrice reqId={reqId} type={TickTypeEnum.toStr(tickType)} price={price}"
        )

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        with self.data_lock:
            super().tickSize(reqId, tickType, size)

    @log_result
    def tickGeneric(
        self, reqId: int, tickType: int, value: float
    ) -> None:  # noqa: N802
        with self.data_lock:
            rec = self.market_data.setdefault(reqId, {})
            if tickType == 100:
                rec["volume"] = int(value)
            elif tickType == 101:
                rec["open_interest"] = int(value)
        logger.debug(f"tickGeneric reqId={reqId} type={tickType} value={value}")

    # Request orchestration --------------------------------------
    def start_requests(self) -> None:  # pragma: no cover - runtime behaviour
        threading.Thread(target=self._init_requests, daemon=True).start()

    @log_result
    def _init_requests(self) -> None:
        self._init_market()

        stk = self._stock_contract()
        logger.debug(f"Requesting stock quote with contract: {stk}")

        if self.trading_hours and self.server_time:
            market_time = self.server_time.astimezone(self.market_tz)
            hours = market_hours_today(
                self.trading_hours, market_time, tz=self.market_tz
            )
            now_str = market_time.strftime("%H:%M")
            if hours is not None:
                start, end = hours
                status = "open" if self.market_open else "dicht"
                logger.debug(
                    f"De markt ({self.symbol}) is open tussen {start} en {end}, "
                    f"het is nu {now_str} dus de markt is {status}"
                )
            else:
                logger.debug(
                    f"De markt ({self.symbol}) is vandaag gesloten, het is nu {now_str}"
                )

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
        if not self.option_params_complete.wait(timeout=cfg_get("OPTION_PARAMS_TIMEOUT", 20)):
            logger.error("❌ FAIL stap 5: Timeout waiting for option parameters")
            return

        if not self.iv_event.wait(10):
            logger.error("❌ FAIL stap 6: Timeout waiting for IV calculation")
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

            logger.info(
                f"❌ contractDetails MISSING voor reqId {req_id} na {timeout}s"
                f" (attempt {attempt + 1})"
            )

        return False

    def _fetch_iv_for_expiry(self, expiry: str, strike: float) -> float | None:
        """Return implied volatility for the specified ATM option.

        This helper builds a temporary option contract and waits briefly for
        ``tickOptionComputation`` data. When no data is received or the client
        is not connected, ``None`` is returned.
        """

        if not getattr(self, "isConnected", lambda: False)():
            return None

        info = OptionContract(
            self.symbol,
            expiry,
            strike,
            "C",
            exchange=self.options_exchange,
            trading_class=self.trading_class or self.symbol,
            primary_exchange=self.options_primary_exchange,
            multiplier=self.multiplier,
        )

        req_id = self._next_id()
        self._pending_details[req_id] = info
        with self.data_lock:
            self.market_data[req_id] = {}
        self._detail_semaphore.acquire()
        if not self._request_contract_details(info.to_ib(), req_id):
            self._pending_details.pop(req_id, None)
            with self.data_lock:
                self.market_data.pop(req_id, None)
            self._detail_semaphore.release()
            return None

        start = time.time()
        iv = None
        timeout = 5
        while time.time() - start < timeout:
            with self.data_lock:
                iv = self.market_data.get(req_id, {}).get("iv")
            if iv is not None:
                break
            time.sleep(0.1)

        try:
            self.cancelMktData(req_id)
        except Exception:
            pass
        with self.data_lock:
            self.market_data.pop(req_id, None)
        self.option_info.pop(req_id, None)
        self.invalid_contracts.discard(req_id)
        self._completed_requests.discard(req_id)
        return iv

    async def _request_option_data_async(self) -> None:
        if not self.expiries or not self.strikes or self.trading_class is None:
            logger.debug(
                f"Request option data skipped: expiries={self.expiries} "
                f"strikes={self.strikes} trading_class={self.trading_class}"
            )
            return
        self.all_data_event.clear()
        with self.data_lock:
            self._completed_requests.clear()
        self._use_snapshot = not self.market_open
        self.use_hist_iv = (
            not self.market_open
            and cfg_get("USE_HISTORICAL_IV_WHEN_CLOSED", False)
        )
        logger.debug(f"Spot price at _request_option_data: {self.spot_price}")
        logger.debug(
            f"Requesting option data for expiries={self.expiries} strikes={self.strikes}"
        )
        if not self._step7_logged:
            logger.info(
                "▶️ START stap 7 - Per combinatie optiecontract bouwen en reqContractDetails()"
            )
            self._step7_logged = True
        async_sem = asyncio.Semaphore(int(cfg_get("MAX_CONCURRENT_REQUESTS", 5)))
        contract_map: dict[int, Contract] = {}

        async def handle_request(expiry: str, strike: float, right: str) -> None:
            actual = self._exp_strike_lookup.get(expiry, {}).get(
                strike, self._strike_lookup.get(strike, strike)
            )
            info = OptionContract(
                self.symbol,
                expiry,
                actual,
                right,
                exchange=self.options_exchange,
                trading_class=self.trading_class,
                primary_exchange=self.options_primary_exchange,
                multiplier=self.multiplier,
                con_id=self.con_ids.get((expiry, strike, right)),
            )
            c = info.to_ib()
            req_id = self._next_id()
            logger.debug(
                f"reqId for {c.symbol} {c.lastTradeDateOrContractMonth}{c.strike} {c.right} is {req_id}"
            )
            with self.data_lock:
                self.market_data[req_id] = {
                    "expiry": expiry,
                    "strike": strike,
                    "right": right,
                    "event": threading.Event(),
                    "status": "ok",
                }
                self._pending_details[req_id] = info
            contract_map[req_id] = c
            await async_sem.acquire()
            self._detail_semaphore.acquire()
            await asyncio.sleep(0.01)
            ok = await asyncio.to_thread(self._request_contract_details, c, req_id)
            if not ok:
                logger.warning(
                    f"⚠️ Geen optiecontractdetails voor reqId {req_id}; marktdata overgeslagen"
                )
                self._pending_details.pop(req_id, None)
                self._detail_semaphore.release()
                with self.data_lock:
                    self.invalid_contracts.add(req_id)
                    rec = self.market_data.get(req_id, {})
                    rec["status"] = "invalid"
                    evt = rec.get("event")
                if isinstance(evt, threading.Event) and not evt.is_set():
                    evt.set()
                self._mark_complete(req_id)
            async_sem.release()

        tasks = []
        for e in self.expiries:
            strike_map = self._exp_strike_lookup.get(e)
            for s in self.strikes:
                if strike_map is not None and s not in strike_map:
                    logger.debug(
                        f"Skipping strike {s} for expiry {e} (not in exp strike lookup)"
                    )
                    continue
                for r in ("C", "P"):
                    tasks.append(asyncio.create_task(handle_request(e, s, r)))

        await asyncio.gather(*tasks)
        if self.use_hist_iv:
            contracts = {
                rid: self.option_info[rid].contract
                for rid in contract_map
                if rid in self.option_info
            }
            bulk_results = await asyncio.to_thread(
                fetch_historical_option_data, contracts, app=self
            )
            self._merge_historical_data(contracts, bulk_results)
            for rid in contracts:
                self._mark_complete(rid)
            return

        logger.debug(
            f"Aantal contractdetails aangevraagd: {len(self._pending_details)}"
        )
        self._start_max_data_timer()

    @log_result
    def _request_option_data(self) -> None:
        asyncio.run(self._request_option_data_async())


class TermStructureClient(OptionChainClient):
    """Lightweight ``OptionChainClient`` for quick term structure snapshots."""

    def __init__(
        self, symbol: str, *, expiries: int = 3, strike_window: int = 1
    ) -> None:
        super().__init__(symbol)
        self._ts_expiries = expiries
        self._ts_window = strike_window

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
        super().securityDefinitionOptionParameter(
            reqId,
            exchange,
            underlyingConId,
            tradingClass,
            multiplier,
            expirations,
            strikes,
        )
        if self.expiries:
            self.expiries = self.expiries[: self._ts_expiries]
        if self.spot_price is not None and self.strikes:
            center = round(self.spot_price)
            allowed = [s for s in self.strikes if abs(s - center) <= self._ts_window]
            if not allowed:
                closest = min(self.strikes, key=lambda x: abs(x - center))
                allowed = [closest]
            self.strikes = sorted(set(allowed))
            self._strike_lookup = {s: s for s in self.strikes}
        self.expected_contracts = len(self.expiries) * len(self.strikes) * 2
        logger.info(
            f"✅ [stap 6] Er zijn {len(self.expiries)} expiries en {len(self.strikes)} strikes dus {self.expected_contracts} combinaties"
        )
        if self.expected_contracts == 0:
            self.all_data_event.set()


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
    """Wait until market data has been populated or timeout occurs.

    Access to ``app.market_data`` is protected by ``app.data_lock`` so the
    function can safely be called from multiple threads.
    """
    start = time.time()
    retries = int(cfg_get("OPTION_DATA_RETRIES", 0)) if isinstance(app, OptionChainClient) else 0
    interval = 1

    while time.time() - start < timeout:
        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            break
        if isinstance(app, OptionChainClient):
            event = getattr(app, "all_data_event", app.market_event)
            # Progress-based completion check
            if (
                app.expected_contracts
                and len(app._completed_requests) >= app.expected_contracts
                and app.spot_price is not None
            ):
                logger.debug(
                    f"Market data ontvangen binnen {time.time() - start:.2f}s"
                )
                return True
        else:
            event = getattr(app, "market_event", app.data_event)

        wait_time = min(interval, remaining)
        event.wait(wait_time)
        if not event.is_set():
            event.clear()
            continue

        if isinstance(app, OptionChainClient):
            hist = getattr(app, "use_hist_iv", False)
            if (
                getattr(app, "all_data_event", event).is_set()
                and app.spot_price is not None
            ):
                if not hist and retries > 0 and app.incomplete_requests():
                    app.retry_incomplete_requests(wait=False)
                    retries -= 1
                    start = time.time()
                    continue
                logger.debug(
                    f"Market data ontvangen binnen {time.time() - start:.2f}s"
                )
                return True
            if not app.connected.is_set() and not app.incomplete_requests():
                logger.debug(
                    f"Market data aborted after disconnect at {time.time() - start:.2f}s"
                )
                return False
        else:
            if app.spot_price is not None and event.is_set():
                logger.debug(f"Market data ontvangen binnen {time.time() - start:.2f}s")
                return True

            if hasattr(app, "data_lock"):
                with app.data_lock:
                    has_bidask = any(
                        "bid" in rec or "ask" in rec for rec in app.market_data.values()
                    )
            else:
                has_bidask = any(
                    "bid" in rec or "ask" in rec for rec in app.market_data.values()
                )
            if has_bidask:
                logger.debug(
                    f"Bid/ask ontvangen binnen {time.time() - start:.2f}s"
                )
                return True

        event.clear()

    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


@log_result
def compute_iv_term_structure(
    app: OptionChainClient, *, strike_window: int | None = None
) -> dict[str, float]:
    """Return front-month term structure metrics based on retrieved IVs.

    Parameters
    ----------
    app:
        Running :class:`OptionChainClient` with populated ``market_data``.
        Access to the data is synchronized with ``app.data_lock`` so this
        function is thread-safe.
    strike_window:
        Absolute distance from the spot price used to select strikes. Defaults
        to ``5`` when not provided.
    """

    if app.spot_price is None:
        return {}

    if strike_window is None:
        strike_window = int(cfg_get("TERM_STRIKE_WINDOW", 5))

    grouped: Dict[str, list[float]] = {}
    if hasattr(app, "data_lock"):
        with app.data_lock:
            items = list(app.market_data.items())
    else:
        items = list(app.market_data.items())
    for req_id, rec in items:
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
    symbol: str,
    app: MarketClient | None = None,
    *,
    timeout: int | None = None,
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
        "term_m1_m2": None,
        "term_m1_m3": None,
        "iv_rank": data.get("iv_rank"),
        "implied_volatility": data.get("implied_volatility"),
        "iv_percentile": data.get("iv_percentile"),
    }

    owns_app = False
    if app is None:
        app = TermStructureClient(symbol)
        start_app(app)
        owns_app = True

    wait_time = timeout if timeout is not None else cfg_get("MARKET_DATA_TIMEOUT", 30)
    if (
        timeout is None
        and isinstance(app, OptionChainClient)
        and not app.expiries
    ):
        wait_time = cfg_get("SPOT_TIMEOUT", 10)

    if await_market_data(app, symbol, timeout=wait_time):
        metrics["spot_price"] = app.spot_price or metrics["spot_price"]
        if isinstance(app, OptionChainClient):
            term = compute_iv_term_structure(app)
            if term.get("term_m1_m2") is not None:
                metrics["term_m1_m2"] = term["term_m1_m2"]
            if term.get("term_m1_m3") is not None:
                metrics["term_m1_m3"] = term["term_m1_m3"]

    if owns_app:
        app.disconnect()

    logger.debug(f"Fetched metrics for {symbol}: {metrics}")
    return metrics


__all__ = [
    "MarketClient",
    "OptionChainClient",
    "TermStructureClient",
    "start_app",
    "await_market_data",
    "compute_iv_term_structure",
    "fetch_market_metrics",
]
