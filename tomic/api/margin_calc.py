import threading
from ibapi.order import Order
from ibapi.contract import Contract

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.config import get as cfg_get


def _create_option_contract(symbol: str, expiry: str, strike: float, right: str) -> Contract:
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
    c.tradingClass = symbol
    return c


class MarginApp(BaseIBApp):
    """Minimal IB app to request what-if orders for margin."""

    def __init__(self):
        super().__init__()
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
    client_id: int | None = None,
) -> float | None:
    """Return required initial margin for the given option legs."""
    expiry = expiry.replace("-", "")
    host = host or cfg_get("IB_HOST", "127.0.0.1")
    port = int(port or cfg_get("IB_PORT", 7497))
    cid = client_id if client_id is not None else int(cfg_get("IB_CLIENT_ID", 100))
    app = MarginApp()
    try:
        client = connect_ib(client_id=cid, host=host, port=port)
        client.disconnect()
    except Exception:
        return None

    app.connect(host, port, cid)
    thread = threading.Thread(target=app.run)
    thread.start()
    app.reqIds(1)
    if not app.event.wait(timeout=5):
        app.disconnect()
        return None

    total = 0.0
    for leg in legs:
        contract = _create_option_contract(symbol, expiry, leg["strike"], leg["type"])
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
