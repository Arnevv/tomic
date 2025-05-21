from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.ticktype import TickTypeEnum
from threading import Thread, Lock
import time
import csv
from datetime import datetime
import os

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.ready = False
        self.option_params_ready = False
        self.contract_details_counter = 0
        self.expected_contracts = 0
        self.market_data = {}
        self.greeks_fields = ["implied_vol", "delta", "theta", "vega", "gamma"]
        self.lock = Lock()
        self.expiries = []
        self.trading_class = None
        self.strikes = []
        self.spot_price = None
        self.spot_price_received = False
        self.requested_contracts = set()
        self.valid_contracts = set()
        self.market_data_req_ids = []
        self.unique_contract_details_keys = set()
        self.market_data_keys = set()
        self.req_id_counter = 1
        self.invalid_contracts = set()
        self.invalid_contract_keys = set()
        self.received_contract_details = 0

    def get_next_req_id(self):
        self.req_id_counter += 1
        return self.req_id_counter

    def nextValidId(self, orderId: int):
        self.ready = True
        print(f"[Step 1] ✅ API ready with ID: {orderId}")

    def error(self, reqId, errorCode, errorString):
        if errorCode == 200:
            if reqId in self.market_data:
                d = self.market_data[reqId]
                key = (d['expiry'], d['strike'], d['right'])
                self.invalid_contract_keys.add(key)
                self.invalid_contracts.add(reqId)
        if errorCode not in (2104, 2106, 2158):
            print(f"⚠️ Error {reqId}: {errorCode} - {errorString}")
            if reqId in self.requested_contracts:
                self.requested_contracts.discard(reqId)

    def tickPrice(self, reqId, tickType, price, attrib):
        with self.lock:
            if reqId == 999 and tickType == TickTypeEnum.LAST:
                self.spot_price = price
                self.spot_price_received = True
                print(f"[Step 2] ✅ SPY spotprijs ontvangen: {price}")
            elif reqId in self.market_data:
                if tickType == 14: self.market_data[reqId]['implied_vol'] = price
                elif tickType == 1: self.market_data[reqId]['bid'] = price
                elif tickType == 2: self.market_data[reqId]['ask'] = price
                elif tickType == 24: self.market_data[reqId]['delta'] = price
                elif tickType == 25: self.market_data[reqId]['gamma'] = price
                elif tickType == 26: self.market_data[reqId]['vega'] = price
                elif tickType == 27: self.market_data[reqId]['theta'] = price

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol,
                              delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        with self.lock:
            if reqId in self.market_data:
                self.market_data[reqId]['implied_vol'] = impliedVol
                self.market_data[reqId]['delta'] = delta
                self.market_data[reqId]['gamma'] = gamma
                self.market_data[reqId]['vega'] = vega
                self.market_data[reqId]['theta'] = theta

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId,
                                          tradingClass, multiplier, expirations, strikes):
        def is_third_friday(date_str):
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.weekday() == 4 and 15 <= dt.day <= 21
            except:
                return False

        regulars = sorted(e for e in expirations if is_third_friday(e))[:3]
        self.expiries = regulars
        self.trading_class = tradingClass
        center = round(self.spot_price)
        self.strikes = sorted([s for s in strikes if center - 60 <= s <= center + 60 and s % 1 == 0])
        self.option_params_ready = True
        print(f"[Step 3] ✅ Drie reguliere expiries: {self.expiries}")

    def contractDetails(self, reqId, details: ContractDetails):
        c = details.contract
        key = (c.lastTradeDateOrContractMonth, c.strike, c.right)
        if key in self.unique_contract_details_keys:
            return
        self.unique_contract_details_keys.add(key)
        self.market_data[reqId] = {
            'expiry': c.lastTradeDateOrContractMonth,
            'strike': c.strike,
            'right': c.right,
            'bid': None, 'ask': None,
            'implied_vol': None, 'delta': None, 'gamma': None, 'vega': None, 'theta': None
        }
        self.valid_contracts.add(reqId)
        self.received_contract_details += 1

    def contractDetailsEnd(self, reqId):
        if self.received_contract_details == len(self.requested_contracts):
            self.request_market_data()

    def request_market_data(self):
        batch = []
        for old_req_id in self.valid_contracts:
            data = self.market_data.get(old_req_id, {})
            if not data.get("expiry") or not data.get("strike") or not data.get("right"):
                continue
            key = (data['expiry'], data['strike'], data['right'])
            if key in self.market_data_keys:
                continue
            self.market_data_keys.add(key)
            contract = create_option_contract("SPY", data['expiry'], data['strike'], data['right'], self.trading_class)
            mkt_reqId = self.get_next_req_id()
            self.reqMktData(mkt_reqId, contract, "", True, False, [])
            self.market_data[mkt_reqId] = data
            self.market_data_req_ids.append(mkt_reqId)
            batch.append(mkt_reqId)
            if len(batch) >= 50:
                time.sleep(2)
                batch = []

        print("[Step 5] ✅ Market data requests initiated")

    def cancel_all_market_data(self):
        for reqId in self.market_data_req_ids:
            self.cancelMktData(reqId)
        print("[Step 9] 😕 Alle market data requests geannuleerd")

