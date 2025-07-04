import importlib
from datetime import datetime, date
from types import SimpleNamespace


def test_fetch_prices_polygon_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        mod,
        "_request_bars",
        lambda client, sym: [
            {
                "symbol": sym,
                "date": "2024-01-01",
                "close": 1.23,
                "volume": 100,
                "atr": None,
            }
        ],
    )

    class FakeClient:
        def connect(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(mod, "PolygonClient", lambda: FakeClient())

    captured = []
    monkeypatch.setattr(mod, "_merge_price_data", lambda f, recs: (captured.extend(recs), len(recs))[1])

    called = []
    monkeypatch.setattr(mod, "compute_volstats_polygon_main", lambda syms: called.append(syms))

    monkeypatch.setattr(mod, "sleep", lambda s: None)

    mod.main(["ABC"])
    assert captured
    assert captured[0]["close"] == 1.23
    assert called and called[0] == ["ABC"]


def test_fetch_prices_polygon_no_data(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(mod, "_request_bars", lambda client, sym: [])

    class FakeClient:
        def connect(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(mod, "PolygonClient", lambda: FakeClient())

    captured = []
    monkeypatch.setattr(mod, "_merge_price_data", lambda f, recs: (captured.extend(recs), 0)[1])

    monkeypatch.setattr(mod, "compute_volstats_polygon_main", lambda syms: None)

    monkeypatch.setattr(mod, "sleep", lambda s: None)

    mod.main(["XYZ"])
    assert not captured


def test_latest_trading_day_before_close(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 7, 2, 10, 0, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    day = mod.latest_trading_day()
    assert day == date(2025, 7, 1)


def test_latest_trading_day_after_close(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 7, 2, 21, 0, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    day = mod.latest_trading_day()
    assert day == date(2025, 7, 2)


def test_request_bars_skips_on_403(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    monkeypatch.setattr(mod, "latest_trading_day", lambda: date(2024, 1, 2))
    monkeypatch.setattr(mod, "_load_latest_close", lambda s: (None, None))

    class FakeHTTPError(Exception):
        def __init__(self, status):
            self.response = SimpleNamespace(status_code=status)

    class FakeClient:
        def _request(self, path, params):
            raise FakeHTTPError(403)

    records = list(mod._request_bars(FakeClient(), "ABC"))
    assert records == []
