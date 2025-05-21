from ibapi.order import Order
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
        self.spot_price = None
        self.spot_price_received = False
        self.expiries = []
        self.trading_class = None
        self.lock = Lock()

    def nextValidId(self, orderId: int):
        self.ready = True
        print(f"[Step 1] ✅ API ready with ID: {orderId}")

    def error(self, reqId, errorCode, errorString):
        if errorCode not in (2104, 2106, 2158):
            print(f"⚠️ Error {reqId}: {errorCode} - {errorString}")

    def tickPrice(self, reqId, tickType, price, attrib):
        if reqId == 999 and tickType == TickTypeEnum.LAST:
            self.spot_price = price
            self.spot_price_received = True
            print(f"[Step 2] ✅ SPY spotprijs ontvangen: {price}")

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId,
                                          tradingClass, multiplier, expirations, strikes):
        def is_third_friday(date_str):
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.weekday() == 4 and 15 <= dt.day <= 21
            except:
                return False

        self.expiries = sorted(e for e in expirations if is_third_friday(e))[:1]
        self.trading_class = tradingClass
        self.option_params_ready = True
        print(f"[Step 3] ✅ Eerste reguliere expiratie: {self.expiries}")

def run_loop(app):
    app.run()

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

def create_market_order(action, quantity):
    order = Order()
    order.action = action
    order.orderType = "MKT"
    order.totalQuantity = quantity
    order.transmit = True
    return order

def place_atm_call_order():
    print("=== START ATM CALL ORDER ===")
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

    app.reqSecDefOptParams(1000, "SPY", "", "STK", 756733)

    while not app.option_params_ready:
        time.sleep(0.2)

    if not app.expiries:
        print("❌ Geen expiraties gevonden.")
        return

    expiry = app.expiries[0]
    strike = round(app.spot_price)
    right = "C"
    trading_class = app.trading_class

    option_contract = create_option_contract("SPY", expiry, strike, right, trading_class)
    order = create_market_order("BUY", 1)

    print(f"📤 Order wordt geplaatst: SPY {expiry} {strike}C Market Buy 1x")
    app.placeOrder(app.reqId, option_contract, order)
    time.sleep(3)
    app.disconnect()
    print("=== ORDER GEPLAATST ===")