import importlib
import threading
import types


def test_start_requests_requests_stock(monkeypatch):
    # Import market_client after stubs from conftest are installed
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    if not hasattr(market_client.TickTypeEnum, "LAST"):
        market_client.TickTypeEnum.LAST = 68
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "DELAYED_LAST"):
        market_client.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2
    if not hasattr(market_client.TickTypeEnum, "DELAYED_BID"):
        market_client.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(market_client.TickTypeEnum, "DELAYED_ASK"):
        market_client.TickTypeEnum.DELAYED_ASK = 4
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "DELAYED_LAST"):
        market_client.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2
    if not hasattr(market_client.TickTypeEnum, "DELAYED_BID"):
        market_client.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(market_client.TickTypeEnum, "DELAYED_ASK"):
        market_client.TickTypeEnum.DELAYED_ASK = 4

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId, tickList, snapshot, contract))
            # Simulate receiving a valid tick price to satisfy the wait
            self.tickPrice(reqId, market_client.TickTypeEnum.LAST, 10.0, None)

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:0930-1600",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)  # 2020-01-01 12:00 UTC

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    app = DummyClient("ABC")
    app.start_requests()
    assert ("type", 1) in app.calls
    req = next(call for call in app.calls if call[0] == "req")
    assert req[4].secType == "STK"
    assert req[2] == "100,101,106"
    assert req[3] is False
    assert ("cancel", req[1]) in app.calls


def test_market_open_with_timezone(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    if not hasattr(market_client.TickTypeEnum, "LAST"):
        market_client.TickTypeEnum.LAST = 68
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "DELAYED_LAST"):
        market_client.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2
    if not hasattr(market_client.TickTypeEnum, "DELAYED_BID"):
        market_client.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(market_client.TickTypeEnum, "DELAYED_ASK"):
        market_client.TickTypeEnum.DELAYED_ASK = 4

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId, tickList, snapshot, contract))
            self.tickPrice(reqId, market_client.TickTypeEnum.LAST, 10.0, None)

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:0930-1600",
                timeZoneId="America/New_York",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577890800)  # 2020-01-01 15:00 UTC -> 10:00 NY

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    app = DummyClient("ABC")
    app.start_requests()
    assert app.market_open is True


def test_start_requests_delayed_when_closed(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId, tickList, snapshot, contract))

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:CLOSED",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    # Patch fetch_volatility_metrics to avoid network access during tests
    monkeypatch.setattr(market_client, "fetch_volatility_metrics", lambda s: {})
    app = DummyClient("ABC")
    app.start_requests()
    type_calls = [t[1] for t in app.calls if t[0] == "type"]
    assert type_calls == [2]
    req = next(call for call in app.calls if call[0] == "req")
    assert req[2] == ""
    assert req[3] is True


def test_start_requests_skips_invalid_tick(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    if not hasattr(market_client.TickTypeEnum, "LAST"):
        market_client.TickTypeEnum.LAST = 68
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "DELAYED_LAST"):
        market_client.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2
    if not hasattr(market_client.TickTypeEnum, "DELAYED_BID"):
        market_client.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(market_client.TickTypeEnum, "DELAYED_ASK"):
        market_client.TickTypeEnum.DELAYED_ASK = 4

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId, contract))
            # Simulate tickPrice callback with an invalid price
            self.tickPrice(reqId, market_client.TickTypeEnum.LAST, -1, None)

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:CLOSED",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    monkeypatch.setattr(market_client, "fetch_volatility_metrics", lambda s: {})
    app = DummyClient("ABC")
    app.start_requests()
    type_calls = [t[1] for t in app.calls if t[0] == "type"]
    assert type_calls == [2]


