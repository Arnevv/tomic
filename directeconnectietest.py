import time
import logging
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import TickerId

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class SpotPriceApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.spot_price = None
        self.symbol = "SPY"
        self.connected_flag = False

    def nextValidId(self, orderId: int):
        logging.info("Verbonden met TWS (orderId = %s)", orderId)
        self.connected_flag = True
        self.request_market_data()

    def request_market_data(self):
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"

        logging.info("Vraag spotprijs aan voor %s...", self.symbol)
        self.reqMktData(1001, contract, "", False, False, [])

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib):
        if tickType == 4:  # Last price
            self.spot_price = price
            logging.info("Spotprijs %s = %.2f USD", self.symbol, price)
            self.disconnect()

    def error(self, reqId, errorCode, errorString):
        logging.warning("Error %s: %s", errorCode, errorString)

    def connectionClosed(self):
        logging.info("Verbinding gesloten.")

def main():
    app = SpotPriceApp()
    app.connect("127.0.0.1", 7497, clientId=123)

    while not app.connected_flag:
        time.sleep(0.1)

    try:
        app.run()
    except KeyboardInterrupt:
        logging.info("Handmatig gestopt.")
        app.disconnect()

if __name__ == "__main__":
    main()
