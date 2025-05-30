from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.ticktype import TickTypeEnum
from ibapi.common import TickerId
import threading
import time
import csv
import os
import math
import statistics
from datetime import datetime, timezone
import logging
from tomic.analysis.get_iv_rank import fetch_iv_metrics
import pandas as pd
from tomic.logging import setup_logging


class CombinedApp(EWrapper, EClient):
    def __init__(self, symbol):
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

    def nextValidId(self, orderId: int):
        self.reqMarketDataType(2)
        self.request_spot_price()
        self.request_vix()
        self.ready_event.set()

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

    def contractDetails(self, reqId: int, details: ContractDetails):
        c = details.contract
        if c.secType == "STK" and c.symbol.upper() == self.symbol:
            self.conId = details.contract.conId

    def contractDetailsEnd(self, reqId: int):
        self.contract_details_event.set()

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId,
                                          tradingClass, multiplier, expirations,
                                          strikes):
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
            s for s in strikes
            if center - 100 <= s <= center + 100 and isinstance(s, (int, float))
        ]
        self.strikes = sorted(filtered_strikes)
        self.trading_class = tradingClass
        self.option_params_event.set()
        self.request_option_market_data()

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

    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        if errorCode == 200 and reqId in self.market_data:
            self.invalid_contracts.add(reqId)
        elif errorCode not in (2104, 2106, 2158, 2176):
            logging.error("⚠️ Error %s (%s): %s", reqId, errorCode, errorString)

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
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

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol,
                              delta, optPrice, pvDividend, gamma, vega, theta,
                              undPrice):
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

    def historicalData(self, reqId: int, bar):
        self.historical_data.append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        self.historical_event.set()

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

    def calculate_hv30(self):
        closes = [bar.close for bar in self.historical_data if hasattr(bar, "close")]
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
        atr14 = statistics.mean(trs[-14:])
        return round(atr14, 2)

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


def create_underlying(symbol):
    c = Contract()
    c.symbol = symbol
    c.secType = "STK"
    c.exchange = "SMART"
    c.primaryExchange = "ARCA"
    c.currency = "USD"
    return c


def create_option_contract(symbol, expiry, strike, right, trading_class):
    c = Contract()
    c.symbol = symbol
    c.secType = "OPT"
    c.exchange = "SMART"
    c.primaryExchange = "SMART"
    c.currency = "USD"
    c.lastTradeDateOrContractMonth = expiry
    c.strike = strike
    c.right = right
    c.multiplier = "100"
    c.tradingClass = trading_class
    return c