def test_fallback_called_after_timeout(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    calls = []

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.calls = []

        def reqMarketDataType(self, data_type: int) -> None:
            self.calls.append(("type", data_type))

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.calls.append(("req", reqId))

        def cancelMktData(self, reqId: int) -> None:
            self.calls.append(("cancel", reqId))

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:CLOSED",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)

    def fake_fetch(symbol):
        calls.append(symbol)
        return {"spot_price": 5.0}

    monkeypatch.setattr(market_client, "cfg_get", lambda name, default=None: 0)
    monkeypatch.setattr(market_client, "fetch_volatility_metrics", fake_fetch)

    app = DummyClient("ABC")
    app.start_requests()

    assert calls == ["ABC"]
    assert app.spot_price == 5.0


def test_bid_ask_before_last_uses_fallback(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    if not hasattr(market_client.TickTypeEnum, "LAST"):
        market_client.TickTypeEnum.LAST = 68
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)

        def reqMarketDataType(self, data_type: int) -> None:
            pass

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            # Emit BID/ASK ticks but no LAST tick
            self.tickPrice(reqId, market_client.TickTypeEnum.BID, 9.8, None)
            self.tickPrice(reqId, market_client.TickTypeEnum.ASK, 10.2, None)

        def cancelMktData(self, reqId: int) -> None:
            pass

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:CLOSED",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)

    monkeypatch.setattr(
        market_client,
        "cfg_get",
        lambda name, default=None: 0.01 if name == "SPOT_TIMEOUT" else 0,
    )
    monkeypatch.setattr(
        market_client, "fetch_volatility_metrics", lambda s: {"spot_price": 7.5}
    )

    app = DummyClient("ABC")
    app.start_requests()

    assert app.spot_price == 7.5


def test_close_tick_sets_spot_and_skips_fallback(monkeypatch):
    market_client = importlib.import_module("tomic.api.market_client")
    MarketClient = market_client.MarketClient

    if not hasattr(market_client.TickTypeEnum, "LAST"):
        market_client.TickTypeEnum.LAST = 68
    if not hasattr(market_client.TickTypeEnum, "BID"):
        market_client.TickTypeEnum.BID = 1
    if not hasattr(market_client.TickTypeEnum, "DELAYED_LAST"):
        market_client.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(market_client.TickTypeEnum, "ASK"):
        market_client.TickTypeEnum.ASK = 2
    if not hasattr(market_client.TickTypeEnum, "DELAYED_BID"):
        market_client.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(market_client.TickTypeEnum, "DELAYED_ASK"):
        market_client.TickTypeEnum.DELAYED_ASK = 4
    if not hasattr(market_client.TickTypeEnum, "CLOSE"):
        market_client.TickTypeEnum.CLOSE = 9
    if not hasattr(market_client.TickTypeEnum, "toStr"):
        market_client.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))

    fallback = []

    class DummyClient(MarketClient):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)
            self.timer = None

        def reqMarketDataType(self, data_type: int) -> None:
            pass

        def reqMktData(self, reqId, contract, tickList, snapshot, regSnapshot, opts):
            self.timer = threading.Timer(
                0.01,
                self.tickPrice,
                args=(
                    reqId,
                    getattr(market_client.TickTypeEnum, "CLOSE", 9),
                    12.0,
                    None,
                ),
            )
            self.timer.start()

        def cancelMktData(self, reqId: int) -> None:
            pass

        def reqContractDetails(self, reqId, contract):
            details = types.SimpleNamespace(
                tradingHours="20200101:CLOSED",
                contract=types.SimpleNamespace(secType="STK"),
            )
            self.contractDetails(reqId, details)

        def reqCurrentTime(self):
            self.currentTime(1577880000)

    def fake_cfg(name, default=None):
        if name == "SPOT_TIMEOUT":
            return 0
        return default

    monkeypatch.setattr(market_client, "cfg_get", fake_cfg)
    monkeypatch.setattr(
        market_client,
        "fetch_volatility_metrics",
        lambda s: (fallback.append(s) or {}),
    )

    app = DummyClient("ABC")
    app.start_requests()
    if app.timer:
        app.timer.join()

    assert app.spot_price == 12.0
    assert fallback == []


def test_option_chain_client_events_set():
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
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
    if not hasattr(mod.TickTypeEnum, "CLOSE"):
        mod.TickTypeEnum.CLOSE = 9
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))
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


