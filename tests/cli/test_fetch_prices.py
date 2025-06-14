import importlib
import types


def test_fetch_prices_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices")

    # Stub database functions
    conn = types.SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(mod, "init_db", lambda path: conn)

    captured = []
    monkeypatch.setattr(mod, "save_price_history", lambda c, recs: captured.append(recs))

    # Fake IB connection
    class FakeBar:
        def __init__(self):
            self.date = "20240101"
            self.close = 1.23
            self.volume = 100

    class FakeApp:
        def __init__(self):
            self.next_valid_id = 1
            self.disconnected = False

        def reqHistoricalData(self, *a, **k):
            self.historicalData(1, FakeBar())
            self.historicalDataEnd(1, "", "")

        def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(mod, "connect_ib", lambda: FakeApp())

    called = []
    monkeypatch.setattr(mod, "compute_volstats_main", lambda syms: called.append(syms))

    mod.main(["ABC"])
    assert captured
    assert called and called[0] == ["ABC"]