def run(symbol):
    symbol = symbol.upper()
    if not symbol:
        logging.error("❌ Geen geldig symbool ingevoerd.")
        return

    app = CombinedApp(symbol)
    app.connect("127.0.0.1", 7497, clientId=200)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.spot_price_event.wait(timeout=10):
        logging.error("❌ Spotprijs ophalen mislukt.")
        app.disconnect()
        return

    if not app.contract_details_event.wait(timeout=10):
        logging.error("❌ Geen contractdetails ontvangen.")
        app.disconnect()
        return

    if not app.conId:
        logging.error("❌ Geen conId ontvangen.")
        app.disconnect()
        return

    app.reqSecDefOptParams(1201, symbol, "", "STK", app.conId)
    if not app.option_params_event.wait(timeout=10):
        logging.error("❌ Geen expiries ontvangen.")
        app.disconnect()
        return

    app.historical_event.clear()
    app.get_historical_data()
    if not app.historical_event.wait(timeout=15):
        logging.error("❌ Historische data ophalen mislukt.")
        app.disconnect()
        return

    hv30 = app.calculate_hv30()
    atr14 = app.calculate_atr14()

    try:
        iv_data = fetch_iv_metrics(symbol)
        iv_rank = iv_data.get("iv_rank")
        implied_volatility = iv_data.get("implied_volatility")
        iv_percentile = iv_data.get("iv_percentile")
    except Exception as exc:
        logging.error("⚠️ IV metrics ophalen mislukt: %s", exc)
        iv_rank = None
        implied_volatility = None
        iv_percentile = None

    if not app.vix_event.wait(timeout=10):
        logging.error("❌ VIX ophalen mislukt.")
        app.disconnect()
        return

    logging.info("⏳ Wachten op marketdata (10 seconden)...")
    time.sleep(10)

    total_options = len([k for k in app.market_data if k not in app.invalid_contracts])
    incomplete = app.count_incomplete()
    waited = 10
    max_wait = 60
    interval = 5
    while incomplete > 0 and waited < max_wait:
        logging.info(
            "⏳ %s van %s opties niet compleet na %s seconden. Wachten...",
            incomplete,
            total_options,
            waited,
        )
        time.sleep(interval)
        waited += interval
        incomplete = app.count_incomplete()

    if incomplete > 0:
        logging.warning(
            "⚠️ %s opties blijven incompleet na %s seconden. Berekeningen gaan verder met beschikbare data.",
            incomplete,
            waited,
        )
    else:
        logging.info("✅ Alle opties volledig na %s seconden.", waited)

    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    chain_file = os.path.join(export_dir, f"option_chain_{symbol}_{timestamp}.csv")
    headers_chain = [
        "Expiry",
        "Type",
        "Strike",
        "Bid",
        "Ask",
        "IV",
        "Delta",
        "Gamma",
        "Vega",
        "Theta",
    ]
    with open(chain_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers_chain)
        for data in app.market_data.values():
            writer.writerow(
                [
                    data.get("expiry"),
                    data.get("right"),
                    data.get("strike"),
                    data.get("bid"),
                    data.get("ask"),
                    round(data.get("iv"), 3) if data.get("iv") is not None else None,
                    round(data.get("delta"), 3) if data.get("delta") is not None else None,
                    round(data.get("gamma"), 3) if data.get("gamma") is not None else None,
                    round(data.get("vega"), 3) if data.get("vega") is not None else None,
                    round(data.get("theta"), 3) if data.get("theta") is not None else None,
                ]
            )

    logging.info("✅ Optieketen opgeslagen in: %s", chain_file)

    valid_options = [
        d
        for k, d in app.market_data.items()
        if k not in app.invalid_contracts and d.get("delta") is not None and d.get("iv") is not None
    ]

    expiry = app.expiries[0]
    logging.info("📆 Skew berekend op expiry: %s", expiry)

    calls = [d for d in valid_options if d["right"] == "C" and d["expiry"] == expiry]
    puts = [d for d in valid_options if d["right"] == "P" and d["expiry"] == expiry]

    def interpolate_iv_at_delta(options, target_delta):
        if not options:
            return None, None
        sorted_opts = sorted(options, key=lambda x: x["delta"])
        for i in range(len(sorted_opts) - 1):
            d1, d2 = sorted_opts[i]["delta"], sorted_opts[i + 1]["delta"]
            if d1 is None or d2 is None:
                continue
            if (d1 <= target_delta <= d2) or (d2 <= target_delta <= d1):
                iv1, iv2 = sorted_opts[i]["iv"], sorted_opts[i + 1]["iv"]
                k1, k2 = sorted_opts[i]["strike"], sorted_opts[i + 1]["strike"]
                if iv1 is None or iv2 is None:
                    continue
                weight = 0 if d1 == d2 else (target_delta - d1) / (d2 - d1)
                iv = iv1 + weight * (iv2 - iv1)
                strike = k1 + weight * (k2 - k1) if k1 is not None and k2 is not None else None
                return iv, strike
        nearest = min(sorted_opts, key=lambda x: abs(x["delta"] - target_delta))
        return nearest["iv"], nearest.get("strike")

    atm_call_ivs = []
    for exp in app.expiries:
        exp_calls = [d for d in valid_options if d["right"] == "C" and d["expiry"] == exp]
        iv, strike = interpolate_iv_at_delta(exp_calls, 0.50)
        atm_call_ivs.append(iv)
        if iv is not None:
            logging.info("📈 ATM IV %s: %.4f (strike ~ %s)", exp, iv, strike)
        else:
            logging.warning("⚠️ Geen ATM IV beschikbaar voor %s", exp)

    call_iv, _ = interpolate_iv_at_delta(calls, 0.25)
    put_iv, _ = interpolate_iv_at_delta(puts, -0.25)

    if call_iv is not None and put_iv is not None:
        skew = round((call_iv - put_iv) * 100, 2)
        logging.info(
            "📐 Skew (25d CALL - 25d PUT): %.4f - %.4f = %.2f",
            call_iv,
            put_iv,
            skew,
        )
    else:
        logging.warning("⚠️ Onvoldoende data voor skew-berekening.")
        skew = None

    m1 = atm_call_ivs[0] if len(atm_call_ivs) > 0 else None
    m2 = atm_call_ivs[1] if len(atm_call_ivs) > 1 else None
    m3 = atm_call_ivs[2] if len(atm_call_ivs) > 2 else None

    term_m1_m2 = (
        None if m1 is None or m2 is None else round((m2 - m1) * 100, 2)
    )
    term_m1_m3 = (
        None if m1 is None or m3 is None else round((m3 - m1) * 100, 2)
    )

    logging.info("📊 Term m1->m2: %s", term_m1_m2 if term_m1_m2 is not None else "n.v.t.")
    logging.info("📊 Term m1->m3: %s", term_m1_m3 if term_m1_m3 is not None else "n.v.t.")

    metrics_file = os.path.join(export_dir, f"other_data_{symbol}_{timestamp}.csv")
    headers_metrics = [
        "Symbol",
        "SpotPrice",
        "HV_30",
        "ATR_14",
        "VIX",
        "Skew",
        "Term_M1_M2",
        "Term_M1_M3",
        "IV_Rank",
        "Implied_Volatility",
        "IV_Percentile",
    ]
    values_metrics = [
        symbol,
        app.spot_price,
        hv30,
        atr14,
        app.vix_price,
        skew,
        term_m1_m2,
        term_m1_m3,
        iv_rank,
        implied_volatility,
        iv_percentile,
    ]

    with open(metrics_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers_metrics)
        writer.writerow(values_metrics)

    logging.info("✅ CSV opgeslagen als: %s", metrics_file)

    app.disconnect()
    time.sleep(1)
    df_metrics = pd.DataFrame([values_metrics], columns=headers_metrics)
    return df_metrics


def export_combined_csv(data_per_market, output_dir):
    """Combine individual market DataFrames and export to a single CSV."""
    combined_df = pd.concat(data_per_market, ignore_index=True)
    output_path = os.path.join(output_dir, "Overzicht_Marktkenmerken.csv")
    combined_df.to_csv(output_path, index=False)
    logging.info("%d markten verwerkt. CSV geëxporteerd.", len(data_per_market))


if __name__ == "__main__":
    setup_logging()
    symbols = [
        "AAPL",
        "ASML",
        "CRM",
        "DIA",
        "EWG",
        "EWJ",
        "EWZ",
        "FEZ",
        "FXI",
        "GLD",
        "INDA",
        "NVDA",
        "QQQ",
        "RUT",
        "SPY",
        "TSLA",
        "VIX",
        "XLE",
        "XLF",
        "XLV"
    ]
    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    data_frames = []
    for sym in symbols:
        logging.info("🔄 Ophalen voor %s...", sym)
        df = run(sym)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)
