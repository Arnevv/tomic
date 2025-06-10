import importlib
import types
import threading


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
    client.reqMarketDataType = lambda *a, **k: None

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
    assert client.con_ids[("20250101", 100.0, "C")] == 123

    client.market_event.clear()
    client.tickPrice(req_id, mod.TickTypeEnum.BID, 1.2, None)
    assert client.market_event.is_set()


def test_security_def_option_parameter_records_multiplier():
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.spot_price = 100.0
    client.securityDefinitionOptionParameter(
        1,
        "SMART",
        123,
        "OPTCLS",
        "25",
        ["20250101"],
        [100.0],
    )
    assert client.multiplier == "25"


def test_request_skips_without_details(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 101.0}
    client.option_params_complete.set()

    calls = []

    def fake_reqContractDetails(reqId, contract):
        client.contract_received.set()

    monkeypatch.setattr(client, "reqContractDetails", fake_reqContractDetails, raising=False)
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: calls.append(a), raising=False)
    monkeypatch.setattr(client, "reqMarketDataType", lambda *a, **k: None, raising=False)

    client._request_option_data()
    assert calls == []
    assert client.invalid_contracts
    assert not client._pending_details


def test_request_reuses_known_con_id(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 101.0}
    client.option_params_complete.set()

    client.con_ids[("20250101", 100.0, "C")] = 555

    captured = []

    def fake_reqContractDetails(reqId, contract):
        captured.append(contract.conId)
        client.contract_received.set()

    monkeypatch.setattr(client, "reqContractDetails", fake_reqContractDetails, raising=False)
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client, "reqMarketDataType", lambda *a, **k: None, raising=False)

    client._request_option_data()

    assert captured and captured[0] == 555


def test_request_uses_stored_multiplier(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.spot_price = 100.0
    client.securityDefinitionOptionParameter(
        1,
        "SMART",
        123,
        "OPTCLS",
        "75",
        ["20250101"],
        [100.0],
    )
    client.option_params_complete.set()

    captured = []

    def fake_reqContractDetails(reqId, contract):
        captured.append(contract.multiplier)
        client.contract_received.set()

    monkeypatch.setattr(client, "reqContractDetails", fake_reqContractDetails, raising=False)
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client, "reqMarketDataType", lambda *a, **k: None, raising=False)

    client._request_option_data()

    assert captured and captured[0] == "75"


def test_request_contract_details_timeout(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    monkeypatch.setattr(client, "reqContractDetails", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client.contract_received, "wait", lambda t=None: False)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: 0 if name in {"CONTRACT_DETAILS_TIMEOUT", "CONTRACT_DETAILS_RETRIES"} else default,
    )

    client._request_option_data()

    assert client.invalid_contracts
    assert not client._pending_details


def test_concurrent_contract_request_limit(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    max_req = 2
    client = mod.OptionChainClient("ABC", max_concurrent_requests=max_req)
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [1.0, 2.0, 3.0, 4.0]
    client._strike_lookup = {s: s for s in client.strikes}
    client.option_params_complete.set()

    active = 0
    max_seen = 0
    timers = []

    def fake_reqContractDetails(reqId, contract):
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)

        def finish():
            client.contractDetailsEnd(reqId)

        t = threading.Timer(0.001, finish)
        timers.append(t)
        t.start()

    monkeypatch.setattr(client, "reqContractDetails", fake_reqContractDetails, raising=False)
    monkeypatch.setattr(client, "_request_contract_details", lambda c, r: [client.reqContractDetails(r, c), True][1])
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client, "reqMarketDataType", lambda *a, **k: None, raising=False)

    original_end = client.contractDetailsEnd

    def end_wrapper(reqId):
        nonlocal active
        original_end(reqId)
        active -= 1

    monkeypatch.setattr(client, "contractDetailsEnd", end_wrapper)

    client._request_option_data()

    for t in timers:
        t.join()

    assert max_seen <= max_req