def test_spot_event_set_close_before_last(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    if not hasattr(mod.TickTypeEnum, "CLOSE"):
        mod.TickTypeEnum.CLOSE = 9
    if not hasattr(mod.TickTypeEnum, "LAST"):
        mod.TickTypeEnum.LAST = 68
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
    if not hasattr(mod.TickTypeEnum, "DELAYED_LAST"):
        mod.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(mod.TickTypeEnum, "DELAYED_BID"):
        mod.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(mod.TickTypeEnum, "DELAYED_ASK"):
        mod.TickTypeEnum.DELAYED_ASK = 4
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))

    client._spot_req_id = 1
    client.spot_price = None
    client.spot_event.clear()

    client.tickPrice(1, mod.TickTypeEnum.CLOSE, 9.0, None)
    assert client.spot_event.is_set()


def test_spot_event_set_last_before_close(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    if not hasattr(mod.TickTypeEnum, "LAST"):
        mod.TickTypeEnum.LAST = 68
    if not hasattr(mod.TickTypeEnum, "CLOSE"):
        mod.TickTypeEnum.CLOSE = 9
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
    if not hasattr(mod.TickTypeEnum, "DELAYED_LAST"):
        mod.TickTypeEnum.DELAYED_LAST = 69
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
    assert client.expected_contracts == len(client.expiries) * len(client.strikes) * 2


def test_req_secdefopt_waits_for_spot(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")

    calls = []

    def fake_callback(*a, **k):
        calls.append(1)

    def fake_reqSecDefOptParams(*a, **k):
        client.securityDefinitionOptionParameter(1, "SMART", 1, "TC", "100", [], [])

    monkeypatch.setattr(
        client, "securityDefinitionOptionParameter", fake_callback, raising=False
    )
    client.reqSecDefOptParams = fake_reqSecDefOptParams

    details = types.SimpleNamespace(
        contract=types.SimpleNamespace(
            secType="STK",
            conId=1,
            tradingClass="TC",
            primaryExchange="SMART",
        )
    )

    def set_spot():
        client.spot_price = 10.0
        client.spot_event.set()

    t = threading.Timer(0.01, set_spot)
    t.start()
    client.contractDetails(1, details)
    t.join()

    assert len(calls) == 1


def test_request_skips_without_details(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    calls = []

    def fake_reqContractDetails(reqId, contract):
        client.contract_received.set()

    monkeypatch.setattr(
        client, "reqContractDetails", fake_reqContractDetails, raising=False
    )
    monkeypatch.setattr(
        client, "reqMktData", lambda *a, **k: calls.append(a), raising=False
    )
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )

    client._request_option_data()
    assert calls == []
    assert client.invalid_contracts
    assert not client._pending_details


def test_request_reuses_known_con_id(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
    client = mod.OptionChainClient("ABC")
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    client.con_ids[("20250101", 100.0, "C")] = 555

    captured = []

    def fake_reqContractDetails(reqId, contract):
        captured.append(contract.conId)
        client.contract_received.set()

    monkeypatch.setattr(
        client, "reqContractDetails", fake_reqContractDetails, raising=False
    )
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )

    client._request_option_data()

    assert captured and captured[0] == 555


def test_request_uses_stored_multiplier(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
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

    monkeypatch.setattr(
        client, "reqContractDetails", fake_reqContractDetails, raising=False
    )
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )

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

    monkeypatch.setattr(
        client, "reqContractDetails", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(client.contract_received, "wait", lambda t=None: False)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            0
            if name in {"CONTRACT_DETAILS_TIMEOUT", "CONTRACT_DETAILS_RETRIES"}
            else default
        ),
    )

    client._request_option_data()

    assert client.invalid_contracts
    assert not client._pending_details


def test_semaphore_released_on_invalid_contract(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
    client = mod.OptionChainClient("ABC", max_concurrent_requests=1)
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    monkeypatch.setattr(
        client, "_request_contract_details", lambda c, r: False, raising=False
    )
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )

    client._request_option_data()

    assert client.invalid_contracts
    assert not client._pending_details
    assert client._detail_semaphore.acquire(blocking=False)
    client._detail_semaphore.release()


def test_concurrent_contract_request_limit(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
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

    monkeypatch.setattr(
        client, "reqContractDetails", fake_reqContractDetails, raising=False
    )
    monkeypatch.setattr(
        client,
        "_request_contract_details",
        lambda c, r: [client.reqContractDetails(r, c), True][1],
    )
    monkeypatch.setattr(client, "reqMktData", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )

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


def test_error_300_releases_semaphore(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC", max_concurrent_requests=1)
    client._pending_details[1] = mod.OptionContract("ABC", "20250101", 100.0, "C")
    client._detail_semaphore.acquire()

    client.error(1, "", 300, "Can't find EId with tickerId:1")

    assert 1 in client.invalid_contracts
    assert 1 not in client._pending_details
    assert client._detail_semaphore.acquire(blocking=False)
    client._detail_semaphore.release()


def test_all_data_event_set(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "LAST"):
        mod.TickTypeEnum.LAST = 68
    if not hasattr(mod.TickTypeEnum, "DELAYED_LAST"):
        mod.TickTypeEnum.DELAYED_LAST = 69
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
    if not hasattr(mod.TickTypeEnum, "DELAYED_BID"):
        mod.TickTypeEnum.DELAYED_BID = 3
    if not hasattr(mod.TickTypeEnum, "DELAYED_ASK"):
        mod.TickTypeEnum.DELAYED_ASK = 4

    client.expected_contracts = 2
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))
    client.market_data[1] = {"event": threading.Event()}
    client.market_data[2] = {"event": threading.Event()}

    client.tickPrice(1, mod.TickTypeEnum.BID, 1.0, None)
    client.tickPrice(1, mod.TickTypeEnum.ASK, 1.2, None)
    client.tickOptionComputation(
        1,
        0,
        None,
        0.3,
        0.1,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
    )
    assert not client.all_data_event.is_set()
    client.error(2, "", 200, "")
    assert client.all_data_event.is_set()


def test_tick_price_negative_delays_invalidation(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")

    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))

    monkeypatch.setattr(
        mod, "cfg_get", lambda n, d=None: 999 if n == "BID_ASK_TIMEOUT" else d
    )
    client.market_data[1] = {"event": threading.Event()}

    client.tickPrice(1, mod.TickTypeEnum.BID, -1, None)

    assert 1 not in client.invalid_contracts