def create_underlying():
    c = Contract()
    c.symbol = "SPY"
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

def run_loop(app):
    app.run()

def main():
    print("=== START SCRIPT ===")
    app = IBApp()
    app.connect("127.0.0.1", 7497, clientId=123)
    Thread(target=run_loop, args=(app,), daemon=True).start()

    while not app.ready:
        time.sleep(0.1)

    app.reqMarketDataType(2)
    spy_contract = create_underlying()
    app.reqMktData(999, spy_contract, "", False, False, [])

    timeout = time.time() + 10
    while not app.spot_price_received and time.time() < timeout:
        time.sleep(0.1)

    if not app.spot_price_received:
        print("❌ Spotprijs niet ontvangen binnen timeout.")
        return

    app.cancelMktData(999)
    app.reqSecDefOptParams(1000, "SPY", "", "STK", 756733)
    while not app.option_params_ready:
        time.sleep(0.2)

    if not app.strikes:
        print("⚠️ No strikes found in range.")
        return

    for expiry in app.expiries:
        req_id = 2000
        app.valid_contracts.clear()
        app.requested_contracts.clear()
        app.market_data_keys.clear()
        app.received_contract_details = 0

        for strike in app.strikes:
            for right in ["C", "P"]:
                contract = create_option_contract("SPY", expiry, strike, right, app.trading_class)
                app.reqContractDetails(req_id, contract)
                app.requested_contracts.add(req_id)
                time.sleep(0.05)
                req_id += 1

        timeout = time.time() + 30
        while any(
            d.get("bid") is None and d.get("ask") is None and d.get("implied_vol") is None
            for d in app.market_data.values()
        ) and time.time() < timeout:
            print("[Wachten] 📉 Nog geen volledige data voor sommige regels...")
            time.sleep(0.5)

        print("[Wait] Laatste 15 seconden voor eventuele vertraagde data...")
        time.sleep(15)

        complete = sum(1 for d in app.market_data.values() if d["bid"] is not None and d["ask"] is not None)
        print(f"[Debug] ✅ Aantal volledig gevulde regels: {complete} van {len(app.market_data)}")

        retries = 2
        for attempt in range(retries):
            incomplete = [k for k, d in app.market_data.items() if k not in app.invalid_contracts
                          if d.get("bid") is None and d.get("ask") is None and d.get("implied_vol") is None]
            if not incomplete:
                break
            print(f"[Retry] 🔁 Poging {attempt + 1} voor {len(incomplete)} incomplete regels...")
            for req_id in incomplete:
                d = app.market_data[req_id]
                key = (d['expiry'], d['strike'], d['right'])
                if key in app.invalid_contract_keys:
                    continue
                contract = create_option_contract("SPY", d['expiry'], d['strike'], d['right'], app.trading_class)
                new_id = app.get_next_req_id()
                app.reqMktData(new_id, contract, "", True, False, [])
                app.market_data[new_id] = d
                app.market_data_req_ids.append(new_id)
            time.sleep(10)

    print(f"[Summary] ❌ {len(app.invalid_contracts)} contracten gaven error 200")

    headers = ["Expiry", "Type", "Strike", "Bid", "Ask", "IV", "Delta", "Gamma", "Vega", "Theta"]
    output_file = os.getenv("OPTIONCHAIN_OUTPUT", "option_chain_output.csv")
    with open(output_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        for data in app.market_data.values():
            writer.writerow([
                data.get("expiry", ""), data.get("right", ""), data.get("strike", ""),
                data.get("bid", ""), data.get("ask", ""), data.get("implied_vol", ""),
                data.get("delta", ""), data.get("gamma", ""), data.get("vega", ""), data.get("theta", "")
            ])

    print(f"[Step 8] 🗓 CSV opgeslagen als: {output_file}")
    app.cancel_all_market_data()
    app.disconnect()
    print("=== DONE ===")

if __name__ == "__main__":
    main()
