from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import *
from ibapi.account_summary_tags import *
from ibapi.ticktype import TickTypeEnum

from datetime import datetime
import json
import math
import statistics
from tomic.analysis.get_iv_rank import fetch_iv_metrics

import threading
import time

from tomic.config import get as cfg_get


def _fmt_money(value):
    """Return value formatted as dollar amount if possible."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return value or "-"


def print_account_overview(values: dict) -> None:
    """Print account status and explanation table."""
    net_liq = values.get("NetLiquidation")
    buying_power = values.get("BuyingPower")
    init_margin = values.get("InitMarginReq")
    excess_liq = values.get("ExcessLiquidity")
    gross_pos_val = values.get("GrossPositionValue")
    cushion = values.get("Cushion")

    margin_pct = None
    try:
        margin_pct = float(init_margin) / float(net_liq)
    except (TypeError, ValueError, ZeroDivisionError):
        margin_pct = None

    print("\n📊 Accountstatus:")
    print(f"- NetLiquidation:      {_fmt_money(net_liq)}")
    print(f"- Buying Power:        {_fmt_money(buying_power)}")
    if init_margin is not None:
        line = _fmt_money(init_margin)
        if margin_pct is not None:
            line += f" (≈ {margin_pct:.0%} van vermogen)"
        print(f"- Margin gebruikt:     {line}")
    print(f"- Excess Liquidity:    {_fmt_money(excess_liq)}")
    print(f"- Gross Position Value: {_fmt_money(gross_pos_val)}")
    print(f"- Cushion:              {cushion}")

    uitleg = {
        "NetLiquidation": "Jouw actuele vermogen. Hoofdreferentie voor alles.",
        "BuyingPower": "Wat je direct mag inzetten voor nieuwe trades.",
        "InitMarginReq": "Hoeveel margin je in totaal verbruikt met je posities.",
        "ExcessLiquidity": "Hoeveel marge je veilig overhoudt. Buffer tegen margin calls.",
    }

    rows = [
        ("💰 **Net Liquidation Value**", _fmt_money(net_liq), uitleg["NetLiquidation"]),
        ("🏦 **Buying Power**", _fmt_money(buying_power), uitleg["BuyingPower"]),
        (
            "⚖️ **Used Margin (init)**",
            _fmt_money(init_margin) + (f" (≈ {margin_pct:.0%} van vermogen)" if margin_pct is not None else ""),
            uitleg["InitMarginReq"],
        ),
        ("✅ **Excess Liquidity**", _fmt_money(excess_liq), uitleg["ExcessLiquidity"]),
        ("**Gross Position Value**", _fmt_money(gross_pos_val), "–"),
        ("**Cushion**", str(cushion), "–"),
    ]

    print("\n| Label | Waarde | Waarom? |")
    print("| ---------------------------- | ------------------------------------ | --------------------------------------------------------------- |")
    for label, value, reason in rows:
        print(f"| {label} | {value} | {reason} |")

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

        self.positions_data = []
        self.open_orders = []
        self.account_values = {}
        self.base_currency = None
        self.req_id = 5000
        self.req_id_to_index = {}
        self.market_req_id = 8000
        self.market_req_map = {}
        self.spot_data = {}
        self.historical_data = []
        self.hist_event = threading.Event()
        self.hv_data = {}
        self.atr_data = {}
        self.iv_rank_data = {}
        self.account_event = threading.Event()
        self.position_event = threading.Event()

    def nextValidId(self, orderId: int):
        print("✅ Verbonden. OrderId:", orderId)
        self.reqMarketDataType(2)
        self.account_event.clear()
        self.position_event.clear()
        self.reqAccountSummary(9001, "All", AccountSummaryTags.AllTags)
        self.reqPositions()
        self.reqOpenOrders()

    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        idx = len(self.positions_data)
        self.positions_data.append({
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
            "theta": None
        })
        self.reqPnLSingle(self.req_id, account, "", contract.conId)
        self.req_id_to_index[self.req_id] = idx
        self.req_id += 1

        mkt_id = self.market_req_id
        self.market_req_map[mkt_id] = idx
        if not getattr(contract, "exchange", None):
            contract.exchange = "SMART"
            contract.primaryExchange = "SMART"
        self.reqMktData(mkt_id, contract, "", True, False, [])
        self.market_req_id += 1

        if contract.symbol not in self.spot_data:
            u = Contract()
            u.symbol = contract.symbol
            u.secType = "STK"
            u.exchange = "SMART"
            u.primaryExchange = "ARCA"
            u.currency = contract.currency
            spot_id = self.market_req_id
            self.market_req_map[spot_id] = {"underlying": contract.symbol}
            self.spot_data[contract.symbol] = {"bid": None, "ask": None, "last": None}
            self.reqMktData(spot_id, u, "", False, False, [])
            self.market_req_id += 1

    def openOrder(self, orderId: OrderId, contract: Contract, order, orderState):
        self.open_orders.append({
            "orderId": orderId,
            "symbol": contract.symbol,
            "action": order.action,
            "totalQuantity": order.totalQuantity,
            "orderType": order.orderType,
            "limitPrice": order.lmtPrice
        })

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
        print("🔹 Accountoverzicht opgehaald.")
        self.account_event.set()

    def pnlSingle(self, reqId: int, pos: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float, value: float):
        idx = self.req_id_to_index.get(reqId)
        if idx is not None and idx < len(self.positions_data):
            self.positions_data[idx].update({
                "dailyPnL": dailyPnL,
                "unrealizedPnL": unrealizedPnL,
                "realizedPnL": realizedPnL
            })

    def positionEnd(self):
        print("🔹 Posities opgehaald.")
        self.position_event.set()

    def openOrderEnd(self):
        print("🔹 Open orders opgehaald.")

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

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol,
                              delta, optPrice, pvDividend, gamma, vega, theta,
                              undPrice):
        if reqId in self.market_req_map and not isinstance(self.market_req_map[reqId], dict):
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

    def calculate_hv30(self):
        closes = [bar.close for bar in self.historical_data if hasattr(bar, "close")]
        if len(closes) < 2:
            return None
        log_returns = [math.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]
        std_dev = statistics.stdev(log_returns)
        return round(std_dev * math.sqrt(252) * 100, 2)

    def calculate_atr14(self):
        trs = []
        for i in range(1, len(self.historical_data)):
            high = self.historical_data[i].high
            low = self.historical_data[i].low
            prev_close = self.historical_data[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        if len(trs) < 14:
            return None
        atr14 = statistics.mean(trs[-14:])
        return round(atr14, 2)

    def count_incomplete(self):
        """Return how many positions are missing market or Greek data."""
        return sum(
            1
            for d in self.positions_data
            if (
                d["bid"] is None
                or d["ask"] is None
                or d["iv"] is None
                or d["delta"] is None
                or d["gamma"] is None
                or d["vega"] is None
                or d["theta"] is None
            )
        )

    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        print(f"⚠️ Error {errorCode}: {errorString}")


def run_loop(app):
    app.run()


def main() -> None:
    """CLI entry point executing the original script logic."""
    app = IBApp()
    app.connect("127.0.0.1", 7497, clientId=1)

    api_thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
    api_thread.start()

    app.account_event.wait(timeout=10)
    app.position_event.wait(timeout=10)

    symbols = set(p["symbol"] for p in app.positions_data)
    for sym in symbols:
        app.historical_data = []
        app.hist_event.clear()
        contract = Contract()
        contract.symbol = sym
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.primaryExchange = "ARCA"
        contract.currency = "USD"
        queryTime = datetime.now().strftime("%Y%m%d-%H:%M:%S")
        req_id = app.market_req_id
        app.market_req_id += 1
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
        hv30 = app.calculate_hv30()
        atr14 = app.calculate_atr14()
        app.hv_data[sym] = hv30
        app.atr_data[sym] = atr14

        try:
            metrics = fetch_iv_metrics(sym)
            app.iv_rank_data[sym] = metrics.get("iv_rank")
            app.iv_rank_data[f"{sym}_pct"] = metrics.get("iv_percentile")
        except Exception:
            app.iv_rank_data[sym] = None
            app.iv_rank_data[f"{sym}_pct"] = None

    time.sleep(10)
    waited = 10
    while app.count_incomplete() > 0 and waited < 60:
        time.sleep(5)
        waited += 5
    if app.count_incomplete() > 0:
        print("⚠️ Some legs remain incomplete.")

    portfolio = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for pos in app.positions_data:
        mult = float(pos.get("multiplier") or 1)
        qty = pos.get("position", 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is not None:
                if greek == "delta":
                    portfolio["Delta"] += val * qty
                else:
                    portfolio[greek.capitalize()] += val * qty * mult

    print_account_overview(app.account_values)

    for pos in app.positions_data:
        sym = pos["symbol"]
        pos["HV30"] = app.hv_data.get(sym)
        pos["ATR14"] = app.atr_data.get(sym)
        pos["IV_Rank"] = app.iv_rank_data.get(sym)
        pos["IV_Percentile"] = app.iv_rank_data.get(f"{sym}_pct")

    with open(cfg_get("POSITIONS_FILE", "positions.json"), "w", encoding="utf-8") as f:
        json.dump(app.positions_data, f, indent=2)
    print(f"\n💾 Posities opgeslagen in {cfg_get('POSITIONS_FILE', 'positions.json')}")

    base_currency_vals = {k: v for k, v in app.account_values.items() if isinstance(k, str)}
    with open(cfg_get("ACCOUNT_INFO_FILE", "account_info.json"), "w", encoding="utf-8") as f:
        json.dump(base_currency_vals, f, indent=2)
    print(f"💾 Accountinfo opgeslagen in {cfg_get('ACCOUNT_INFO_FILE', 'account_info.json')}")

    print("\n📐 Portfolio Greeks:")
    for k, v in portfolio.items():
        print(f"{k}: {round(v, 4)}")

    app.disconnect()



if __name__ == "__main__":
    main()
