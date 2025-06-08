import importlib
import sys
import types

# Stub dependencies before importing the module
client_stub = types.ModuleType("tomic.api.market_client")
client_stub.start_app = lambda app: None
client_stub.await_market_data = lambda app, symbol: True
sys.modules["tomic.api.market_client"] = client_stub


class DummyApp:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.market_data = {
            1: {
                "expiry": "20250101",
                "strike": 100.0,
                "right": "C",
                "volume": 5,
            },
            2: {
                "expiry": "20250101",
                "strike": 100.0,
                "right": "P",
                "volume": 7,
            },
        }
        self.invalid_contracts: set[int] = set()
        self.spot_price = 123.0
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


client_stub.MarketClient = DummyApp  # type: ignore[attr-defined]
sys.modules["tomic.api.market_client"] = client_stub

option_metrics = importlib.reload(importlib.import_module("tomic.api.option_metrics"))
sys.modules.pop("tomic.api.market_client", None)


def test_fetch_option_metrics_aggregates():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0)
    assert result.spot_price == 123.0
    assert result.volume == 12


def test_fetch_option_metrics_filters_call():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0, "C")
    assert result.spot_price == 123.0
    assert result.volume == 5


def test_fetch_option_metrics_filters_put():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0, "P")
    assert result.spot_price == 123.0
    assert result.volume == 7
