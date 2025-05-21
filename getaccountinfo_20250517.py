from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import *
from ibapi.account_summary_tags import *

import threading
import time


class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

        self.positions_data = []
        self.open_orders = []
        self.account_values = {}

    def nextValidId(self, orderId: int):
        print("✅ Verbonden. OrderId:", orderId)
        self.reqAccountSummary(9001, "All", AccountSummaryTags.AllTags)
        self.reqPositions()
        self.reqOpenOrders()

    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        self.positions_data.append({
            "symbol": contract.symbol,
            "secType": contract.secType,
            "exchange": contract.exchange,
            "position": position,
            "avgCost": avgCost
        })

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
        self.account_values[tag] = value

    def accountSummaryEnd(self, reqId: int):
        print("🔹 Accountoverzicht opgehaald.")

    def positionEnd(self):
        print("🔹 Posities opgehaald.")
        for pos in self.positions_data:
            print(pos)

    def openOrderEnd(self):
        print("🔹 Open orders opgehaald.")
        for order in self.open_orders:
            print(order)

    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        print(f"⚠️ Error {errorCode}: {errorString}")


def run_loop(app):
    app.run()


if __name__ == "__main__":
    app = IBApp()
    app.connect("127.0.0.1", 7497, clientId=1)

    api_thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
    api_thread.start()

    time.sleep(5)  # Geef tijd om alles op te halen

    print("\n📊 Account Balans:")
    for tag, value in app.account_values.items():
        print(f"{tag}: {value}")

    print("\n📈 Portfolio Posities:")
    for pos in app.positions_data:
        print(pos)

    print("\n📋 Openstaande Orders:")
    for order in app.open_orders:
        print(order)

    app.disconnect()
