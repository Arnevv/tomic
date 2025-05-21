import os
import csv
import math
import statistics
from datetime import datetime
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.common import *
from ibapi.ticktype import TickTypeEnum
import threading
import time

class IVDataCollector(EWrapper, EClient):
    invalid_contracts = set()
    def __init__(self, symbol):
        EClient.__init__(self, self)
        self.data_ready = threading.Event()
        self.historical_data = []
        self.symbol = symbol.upper()
        self.spot_price = None
        self.vix_price = None
        self.market_data_ready = threading.Event()
        self.vix_data_ready = threading.Event()
        self.expiries = []
        self.option_params_ready = threading.Event()
        self.conId = None
        self.contract_details_ready = threading.Event()

    def nextValidId(self, orderId: int):
        self.reqMarketDataType(2)
        self.request_spot_price()
        self.request_vix()

    def request_spot_price(self):
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
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
        if details.contract.symbol.upper() == self.symbol:
            self.conId = details.contract.conId
            print(f"[Step 1.5] ✅ contractId van {self.symbol} ontvangen: {self.conId}")

    def contractDetailsEnd(self, reqId: int):
        if self.conId:
            self.reqSecDefOptParams(5001, self.symbol, "", "STK", self.conId)

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId,
                                          tradingClass, multiplier, expirations, strikes):
        if self.expiries:
            return
        expiries = sorted(expirations)

        def is_third_friday(date_str):
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.weekday() == 4 and 15 <= dt.day <= 21
            except:
                return False

        regulars = [e for e in expiries if is_third_friday(e)]
        self.expiries = regulars[:3]
        print(f"📅 Geselecteerde expiries: {self.expiries}")
        print(f"📈 Spotprijs: {self.spot_price}")

        center = round(self.spot_price)
        filtered_strikes = sorted([s for s in strikes if center - 100 <= s <= center + 100 and isinstance(s, (int, float))])
        print(f"🎯 Strikes rond {center}: {filtered_strikes[:10]} ... ({len(filtered_strikes)} totaal)")
        self.strikes = filtered_strikes
        self.trading_class = tradingClass
        self.option_params_ready.set()

        self.market_data = {}
        self.req_id_counter = 6000
        for expiry in self.expiries:
            for strike in self.strikes:
                for right in ["C", "P"]:
                    contract = Contract()
                    contract.symbol = self.symbol
                    contract.secType = "OPT"
                    contract.exchange = "SMART"
                    contract.currency = "USD"
                    contract.lastTradeDateOrContractMonth = expiry
                    contract.strike = strike
                    contract.right = right
                    contract.multiplier = "100"
                    contract.tradingClass = self.trading_class

                    req_id = self.req_id_counter
                    self.req_id_counter += 1

                    self.market_data[req_id] = {
                        "expiry": expiry,
                        "strike": strike,
                        "right": right,
                        "bid": None,
                        "ask": None,
                        "delta": None,
                        "iv": None
                    }
                    self.reqMktData(req_id, contract, "", True, False, [])
        print(f"📡 Marketdata requests verzonden: {len(self.market_data)} opties")

    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        if errorCode == 200 and reqId in getattr(self, 'market_data', {}):
            self.invalid_contracts.add(reqId)
        elif errorCode not in (2104, 2106, 2158, 2176):
            print(f"⚠️ Error {reqId} ({errorCode}): {errorString}")

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        if reqId in getattr(self, 'market_data', {}):
            if impliedVol is not None:
                self.market_data[reqId]['iv'] = impliedVol
            if delta is not None:
                self.market_data[reqId]['delta'] = delta

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib: TickAttrib):
        if reqId == 1001 and tickType == TickTypeEnum.LAST:
            self.spot_price = round(price, 2)
            self.cancelMktData(1001)
            self.market_data_ready.set()
        elif reqId == 1002 and tickType == TickTypeEnum.LAST:
            self.vix_price = round(price, 2)
            self.cancelMktData(1002)
            self.vix_data_ready.set()

        elif reqId in getattr(self, 'market_data', {}):
            if tickType == 1:
                self.market_data[reqId]['bid'] = price
            elif tickType == 2:
                self.market_data[reqId]['ask'] = price
            elif tickType == 24:
                self.market_data[reqId]['delta'] = price
            elif tickType == 13:
                self.market_data[reqId]['iv'] = price

            completed = sum(
                1 for d in self.market_data.values()
                if d['bid'] is not None and d['ask'] is not None and d['delta'] is not None and d['iv'] is not None
            )
            total = len(self.market_data)
            if completed % 10 == 0 and completed > 0:
                print(f"🔄 Gevulde opties: {completed}/{total}")

    def historicalData(self, reqId: int, bar):
        self.historical_data.append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        self.data_ready.set()

    def get_historical_data(self):
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"

        queryTime = (datetime.now().astimezone().astimezone()).strftime("%Y%m%d-%H:%M:%S")
        self.reqHistoricalData(2000, contract, queryTime, "30 D", "1 day", "TRADES", 0, 1, False, [])

    def calculate_hv30(self):
        closes = [bar.close for bar in self.historical_data if hasattr(bar, 'close')]
        log_returns = [math.log(closes[i+1]/closes[i]) for i in range(len(closes)-1)]
        std_dev = statistics.stdev(log_returns)
        return round(std_dev * math.sqrt(252) * 100, 2)

    def calculate_atr14(self):
        trs = []
        for i in range(1, len(self.historical_data)):
            high = self.historical_data[i].high
            low = self.historical_data[i].low
            prev_close = self.historical_data[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        atr14 = statistics.mean(trs[-14:])
        return round(atr14, 2)

def run():
    symbol = input("📈 Voer het symbool in waarvoor je data wilt ophalen (bijv. SPY): ").strip().upper()
    if not symbol:
        print("❌ Geen geldig symbool ingevoerd.")
        return

    app = IVDataCollector(symbol)
    app.connect("127.0.0.1", 7497, clientId=100)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    app.market_data_ready.wait(timeout=10)
    if not app.spot_price:
        print("❌ Spotprijs ophalen mislukt.")
        app.disconnect()
        return

    app.vix_data_ready.wait(timeout=10)
    if not app.vix_price:
        print("❌ VIX ophalen mislukt.")
        app.disconnect()
        return

    app.option_params_ready.wait(timeout=10)
    if not app.expiries:
        print("❌ Geen expiries ontvangen.")
        app.disconnect()
        return

    app.data_ready.clear()
    app.get_historical_data()
    app.data_ready.wait(timeout=15)
    if not app.historical_data:
        print("❌ Historische data ophalen mislukt.")
        app.disconnect()
        return

    hv30 = app.calculate_hv30()
    atr14 = app.calculate_atr14()

    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"other_data_{symbol}_{timestamp}.csv"
    filepath = os.path.join(export_dir, filename)

    headers = ["Symbol", "SpotPrice", "HV_30", "ATR_14", "VIX"]
    values = [symbol, app.spot_price, hv30, atr14, app.vix_price]

    with open(filepath, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerow(values)

    print(f"✅ CSV opgeslagen als: {filepath}")
    print("⏳ Wachten op marketdata (10 seconden)...")
    time.sleep(10)

    def count_incomplete():
        return sum(
            1 for k, d in app.market_data.items()
            if k not in app.invalid_contracts and (
                d['bid'] is None or d['ask'] is None or
                d['delta'] is None or d['iv'] is None
            )
        )

    total_options = len([k for k in app.market_data if k not in app.invalid_contracts])
    incomplete = count_incomplete()
    waited = 10
    max_wait = 60
    interval = 5
    while incomplete > 0 and waited < max_wait:
        print(f"⏳ {incomplete} van {total_options} opties niet compleet na {waited} seconden. Wachten...")
        time.sleep(interval)
        waited += interval
        incomplete = count_incomplete()
    if incomplete > 0:
        print(f"⚠️ {incomplete} opties blijven incompleet na {waited} seconden. Berekeningen gaan verder met beschikbare data.")
    else:
        print(f"✅ Alle opties volledig na {waited} seconden.")

    valid_options = [
        d for k, d in app.market_data.items()
        if k not in app.invalid_contracts
        and d['delta'] is not None and d['iv'] is not None
    ]

    expiry = app.expiries[0]  # eerstvolgende maandserie
    print(f"📆 Skew berekend op expiry: {expiry}")

    calls = [d for d in valid_options if d['right'] == 'C' and d['expiry'] == expiry]
    puts = [d for d in valid_options if d['right'] == 'P' and d['expiry'] == expiry]

    def interpolate_iv_at_delta(options, target_delta):
        """Zoekt twee opties waarvan de deltas het doel omringen en
        interpoleert de IV lineair op de doel-delta.

        Geeft de geïnterpoleerde IV en een benaderde strike terug.

        De IV die we voor de skew-berekening gebruiken is dus niet direct van
        een enkele optie, maar via delta-interpolatie afgeleid."""
        if not options:
            return None, None
        sorted_opts = sorted(options, key=lambda x: x['delta'])
        for i in range(len(sorted_opts) - 1):
            d1, d2 = sorted_opts[i]['delta'], sorted_opts[i + 1]['delta']
            if d1 is None or d2 is None:
                continue
            if (d1 <= target_delta <= d2) or (d2 <= target_delta <= d1):
                iv1, iv2 = sorted_opts[i]['iv'], sorted_opts[i + 1]['iv']
                k1, k2 = sorted_opts[i]['strike'], sorted_opts[i + 1]['strike']
                if iv1 is None or iv2 is None:
                    continue
                if d1 == d2:
                    weight = 0
                else:
                    weight = (target_delta - d1) / (d2 - d1)
                iv = iv1 + weight * (iv2 - iv1)
                strike = k1 + weight * (k2 - k1) if k1 is not None and k2 is not None else None
                return iv, strike
        nearest = min(sorted_opts, key=lambda x: abs(x['delta'] - target_delta))
        return nearest['iv'], nearest.get('strike')

    call_iv, call_strike = interpolate_iv_at_delta(calls, 0.25)
    put_iv, put_strike = interpolate_iv_at_delta(puts, -0.25)

    if call_iv is not None and put_iv is not None:
        skew = round(call_iv - put_iv, 2)
        print(
            f"📐 Skew (25d CALL - 25d PUT): {call_iv:.4f} (strike ~ {call_strike}) - "
            f"{put_iv:.4f} (strike ~ {put_strike}) = {skew}"
        )
    else:
        print("⚠️ Onvoldoende data voor skew-berekening.")

    app.disconnect()
    time.sleep(1)

if __name__ == "__main__":
    run()
