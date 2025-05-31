# Common CombinedApp implementation shared across market utilities.
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.ticktype import TickTypeEnum
from ibapi.common import TickerId
import threading
from datetime import datetime
from tomic.logging import logger

from .market_utils import (
    create_underlying,
    create_option_contract,
    calculate_hv30,
    calculate_atr14,
)


class CombinedApp(EWrapper, EClient):
    """IB API client that exposes both EClient and EWrapper behaviour."""

    def __init__(self, symbol: str):
        EClient.__init__(self, self)
        self.symbol = symbol.upper()
        self.ready_event = threading.Event()
        self.spot_price_event = threading.Event()
        self.vix_event = threading.Event()
        self.contract_details_event = threading.Event()
        self.option_params_event = threading.Event()
        self.historical_event = threading.Event()

        self.spot_price = None
        self.vix_price = None
        self.conId = None
        self.expiries = []
        self.strikes = []
        self.trading_class = None
        self.market_data = {}
        self.invalid_contracts = set()
        self.req_id_counter = 2000
        self.historical_data = []

    def get_next_req_id(self):
        self.req_id_counter += 1
        return self.req_id_counter

    # --- Connection callbacks -------------------------------------------------
    def nextValidId(self, orderId: int):  # noqa: N802 (callback name)
        self.reqMarketDataType(2)
        self.request_spot_price()
        self.request_vix()
        self.ready_event.set()

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
                    }
                    self.reqMktData(req_id, contract, "", True, False, [])

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
        if c.secType == "STK" and c.symbol.upper() == self.symbol:
            self.conId = details.contract.conId

    def contractDetailsEnd(self, reqId: int):  # noqa: N802
        self.contract_details_event.set()

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

        def is_third_friday(date_str):
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.weekday() == 4 and 15 <= dt.day <= 21
            except Exception:
                return False

        expiries = sorted(expirations)
        regulars = [e for e in expiries if is_third_friday(e)]
        self.expiries = regulars[:3]
        center = round(self.spot_price)
        filtered_strikes = [
            s
            for s in strikes
            if center - 100 <= s <= center + 100 and isinstance(s, (int, float))
        ]
        self.strikes = sorted(filtered_strikes)
        self.trading_class = tradingClass
        self.option_params_event.set()
        self.request_option_market_data()

    def error(self, reqId: TickerId, errorCode: int, errorString: str):  # noqa: N802
        if errorCode == 200 and reqId in self.market_data:
            self.invalid_contracts.add(reqId)
        elif errorCode not in (2104, 2106, 2158, 2176):
            logger.error("⚠️ Error %s (%s): %s", reqId, errorCode, errorString)

    def tickPrice(
        self, reqId: TickerId, tickType: int, price: float, attrib
    ):  # noqa: N802
        if reqId == 1001 and tickType == TickTypeEnum.LAST:
            self.spot_price = round(price, 2)
            self.cancelMktData(1001)
            self.spot_price_event.set()
        elif reqId == 1002 and tickType == TickTypeEnum.LAST:
            self.vix_price = round(price, 2)
            self.cancelMktData(1002)
            self.vix_event.set()
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

    # --- Calculations --------------------------------------------------------
    def calculate_hv30(self):
        return calculate_hv30(self.historical_data)

    def calculate_atr14(self):
        return calculate_atr14(self.historical_data)

    def count_incomplete(self):
        return sum(
            1
            for k, d in self.market_data.items()
            if k not in self.invalid_contracts
            and (
                d["bid"] is None
                or d["ask"] is None
                or d["iv"] is None
                or d["delta"] is None
                or d["gamma"] is None
                or d["vega"] is None
                or d["theta"] is None
            )
        )


__all__ = ["CombinedApp"]
