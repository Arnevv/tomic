from __future__ import annotations

from datetime import datetime
import threading
import time

from ibapi.account_summary_tags import AccountSummaryTags
from ibapi.common import OrderId, TickerId
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum

from tomic.api.base_client import BaseIBApp
from tomic.analysis.get_iv_rank import fetch_iv_metrics
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.analysis.metrics import historical_volatility, average_true_range
from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.helpers import dump_json


# Alias to avoid NameError if standard logging is accidentally used
logging = logger


class IBApp(BaseIBApp):
    def __init__(self):
        super().__init__()

        self.positions_data = []
        self.open_orders = []
        self.account_values = {}
        self.base_currency = None
        self.req_id = 5000
        self.req_id_to_index = {}
        self.market_req_id = 8000
        self.market_req_map = {}
        self.contract_req_map = {}
        self.spot_data = {}
        self.hist_event = threading.Event()
        self.hv_data = {}
        self.atr_data = {}
        self.iv_rank_data = {}
        self.account_event = threading.Event()
        self.position_event = threading.Event()

    def nextValidId(self, orderId: int):
        logger.info(f"✅ Verbonden. OrderId: {orderId}")
        for data_type in (1, 2, 3):
            self.reqMarketDataType(data_type)
            time.sleep(0.2)
        self.account_event.clear()
        self.position_event.clear()
        self.reqAccountSummary(9001, "All", AccountSummaryTags.AllTags)
        self.reqPositions()
        self.reqOpenOrders()

    def position(
        self, account: str, contract: Contract, position: float, avgCost: float
    ):
        idx = len(self.positions_data)
        self.positions_data.append(
            {
                "symbol": contract.symbol,
                "secType": contract.secType,
                "exchange": contract.exchange,
                "position": position,
                "avgCost": avgCost,
                "conId": contract.conId,
                "localSymbol": contract.localSymbol,
                "lastTradeDate": contract.lastTradeDateOrContractMonth,
                "strike": contract.strike,
                "right": contract.right,
                "multiplier": contract.multiplier,
                "currency": contract.currency,
                "bid": None,
                "ask": None,
                "iv": None,
                "delta": None,
                "gamma": None,
                "vega": None,
                "theta": None,
            }
        )
        logger.debug(
            "Positie %s: localSymbol=%s exchange=%s strike=%s right=%s",
            idx,
            contract.localSymbol,
            contract.exchange,
            contract.strike,
            contract.right,
        )
        self.reqPnLSingle(self.req_id, account, "", contract.conId)
        self.req_id_to_index[self.req_id] = idx
        self.req_id += 1

        mkt_id = self.market_req_id
        self.market_req_map[mkt_id] = idx
        if not getattr(contract, "exchange", None):
            contract.exchange = cfg_get("OPTIONS_EXCHANGE", "SMART")
            contract.primaryExchange = cfg_get("OPTIONS_PRIMARY_EXCHANGE", "ARCA")
        self.reqMktData(mkt_id, contract, "", True, False, [])
        self.market_req_id += 1

        if contract.symbol not in self.spot_data:
            u = Contract()
            u.symbol = contract.symbol
            u.secType = "STK"
            u.exchange = cfg_get("UNDERLYING_EXCHANGE", "SMART")
            u.primaryExchange = cfg_get("UNDERLYING_PRIMARY_EXCHANGE", "ARCA")
            u.currency = contract.currency
            spot_id = self.market_req_id
            self.market_req_map[spot_id] = {"underlying": contract.symbol}
            self.spot_data[contract.symbol] = {"bid": None, "ask": None, "last": None}
            self.reqMktData(spot_id, u, "", False, False, [])
            self.market_req_id += 1

    def openOrder(self, orderId: OrderId, contract: Contract, order, orderState):
        self.open_orders.append(
            {
                "orderId": orderId,
                "symbol": contract.symbol,
                "action": order.action,
                "totalQuantity": order.totalQuantity,
                "orderType": order.orderType,
                "limitPrice": order.lmtPrice,
            }
        )

    def accountSummary(self, reqId, account, tag, value, currency):
        """Store account summary values, keeping track of the currency."""
        # Save per currency
        self.account_values[(tag, currency)] = value
        # Track the account's base currency so we know which values to
        # expose under the plain tags.
        if tag == "AccountCurrency":
            self.base_currency = value

        # If the value is reported in the base currency, or if we have not yet
        # stored a value for this tag, also store it under the bare tag so the
        # rest of the code can access numbers that match what TWS displays.
        if (
            currency == "BASE"
            or (self.base_currency and currency == self.base_currency)
            or tag not in self.account_values
        ):
            self.account_values[tag] = value

    def accountSummaryEnd(self, reqId: int):
        logger.info("🔹 Accountoverzicht opgehaald.")
        self.account_event.set()

    def pnlSingle(
        self,
        reqId: int,
        pos: int,
        dailyPnL: float,
        unrealizedPnL: float,
        realizedPnL: float,
        value: float,
    ):
        idx = self.req_id_to_index.get(reqId)
        if idx is not None and idx < len(self.positions_data):
            self.positions_data[idx].update(
                {
                    "dailyPnL": dailyPnL,
                    "unrealizedPnL": unrealizedPnL,
                    "realizedPnL": realizedPnL,
                }
            )

    def positionEnd(self):
        logger.info("🔹 Posities opgehaald.")
        self.position_event.set()

    def openOrderEnd(self):
        logger.info("🔹 Open orders opgehaald.")

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        if reqId in self.market_req_map:
            mapping = self.market_req_map[reqId]
            if isinstance(mapping, dict) and mapping.get("underlying"):
                data = self.spot_data[mapping["underlying"]]
                if tickType == 1:
                    data["bid"] = price
                elif tickType == 2:
                    data["ask"] = price
                elif tickType == TickTypeEnum.LAST:
                    data["last"] = price
            else:
                idx = mapping
                d = self.positions_data[idx]
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
    ):
        if reqId in self.market_req_map and not isinstance(
            self.market_req_map[reqId], dict
        ):
            idx = self.market_req_map[reqId]
            d = self.positions_data[idx]
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
            if undPrice is not None:
                d["underlyingPrice"] = undPrice

    def historicalData(self, reqId: int, bar):
        self.historical_data.append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        self.hist_event.set()

    def calculate_hv30(self) -> float | None:
        """Calculate 30-day historical volatility using collected bars."""
        closes = [b.close for b in self.historical_data]
        return historical_volatility(closes, window=30)

    def calculate_atr14(self) -> float | None:
        """Calculate 14-day Average True Range using collected bars."""
        highs = [b.high for b in self.historical_data]
        lows = [b.low for b in self.historical_data]
        closes = [b.close for b in self.historical_data]
        return average_true_range(highs, lows, closes, period=14)

    def count_incomplete(self):
        """Return how many positions are missing market or Greek data."""
        missing_keys = ["bid", "ask", "iv", "delta", "gamma", "vega", "theta"]
        incomplete = 0
        for pos in self.positions_data:
            if any(pos.get(k) is None for k in missing_keys):
                incomplete += 1
        return incomplete

    def request_mktdata_for_index(self, idx: int) -> None:
        """(Re)request market data for the position at ``idx``."""
        if idx >= len(self.positions_data):
            return
        d = self.positions_data[idx]
        contract = Contract()
        contract.conId = d["conId"]
        contract.symbol = d["symbol"]
        contract.secType = d["secType"]
        contract.currency = d.get("currency")
        contract.exchange = cfg_get("OPTIONS_EXCHANGE", "SMART")
        contract.primaryExchange = cfg_get("OPTIONS_PRIMARY_EXCHANGE", "ARCA")
        contract.localSymbol = d.get("localSymbol")
        contract.lastTradeDateOrContractMonth = d.get("lastTradeDate")
        if d.get("strike") is not None:
            contract.strike = float(d["strike"])
        if d.get("right"):
            contract.right = d["right"]
        if d.get("multiplier"):
            contract.multiplier = str(d["multiplier"])

        req_id = self.market_req_id
        self.market_req_map[req_id] = idx
        self.reqMktData(req_id, contract, "", True, False, [])
        self.market_req_id += 1

    def contractDetails(self, reqId: int, details) -> None:  # noqa: N802
        idx = self.contract_req_map.get(reqId)
        con = details.contract
        logger.debug(
            "Ontvangen contractdetails voor leg %s: %s %s %s %s",
            idx,
            con.localSymbol,
            con.exchange,
            con.strike,
            con.right,
        )
        self.contract_req_map.pop(reqId, None)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId in self.contract_req_map:
            idx = self.contract_req_map.pop(reqId)
            logger.warning(f"Geen contractdetails ontvangen voor leg {idx}")

    IGNORED_ERROR_CODES: set[int] = getattr(BaseIBApp, "IGNORED_ERROR_CODES", set()) | {2150}
    WARNING_ERROR_CODES: set[int] = getattr(BaseIBApp, "WARNING_ERROR_CODES", set())


