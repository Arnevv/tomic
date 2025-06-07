# Common CombinedApp implementation shared across market utilities.
from tomic.api.base_client import BaseIBApp
from ibapi.contract import Contract, ContractDetails
from ibapi.ticktype import TickTypeEnum
from ibapi.common import TickerId
import threading
from datetime import datetime
from tomic.utils import extract_weeklies
from tomic.logging import logger

from .market_utils import (
    create_underlying,
    create_option_contract,
)


class CombinedApp(BaseIBApp):
    """IB API client exposing ``EClient`` and ``EWrapper`` behaviour."""

    def __init__(self, symbol: str):
        super().__init__()
        self.symbol = symbol.upper()
        self.ready_event = threading.Event()
        self.spot_price_event = threading.Event()
        self.vix_event = threading.Event()
        self.contract_details_event = threading.Event()
        self.option_params_event = threading.Event()
        self.historical_event = threading.Event()
        self.historical_data: list = []

        self.spot_price: float | None = None
        self.vix_price: float | None = None
        self.conId: int | None = None
        self.expiries: list[str] = []
        self.strikes: list[float] = []
        self.trading_class: str | None = None
        self.req_id_counter = 2000
        self.market_data: dict[int, dict] = {}
        self.invalid_contracts: set[int] = set()

    def start(
        self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1
    ) -> threading.Thread:
        """Connect to IB and start the API thread.

        This implementation waits for ``nextValidId`` before returning so that
        callers can safely issue requests immediately after ``start``.
        """

        logger.info("Starting IB connection")
        print("⏳ waiting for nextValidId")

        self.connect(host, port, clientId=client_id)

        # Start run-loop
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()

        # Trigger handshake to request ``nextValidId``
        self.reqIds(1)

        # Start IB API (moet NA run-thread en NA connect gebeuren)
        self.startApi()
        self._api_started = True

        success = self.ready_event.wait(timeout=5)
        if not success:
            logger.error(
                "❌ nextValidId werd niet ontvangen – check connectie met TWS."
            )
            raise TimeoutError(
                "❌ nextValidId werd niet ontvangen – check connectie met TWS."
            )

        return thread

    def get_next_req_id(self):
        self.req_id_counter += 1
        return self.req_id_counter

    # --- Connection callbacks -------------------------------------------------
    def nextValidId(self, orderId: int):  # noqa: N802 (callback name)
        logger.success(f"✅ nextValidId ontvangen: {orderId}")
        self.ready_event.set()
        logger.debug("ready_event set")

    def start_requests(self) -> None:
        """Initiate all data requests once the connection is ready."""
        logger.info("Starting market data requests")
        self.reqMarketDataType(2)
        self.request_spot_price()
        self.request_vix()
        self.get_historical_data()

    # --- Requests -------------------------------------------------------------
    def request_spot_price(self):
        contract = create_underlying(self.symbol)
        self.reqMktData(1001, contract, "", False, False, [])
        self.reqContractDetails(1101, contract)

    def request_vix(self):
        contract = Contract()
        contract.symbol = "VIX"
        contract.secType = "IND"
        contract.exchange = "CBOE"
        contract.currency = "USD"
        self.reqMktData(1002, contract, "", False, False, [])

    def request_option_market_data(self):
        for expiry in self.expiries:
            for strike in self.strikes:
                for right in ["C", "P"]:
                    contract = create_option_contract(
                        self.symbol, expiry, strike, right, self.trading_class
                    )
                    req_id = self.get_next_req_id()
                    self.market_data[req_id] = {
                        "expiry": expiry,
                        "strike": strike,
                        "right": right,
                        "bid": None,
                        "ask": None,
                        "iv": None,
                        "delta": None,
                        "gamma": None,
                        "vega": None,
                        "theta": None,
                        "volume": None,
                    }
                    # Request streaming market data including option specific
                    # generic ticks for volume. Snapshot
                    # requests are not allowed for generic ticks.
                    self.reqMktData(
                        req_id,
                        contract,
                        "100",
                        False,
                        False,
                        [],
                    )

    def get_historical_data(self):
        contract = create_underlying(self.symbol)
        queryTime = datetime.now().strftime("%Y%m%d-%H:%M:%S")
        self.reqHistoricalData(
            2000,
            contract,
            queryTime,
            "30 D",
            "1 day",
            "TRADES",
            0,
            1,
            False,
            [],
        )

    # --- Data callbacks ------------------------------------------------------
    def contractDetails(self, reqId: int, details: ContractDetails):  # noqa: N802
        c = details.contract
        if c.symbol.upper() == self.symbol and c.secType in {"STK", "IND"}:
            self.conId = c.conId

    def contractDetailsEnd(self, reqId: int):  # noqa: N802
        self.contract_details_event.set()
        logger.debug("contract_details_event set")

    def securityDefinitionOptionParameter(
        self,
        reqId,
        exchange,
        underlyingConId,
        tradingClass,
        multiplier,
        expirations,
        strikes,
    ):  # noqa: D417,N802
        if self.expiries:
            return

        def is_third_friday(date_str: str) -> bool:
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.weekday() == 4 and 15 <= dt.day <= 21
            except Exception:
                return False

        expiries = sorted(expirations)
        regulars = [e for e in expiries if is_third_friday(e)]
        weeklies = extract_weeklies(expiries)
        self.expiries = regulars[:3] + weeklies
        center = round(self.spot_price)
        filtered_strikes = [
            s
            for s in strikes
            if center - 100 <= s <= center + 100 and isinstance(s, (int, float))
        ]
        self.strikes = sorted(filtered_strikes)
        self.trading_class = tradingClass
        self.option_params_event.set()
        logger.debug("option_params_event set")
        self.request_option_market_data()

    def error(self, reqId: TickerId, errorCode: int, errorString: str):  # noqa: N802
        if errorCode == 200 and reqId in self.market_data:
            self.invalid_contracts.add(reqId)
        else:
            super().error(reqId, errorCode, errorString)

    def tickPrice(
        self, reqId: TickerId, tickType: int, price: float, attrib
    ):  # noqa: N802
        if reqId == 1001 and tickType == TickTypeEnum.LAST:
            self.spot_price = round(price, 2)
            self.cancelMktData(1001)
            self.spot_price_event.set()
            logger.debug("spot_price_event set")
        elif reqId == 1002 and tickType == TickTypeEnum.LAST:
            self.vix_price = round(price, 2)
            self.cancelMktData(1002)
            self.vix_event.set()
            logger.debug("vix_event set")
        elif reqId in self.market_data:
            d = self.market_data[reqId]
            if tickType == 1:
                d["bid"] = price
            elif tickType == 2:
                d["ask"] = price
            elif tickType == 14:
                d["iv"] = price
            elif tickType == 24:
                d["delta"] = price
            elif tickType == 25:
                d["gamma"] = price
            elif tickType == 26:
                d["vega"] = price
            elif tickType == 27:
                d["theta"] = price
            elif tickType == 8:
                d["volume"] = price

    def tickSize(self, reqId: TickerId, tickType: int, size: int):  # noqa: N802
        if reqId in self.market_data and tickType == 8:
            self.market_data[reqId]["volume"] = size

    def tickGeneric(self, reqId: TickerId, tickType: int, value: float):  # noqa: N802
        if reqId in self.market_data:
            if tickType == 100:
                self.market_data[reqId]["volume"] = value

    def tickOptionComputation(
        self,
        reqId,
        tickType,
        tickAttrib,
        impliedVol,
        delta,
        optPrice,
        pvDividend,
        gamma,
        vega,
        theta,
        undPrice,
    ):  # noqa: D417,N802
        if reqId in self.market_data:
            d = self.market_data[reqId]
            if impliedVol is not None:
                d["iv"] = impliedVol
            if delta is not None:
                d["delta"] = delta
            if gamma is not None:
                d["gamma"] = gamma
            if vega is not None:
                d["vega"] = vega
            if theta is not None:
                d["theta"] = theta

    def historicalData(self, reqId: int, bar):  # noqa: N802
        self.historical_data.append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):  # noqa: N802
        self.historical_event.set()
        logger.debug("historical_event set")


__all__ = ["CombinedApp"]
