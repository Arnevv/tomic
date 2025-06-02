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
sys.modules["tomic.api.market_utils"] = market_utils_stub

# Stub BaseIBApp
base_stub = types.ModuleType("tomic.api.base_client")


class DummyApp:
    def __init__(self, *args, **kwargs):
        self.open_interest = None
        self.open_interest_event = types.SimpleNamespace(
            wait=lambda timeout: True, set=lambda: None
        )
        self.req_id = None
        self.disconnected = False

    def reqMktData(self, req_id, contract, tick_list, snapshot, regulatory, opts):
        self.open_interest = 42
        self.open_interest_event.set()

    def disconnect(self) -> None:
        self.disconnected = True


base_stub.BaseIBApp = DummyApp
sys.modules["tomic.api.base_client"] = base_stub

open_interest = importlib.reload(importlib.import_module("tomic.api.open_interest"))


def test_fetch_open_interest_value():
    assert open_interest.fetch_open_interest("ABC", "2025-01-01", 100.0, "C") == 42


def test_fetch_open_interest_none_if_no_event():
    def no_set(self, req_id, contract, tick_list, snapshot, regulatory, opts):
        self.open_interest = 0

    DummyApp.reqMktData = no_set
    DummyApp.open_interest_event = types.SimpleNamespace(
        wait=lambda timeout: False, set=lambda: None
    )
    assert open_interest.fetch_open_interest("ABC", "2025-01-01", 100.0, "C") is None