def test_tick_price_invalidates_after_timeout(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")

    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))

    monkeypatch.setattr(
        mod, "cfg_get", lambda n, d=None: 0 if n == "BID_ASK_TIMEOUT" else d
    )
    client.market_data[1] = {"event": threading.Event()}

    client.tickPrice(1, mod.TickTypeEnum.BID, -1, None)

    assert 1 in client.invalid_contracts


def test_tick_price_close_keeps_contract_valid(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: False if n == "USE_HISTORICAL_IV_WHEN_CLOSED" else d,
    )
    client = mod.OptionChainClient("ABC")

    if not hasattr(mod.TickTypeEnum, "CLOSE"):
        mod.TickTypeEnum.CLOSE = 9
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "LAST"):
        mod.TickTypeEnum.LAST = 68
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

    client.market_data[1] = {"event": threading.Event()}

    scheduled = []
    monkeypatch.setattr(
        client, "_schedule_invalid_timer", lambda r: scheduled.append(r)
    )
    monkeypatch.setattr(
        client,
        "_cancel_invalid_timer",
        lambda r: scheduled.remove(r) if r in scheduled else None,
    )

    client.tickPrice(1, mod.TickTypeEnum.BID, -1, None)
    assert scheduled == [1]

    client.tickPrice(1, mod.TickTypeEnum.CLOSE, 2.5, None)
    assert scheduled == []
    assert client.market_data[1]["close"] == 2.5

    client.tickOptionComputation(
        1,
        0,
        None,
        0.2,
        0.1,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
    )
    assert client.market_data[1]["event"].is_set()
    assert 1 not in client.invalid_contracts


