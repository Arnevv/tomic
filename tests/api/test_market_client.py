import importlib
import types


def test_start_requests_requests_stock(monkeypatch):
    # Import market_client after stubs from conftest are installed
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId, contract))

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    app = DummyClient("ABC")
    app.spot_price = 1.0
    app.start_requests()
    assert ("type", 2) in app.calls
    req = next(call for call in app.calls if call[0] == "req")
    assert req[2].secType == "STK"
    assert ("cancel", req[1]) in app.calls
