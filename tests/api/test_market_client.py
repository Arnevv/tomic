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


def test_option_chain_client_events_set():
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.reqSecDefOptParams = lambda *a, **k: None
    client.reqMktData = lambda *a, **k: None

    if not hasattr(mod.TickTypeEnum, "LAST"):
        mod.TickTypeEnum.LAST = 68
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "DELAYED_LAST"):
        mod.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
    if not hasattr(mod.TickTypeEnum, "DELAYED_BID"):
        mod.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(mod.TickTypeEnum, "DELAYED_ASK"):
        mod.TickTypeEnum.DELAYED_ASK = 4
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))

    client._spot_req_id = 1
    client.spot_event.clear()
    client.tickPrice(1, mod.TickTypeEnum.LAST, 10.0, None)
    assert client.spot_event.is_set()

    details = types.SimpleNamespace(
        contract=types.SimpleNamespace(
            secType="STK",
            conId=2,
            tradingClass="ABC",
            primaryExchange="SMART",
        )
    )
    client.details_event.clear()
    client.contractDetails(2, details)
    assert client.details_event.is_set()
    assert client.trading_class == "ABC"
    assert client.primary_exchange == "SMART"

    req_id = client._next_id()
    client._pending_details[req_id] = mod.OptionContract("ABC", "20250101", 100.0, "C")
    opt_details = types.SimpleNamespace(
        contract=types.SimpleNamespace(
            secType="OPT",
            conId=123,
            symbol="ABC",
            lastTradeDateOrContractMonth="20250101",
            strike=100.0,
            right="C",
            exchange="SMART",
            primaryExchange="SMART",
            currency="USD",
            tradingClass="ABC",
            multiplier="100",
        )
    )
    client.contract_received.clear()
    client.contractDetails(req_id, opt_details)
    assert client.contract_received.is_set()

    client.market_event.clear()
    client.tickPrice(req_id, mod.TickTypeEnum.BID, 1.2, None)
    assert client.market_event.is_set()


def test_request_skips_without_details(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    calls = []

    def fake_reqContractDetails(reqId, contract):
        client.contract_received.set()

    monkeypatch.setattr(client, "reqContractDetails", fake_reqContractDetails, raising=False)
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: calls.append(a), raising=False)

    client._request_option_data()
    assert calls == []
    assert client.invalid_contracts
    assert not client._pending_details