def test_option_chain_snapshot_no_volume(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
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
    if not hasattr(mod.TickTypeEnum, "CLOSE"):
        mod.TickTypeEnum.CLOSE = 9
    if not hasattr(mod.TickTypeEnum, "toStr"):
        mod.TickTypeEnum.toStr = classmethod(lambda cls, v: str(v))
    client.market_open = False
    client.trading_class = "ABC"
    client.expiries = ["20250101"]
    client.strikes = [100.0]
    client._strike_lookup = {100.0: 100.0}
    client.option_params_complete.set()

    calls = []

    def fake_reqContractDetails(reqId, contract):
        details = types.SimpleNamespace(
            contract=types.SimpleNamespace(
                secType="OPT",
                conId=reqId,
                symbol="ABC",
                lastTradeDateOrContractMonth="20250101",
                strike=100.0,
                right="C",
                exchange="SMART",
                primaryExchange="SMART",
                tradingClass="ABC",
                multiplier="100",
                currency="USD",
            )
        )
        client.contractDetails(reqId, details)

    monkeypatch.setattr(
        client,
        "_request_contract_details",
        lambda c, r: [fake_reqContractDetails(r, c), True][1],
    )
    monkeypatch.setattr(
        client, "reqContractDetails", fake_reqContractDetails, raising=False
    )

    def fake_reqMktData(reqId, contract, tickList, snapshot, regSnapshot, opts):
        calls.append((tickList, snapshot))
        client.tickPrice(reqId, mod.TickTypeEnum.BID, 1.0, None)
        client.tickPrice(reqId, mod.TickTypeEnum.ASK, 1.1, None)

    monkeypatch.setattr(client, "reqMktData", fake_reqMktData, raising=False)
    monkeypatch.setattr(
        client, "reqMarketDataType", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(mod, "cfg_get", lambda n, d=None: 0)

    client._request_option_data()

    assert calls and calls[0] == ("", True)
    rec = next(iter(client.market_data.values()))
    assert "open_interest" not in rec


def test_greeks_skipped_when_closed(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")
    if not hasattr(mod.TickTypeEnum, "BID"):
        mod.TickTypeEnum.BID = 1
    if not hasattr(mod.TickTypeEnum, "ASK"):
        mod.TickTypeEnum.ASK = 2
    client.market_open = False
    client._use_snapshot = False
    client._pending_details[1] = mod.OptionContract("ABC", "20250101", 100.0, "C")

    calls = []

    def fake_reqMktData(reqId, contract, tickList, snapshot, regSnapshot, opts):
        calls.append(tickList)

    monkeypatch.setattr(client, "reqMktData", fake_reqMktData, raising=False)
    monkeypatch.setattr(client._detail_semaphore, "release", lambda: None)
    monkeypatch.setattr(mod, "cfg_get", lambda n, d=None: True if n == "INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN" else False)

    details = types.SimpleNamespace(
        contract=types.SimpleNamespace(
            secType="OPT",
            conId=1,
            symbol="ABC",
            lastTradeDateOrContractMonth="20250101",
            strike=100.0,
            right="C",
            exchange="SMART",
            primaryExchange="SMART",
            tradingClass="ABC",
            multiplier="100",
            currency="USD",
        )
    )

    client.contractDetails(1, details)

    assert calls and calls[0] == "100,101"


def test_invalid_timer_cancel_race(monkeypatch):
    mod = importlib.import_module("tomic.api.market_client")
    client = mod.OptionChainClient("ABC")

    class DummyTimer:
        def __init__(self, interval, fn, args=None, kwargs=None):
            self.fn = fn
            self.args = args or []
            self.kwargs = kwargs or {}
            self.cancelled = False

        def start(self):
            pass

        def run(self):
            if not self.cancelled:
                self.fn(*self.args, **self.kwargs)

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(mod.threading, "Timer", DummyTimer)
    monkeypatch.setattr(mod, "cfg_get", lambda n, d=None: 0.01 if n == "BID_ASK_TIMEOUT" else d)

    events = []
    orig_inv = client._invalidate_request

    def record_inv(rid):
        events.append(rid)
        orig_inv(rid)

    monkeypatch.setattr(client, "_invalidate_request", record_inv)

    client.market_data[1] = {"event": threading.Event()}
    client._schedule_invalid_timer(1)
    timer = client._invalid_timers[1]

    start_evt = threading.Event()

    def expire():
        start_evt.wait()
        timer.run()

    def cancel():
        start_evt.wait()
        client._cancel_invalid_timer(1)

    t1 = threading.Thread(target=expire)
    t2 = threading.Thread(target=cancel)
    t1.start()
    t2.start()
    start_evt.set()
    t1.join()
    t2.join()

    assert 1 not in client._invalid_timers
    assert events in ([], [1])