def retrieve_positions_and_orders(
    app: IBApp, host: str, port: int, client_id: int
) -> None:
    """Connect and populate ``positions_data`` and ``open_orders``."""
    app.connect(host, port, clientId=client_id)
    thread = threading.Thread(target=app.run)
    thread.start()
    app.account_event.wait(timeout=10)
    app.position_event.wait(timeout=10)


def fetch_historical_metrics(app: IBApp) -> None:
    """Download bars and compute HV30/ATR14 for all symbols."""
    symbols = {p["symbol"] for p in app.positions_data}
    for sym in symbols:
        app.historical_data = []
        app.hist_event.clear()
        contract = Contract()
        contract.symbol = sym
        contract.secType = "STK"
        contract.exchange = cfg_get("UNDERLYING_EXCHANGE", "SMART")
        contract.primaryExchange = cfg_get("UNDERLYING_PRIMARY_EXCHANGE", "ARCA")
        contract.currency = "USD"
        contract.includeExpired = True
        queryTime = datetime.now().strftime("%Y%m%d-%H:%M:%S")
        req_id = app.market_req_id
        app.market_req_id += 1
        logger.debug(contract.__dict__)
        app.reqHistoricalData(
            req_id,
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
        app.hist_event.wait(timeout=10)
        app.hv_data[sym] = app.calculate_hv30()
        app.atr_data[sym] = app.calculate_atr14()


def enrich_with_iv_rank(app: IBApp) -> None:
    """Fetch and store IV rank/percentile for all symbols."""
    symbols = {p["symbol"] for p in app.positions_data}
    for sym in symbols:
        try:
            metrics = fetch_iv_metrics(sym)
            app.iv_rank_data[sym] = metrics.get("iv_rank")
            app.iv_rank_data[f"{sym}_pct"] = metrics.get("iv_percentile")
        except Exception:  # pragma: no cover - network errors
            app.iv_rank_data[sym] = None
            app.iv_rank_data[f"{sym}_pct"] = None


def retry_incomplete_positions(app: IBApp, retries: int = 4, wait: int = 7) -> None:
    """Retry requesting market data for incomplete legs."""
    missing_keys = ["bid", "ask", "iv", "delta", "gamma", "vega", "theta"]
    for attempt in range(retries):
        incomplete = [
            i
            for i, p in enumerate(app.positions_data)
            if any(p.get(k) is None for k in missing_keys)
        ]
        if not incomplete:
            return
        for idx in incomplete:
            leg = app.positions_data[idx]
            logger.warning(
                "Incomplete leg #%s: localSymbol=%s exchange=%s strike=%s right=%s",
                idx,
                leg.get("localSymbol"),
                leg.get("exchange"),
                leg.get("strike"),
                leg.get("right"),
            )
        logger.info(f"🔄 Retry {attempt + 1} for {len(incomplete)} incomplete legs")
        for idx in incomplete:
            app.request_mktdata_for_index(idx)
            d = app.positions_data[idx]
            c = Contract()
            c.conId = d["conId"]
            c.symbol = d["symbol"]
            c.secType = d["secType"]
            c.currency = d.get("currency")
            c.exchange = cfg_get("OPTIONS_EXCHANGE", "SMART")
            c.primaryExchange = cfg_get("OPTIONS_PRIMARY_EXCHANGE", "ARCA")
            c.localSymbol = d.get("localSymbol")
            c.lastTradeDateOrContractMonth = d.get("lastTradeDate")
            if d.get("strike") is not None:
                c.strike = float(d["strike"])
            if d.get("right"):
                c.right = d["right"]
            if d.get("multiplier"):
                c.multiplier = str(d["multiplier"])
            req_id = app.market_req_id
            app.contract_req_map[req_id] = idx
            app.reqContractDetails(req_id, c)
            app.market_req_id += 1
        time.sleep(wait)
    if app.count_incomplete() > 0:
        for idx, p in enumerate(app.positions_data):
            if any(p.get(k) is None for k in missing_keys):
                logger.warning(f"Leg {idx} nog incompleet: {p}")
        logger.warning("⚠️ Some legs remain incomplete after retries.")


def main(client_id: int | None = None) -> None:
    """CLI entry point orchestrating the data collection steps."""
    setup_logging()
    logger.info("🚀 Ophalen van accountinformatie")
    app = IBApp()
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    client = client_id if client_id is not None else int(cfg_get("IB_CLIENT_ID", 100))

    retrieve_positions_and_orders(app, host, port, client)
    fetch_historical_metrics(app)
    enrich_with_iv_rank(app)

    time.sleep(10)
    waited = 10
    while app.count_incomplete() > 0 and waited < 60:
        time.sleep(5)
        waited += 5
    if app.count_incomplete() > 0:
        logger.warning("⚠️ Some legs remain incomplete. Retrying...")
        retry_incomplete_positions(app)

    portfolio = compute_portfolio_greeks(app.positions_data)

    for pos in app.positions_data:
        sym = pos["symbol"]
        pos["HV30"] = app.hv_data.get(sym)
        pos["ATR14"] = app.atr_data.get(sym)
        pos["IV_Rank"] = app.iv_rank_data.get(sym)
        pos["IV_Percentile"] = app.iv_rank_data.get(f"{sym}_pct")

    dump_json(app.positions_data, cfg_get("POSITIONS_FILE", "positions.json"))
    logging.info(
        "💾 Posities opgeslagen in {}",
        cfg_get("POSITIONS_FILE", "positions.json"),
    )

    base_currency_vals = {
        k: v for k, v in app.account_values.items() if isinstance(k, str)
    }
    dump_json(base_currency_vals, cfg_get("ACCOUNT_INFO_FILE", "account_info.json"))

    logger.info(
        f"💾 Accountinfo opgeslagen in {cfg_get('ACCOUNT_INFO_FILE', 'account_info.json')}"
    )

    logger.opt(raw=True, colors=False).info("\n📐 Portfolio Greeks:\n")
    for k, v in portfolio.items():
        logger.opt(raw=True, colors=False).info(f"{k}: {round(v, 4):.4f}\n")

    app.disconnect()
    logger.success("✅ Accountinformatie verwerkt")


if __name__ == "__main__":
    main()
