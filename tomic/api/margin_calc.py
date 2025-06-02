from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.order import Order
import threading

from .market_utils import create_option_contract, start_app
from tomic.config import get as cfg_get


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


def calculate_trade_margin(
    symbol: str,
    expiry: str,
    legs: list,
    host: str | None = None,
    port: int | None = None,
    client_id: int = 900,
) -> float | None:
    """Return required initial margin for the given option legs."""
    expiry = expiry.replace("-", "")
    host = host or cfg_get("IB_HOST", "127.0.0.1")
    port = int(port or cfg_get("IB_PORT", 7497))
    app = MarginApp()
    start_app(app, host=host, port=port, client_id=client_id)

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
        order.firmQuoteOnly = False  # disable firm quote check for what-if orders
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
