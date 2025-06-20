import importlib
import types


def test_fetch_historical_iv(monkeypatch):
    mod = importlib.import_module("tomic.api.historical_iv")

    contract_stub = types.SimpleNamespace()

    class FakeBar:
        close = 0.25

    class FakeClose:
        close = 1.0

    class FakeApp:
        def __init__(self):
            self.historicalData = None
            self.historicalDataEnd = None
            self.disconnected = False

        def reqHistoricalData(self, reqId, contract, *a):
            if reqId % 2:
                self.historicalData(reqId, FakeBar())
            else:
                self.historicalData(reqId, FakeClose())
            self.historicalDataEnd(reqId, "", "")

        def disconnect(self):
            self.disconnected = True

        def error(self, *a, **k):
            pass

    monkeypatch.setattr(mod, "connect_ib", lambda: FakeApp())

    result = mod.fetch_historical_iv(contract_stub)
    assert result == 0.25

    fake_app = FakeApp()
    res = mod.fetch_historical_option_data({1: contract_stub}, app=fake_app)
    assert res[1]["iv"] == 0.25
    assert res[1]["close"] == 1.0
