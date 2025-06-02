import importlib
import sys
import types

# Stub dependencies before importing the module
market_export_stub = types.ModuleType("tomic.api.market_export")
market_export_stub._start_app = lambda app: None  # type: ignore[attr-defined]
market_export_stub._await_market_data = (  # type: ignore[attr-defined]
    lambda app, symbol: True
)
sys.modules["tomic.api.market_export"] = market_export_stub

combined_stub = types.ModuleType("tomic.api.combined_app")


class DummyApp:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.market_data = {
            1: {
                "expiry": "20250101",
                "strike": 100.0,
                "right": "C",
                "volume": 5,
                "open_interest": 10,
            },
            2: {
                "expiry": "20250101",
                "strike": 100.0,
                "right": "P",
                "volume": 7,
                "open_interest": 20,
            },
        }
        self.invalid_contracts: set[int] = set()
        self.spot_price = 123.0
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


combined_stub.CombinedApp = DummyApp  # type: ignore[attr-defined]
sys.modules["tomic.api.combined_app"] = combined_stub

option_metrics = importlib.reload(importlib.import_module("tomic.api.option_metrics"))


def test_fetch_option_metrics_aggregates():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0)
    assert result == {"spot_price": 123.0, "volume": 12, "open_interest": 30}


def test_fetch_option_metrics_filters_call():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0, "C")
    assert result == {"spot_price": 123.0, "volume": 5, "open_interest": 10}


def test_fetch_option_metrics_filters_put():
    result = option_metrics.fetch_option_metrics("ABC", "2025-01-01", 100.0, "P")
    assert result == {"spot_price": 123.0, "volume": 7, "open_interest": 20}
