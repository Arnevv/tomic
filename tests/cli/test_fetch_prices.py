import importlib


def test_fetch_prices_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices")

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append(rec))

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


def test_fetch_prices_no_data(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices")

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append(rec))

    class FakeApp:
        def __init__(self):
            self.next_valid_id = 1
            self.disconnected = False

        def reqHistoricalData(self, *a, **k):
            self.historicalDataEnd(1, "", "")

        def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(mod, "connect_ib", lambda: FakeApp())
    monkeypatch.setattr(mod, "compute_volstats_main", lambda syms: None)

    mod.main(["XYZ"])
    assert not captured
