from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
import threading


def create_option_contract(symbol: str, expiry: str, strike: float, right: str) -> Contract:
    """Return an option contract object for the given parameters."""
    c = Contract()
    c.symbol = symbol
    c.secType = "OPT"
    c.exchange = "SMART"
    c.currency = "USD"
    c.lastTradeDateOrContractMonth = expiry
    c.strike = strike
    c.right = right[0].upper()
    c.multiplier = "100"
    c.tradingClass = symbol
    return c


class MarginApp(EWrapper, EClient):
    """Minimal IB app to request what-if orders for margin."""

    def __init__(self):
        EClient.__init__(self, self)
        self.margin = None
        self.order_id = None
        self.event = threading.Event()

    def nextValidId(self, orderId: int):
        self.order_id = orderId
        self.event.set()

    def openOrder(self, orderId, contract, order, orderState):
        if order.whatIf:
            try:
                self.margin = float(orderState.initMarginChange)
            except Exception:
                self.margin = None
            self.event.set()


def calculate_trade_margin(symbol: str, expiry: str, legs: list,
                           host: str = "127.0.0.1", port: int = 7497,
                           client_id: int = 900) -> float | None:
    """Return required initial margin for the given option legs."""
    expiry = expiry.replace("-", "")
    app = MarginApp()
    app.connect(host, port, clientId=client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.event.wait(timeout=5):
        app.disconnect()
        return None

    total = 0.0
    for leg in legs:
        contract = create_option_contract(symbol, expiry, leg["strike"], leg["type"])
        order = Order()
        order.action = leg["action"]
        order.totalQuantity = leg["qty"]
        order.orderType = "MKT"
        # Explicitly disable deprecated TWS attributes to avoid order rejection
        # when submitting what-if orders for margin calculations.
        # See https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc for details.
        order.eTradeOnly = False
        order.whatIf = True
        app.margin = None
        app.event.clear()
        app.placeOrder(app.order_id, contract, order)
        app.event.wait(timeout=5)
        if app.margin is not None:
            total += app.margin
        app.order_id += 1

    app.disconnect()
    return round(total, 2) if total else None
