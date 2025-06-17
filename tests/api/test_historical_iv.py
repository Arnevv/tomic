import importlib
import types


def test_fetch_historical_iv(monkeypatch):
    mod = importlib.import_module("tomic.api.historical_iv")

    contract_stub = types.SimpleNamespace()

    class FakeBar:
        close = 0.25

    class FakeApp:
        def __init__(self):
            self.historicalData = None
            self.historicalDataEnd = None
            self.disconnected = False

        def reqHistoricalData(self, *a, **k):
            self.historicalData(1, FakeBar())
            self.historicalDataEnd(1, "", "")

        def disconnect(self):
            self.disconnected = True

        def error(self, *a, **k):
            pass

    monkeypatch.setattr(mod, "connect_ib", lambda: FakeApp())

    result = mod.fetch_historical_iv(contract_stub)
    assert result == 0.25
