import importlib
import sys
import types

# Stub market_utils.start_app to trigger immediate market data request
market_utils_stub = types.ModuleType("tomic.api.market_utils")


def dummy_start_app(app):
    # simulate connection by invoking nextValidId
    app.nextValidId(1)


market_utils_stub.start_app = dummy_start_app
market_utils_stub.create_option_contract = lambda *args, **kwargs: None
market_utils_stub.round_strike = lambda x: x
sys.modules["tomic.api.market_utils"] = market_utils_stub

# Stub BaseIBApp
base_stub = types.ModuleType("tomic.api.base_client")


class DummyApp:
    called_market_data_types = []

    def __init__(self, *args, **kwargs):
        self.open_interest = None
        self.open_interest_event = types.SimpleNamespace(
            wait=lambda timeout: True, set=lambda: None
        )
        self.req_id = None
        self.disconnected = False

    def reqMktData(self, req_id, contract, tick_list, snapshot, regulatory, opts):
        assert tick_list == "100,101"

        # Simulate server response via tickGeneric
        self.tickGeneric(req_id, 101, 42)

    def reqMarketDataType(self, data_type):
        DummyApp.called_market_data_types.append(data_type)

    def disconnect(self) -> None:
        self.disconnected = True


base_stub.BaseIBApp = DummyApp
sys.modules["tomic.api.base_client"] = base_stub

open_interest = importlib.reload(importlib.import_module("tomic.api.open_interest"))


def test_fetch_open_interest_value():
    DummyApp.called_market_data_types.clear()
    assert open_interest.fetch_open_interest("ABC", "2025-01-01", 100.0, "C") == 42
    assert DummyApp.called_market_data_types == [2, 3]


def test_fetch_open_interest_via_tickprice():
    class AltDummyApp(DummyApp):
        def reqMktData(self, req_id, contract, tick_list, snapshot, regulatory, opts):
            self.tickPrice(req_id, 86, 99.0, None)

    base_stub.BaseIBApp = AltDummyApp
    sys.modules["tomic.api.market_utils"] = market_utils_stub
    importlib.reload(open_interest)
    assert open_interest.fetch_open_interest("XYZ", "2025-01-01", 100.0, "C") == 99


def test_fetch_open_interest_none_if_no_event():
    base_stub.BaseIBApp = DummyApp
    sys.modules["tomic.api.market_utils"] = market_utils_stub
    importlib.reload(open_interest)

    def no_set(self, req_id, contract, tick_list, snapshot, regulatory, opts):
        pass

    DummyApp.reqMktData = no_set
    # Avoid long waits by using a zero timeout
    original_timeout = open_interest.WAIT_TIMEOUT
    open_interest.WAIT_TIMEOUT = 0
    DummyApp.called_market_data_types.clear()
    assert open_interest.fetch_open_interest("ABC", "2025-01-01", 100.0, "C") is None
    open_interest.WAIT_TIMEOUT = original_timeout
