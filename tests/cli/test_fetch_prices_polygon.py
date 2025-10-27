import importlib
import json
from datetime import datetime, date
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from tomic.helpers.price_utils import ClosePriceSnapshot
import tomic.polygon_prices as pp


def test_fetch_prices_polygon_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.fetch_prices_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    calls: list[list[str] | None] = []
    monkeypatch.setattr(
        mod,
        "fetch_polygon_price_history",
        lambda symbols=None, *, run_volstats=True: calls.append(symbols) or [],
    )

    mod.main(["ABC"])
    assert calls == [["ABC"]]


def test_fetch_polygon_price_history_stores_data(monkeypatch, tmp_path):
    svc = importlib.import_module("tomic.cli.services.price_history_polygon")

    class FakeRateLimiter:
        def __init__(self, *_args, **_kwargs):
            pass

        def wait(self) -> None:
            pass

        def record(self) -> None:
            pass

        def time_until_ready(self) -> float:
            return 0.0

    monkeypatch.setattr(svc, "RateLimiter", FakeRateLimiter)

    base_dir = tmp_path / "prices"
    base_dir.mkdir()
    meta_file = tmp_path / "meta.json"
    meta_file.write_text("{}")

    def cfg_stub(name, default=None):
        if name == "PRICE_HISTORY_DIR":
            return str(base_dir)
        if name == "PRICE_META_FILE":
            return str(meta_file)
        if name == "DEFAULT_SYMBOLS":
            return []
        if name == "POLYGON_SLEEP_BETWEEN":
            return 0
        if name == "POLYGON_REQUESTS_PER_MINUTE":
            return 5
        return default

    monkeypatch.setattr(svc, "cfg_get", cfg_stub)

    class FakeClient:
        def connect(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(svc, "PolygonClient", lambda: FakeClient())

    records = [
        {
            "symbol": "ABC",
            "date": "2024-01-01",
            "close": 1.23,
            "volume": 100,
            "atr": None,
        }
    ]
    monkeypatch.setattr(svc, "request_bars", lambda client, sym: (records, True))

    captured: list[list[dict]] = []

    def merge_stub(file, recs):
        captured.append(recs)
        return len(recs)

    monkeypatch.setattr(svc, "merge_price_data", merge_stub)

    meta_store: dict[str, str] = {}
    monkeypatch.setattr(svc, "load_price_meta", lambda: meta_store.copy())
    monkeypatch.setattr(svc, "save_price_meta", lambda m: meta_store.update(m))

    monkeypatch.setattr(svc, "sleep", lambda s: None)

    volstats_calls: list[list[str]] = []
    monkeypatch.setattr(
        svc,
        "compute_polygon_volatility_stats",
        lambda syms: volstats_calls.append(syms),
    )

    fixed_now = datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("America/New_York"))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(svc, "datetime", FakeDatetime)

    processed = svc.fetch_polygon_price_history(["ABC"])

    assert processed == ["ABC"]
    assert captured and captured[0][0]["close"] == 1.23
    assert volstats_calls == [["ABC"]]
    assert meta_store["day_ABC"].startswith("2024-01-01T12:00:00")


def test_fetch_polygon_price_history_no_data(monkeypatch, tmp_path):
    svc = importlib.import_module("tomic.cli.services.price_history_polygon")

    class FakeRateLimiter:
        def __init__(self, *_args, **_kwargs):
            pass

        def wait(self) -> None:
            pass

        def record(self) -> None:
            pass

        def time_until_ready(self) -> float:
            return 0.0

    monkeypatch.setattr(svc, "RateLimiter", FakeRateLimiter)

    base_dir = tmp_path / "prices"
    base_dir.mkdir()
    meta_file = tmp_path / "meta.json"
    meta_file.write_text("{}")

    def cfg_stub(name, default=None):
        if name == "PRICE_HISTORY_DIR":
            return str(base_dir)
        if name == "PRICE_META_FILE":
            return str(meta_file)
        if name == "DEFAULT_SYMBOLS":
            return []
        if name == "POLYGON_SLEEP_BETWEEN":
            return 0
        if name == "POLYGON_REQUESTS_PER_MINUTE":
            return 5
        return default

    monkeypatch.setattr(svc, "cfg_get", cfg_stub)

    class FakeClient:
        def connect(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(svc, "PolygonClient", lambda: FakeClient())

    monkeypatch.setattr(svc, "request_bars", lambda client, sym: ([], True))

    captured: list[list[dict]] = []
    monkeypatch.setattr(
        svc,
        "merge_price_data",
        lambda f, recs: (captured.extend(recs), 0)[1],
    )

    meta_store: dict[str, str] = {}
    monkeypatch.setattr(svc, "load_price_meta", lambda: meta_store.copy())
    monkeypatch.setattr(svc, "save_price_meta", lambda m: meta_store.update(m))

    monkeypatch.setattr(svc, "sleep", lambda s: None)
    monkeypatch.setattr(svc, "compute_polygon_volatility_stats", lambda syms: None)

    processed = svc.fetch_polygon_price_history(["XYZ"])

    assert processed == []
    assert not captured
    assert meta_store == {}


def test_latest_trading_day_before_close(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 7, 2, 10, 0, tzinfo=tz)

    monkeypatch.setattr(pp, "datetime", FakeDT)
    monkeypatch.setattr(pp, "_US_MARKET_HOLIDAYS", set(), raising=False)

    day = pp.latest_trading_day()
    assert day == date(2025, 7, 1)


def test_latest_trading_day_after_close(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 7, 2, 21, 0, tzinfo=tz)

    monkeypatch.setattr(pp, "datetime", FakeDT)
    monkeypatch.setattr(pp, "_US_MARKET_HOLIDAYS", set(), raising=False)

    day = pp.latest_trading_day()
    assert day == date(2025, 7, 1)


def test_latest_trading_day_counts_columbus_day(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 10, 14, 10, 0, tzinfo=tz)

    monkeypatch.setattr(pp, "datetime", FakeDT)
    monkeypatch.setattr(
        pp,
        "holidays",
        SimpleNamespace(
            NYSE=lambda: set(),
            US=lambda: {date(2025, 10, 13)},
        ),
    )
    monkeypatch.setattr(pp, "_US_MARKET_HOLIDAYS", None, raising=False)

    day = pp.latest_trading_day()
    assert day == date(2025, 10, 13)


def test_next_trading_day_skips_market_holidays(monkeypatch):
    monkeypatch.setattr(pp, "_US_MARKET_HOLIDAYS", None, raising=False)
    monkeypatch.setattr(pp, "_us_market_holidays", lambda: {date(2025, 1, 1)})

    next_day = pp._next_trading_day(date(2024, 12, 31))
    assert next_day == date(2025, 1, 2)


def test_request_bars_skips_on_403(monkeypatch):
    monkeypatch.setattr(pp, "latest_trading_day", lambda: date(2024, 1, 2))
    monkeypatch.setattr(pp, "_load_latest_close", lambda s: ClosePriceSnapshot(None, None))

    class FakeHTTPError(Exception):
        def __init__(self, status):
            self.response = SimpleNamespace(status_code=status)

    class FakeClient:
        def _request(self, path, params):
            raise FakeHTTPError(403)

    records, requested = pp.request_bars(FakeClient(), "ABC")
    assert records == []
    assert requested is True


def test_incomplete_day_triggers_refetch(monkeypatch, tmp_path):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "ABC.json").write_text(json.dumps([{ "date": "2024-01-02", "close": 1.0 }]))

    meta_file = tmp_path / "meta.json"
    meta_file.write_text(json.dumps({"day_ABC": "2024-01-02T15:00:00-05:00"}))

    cfg_lambda = lambda name, default=None: (
        str(price_dir)
        if name == "PRICE_HISTORY_DIR"
        else (str(meta_file) if name == "PRICE_META_FILE" else default)
    )

    monkeypatch.setattr(pp, "cfg_get", cfg_lambda)
    import tomic.utils as utils
    monkeypatch.setattr(utils, "cfg_get", cfg_lambda)
    import tomic.helpers.price_meta as price_meta
    monkeypatch.setattr(price_meta, "cfg_get", cfg_lambda)

    monkeypatch.setattr(pp, "latest_trading_day", lambda: date(2024, 1, 2))

    called = []

    class FakeClient:
        def _request(self, path, params):
            called.append(path)
            return {"results": []}

    records, requested = pp.request_bars(FakeClient(), "ABC")
    assert called, "refetch should occur when last fetch before close"
    assert requested is True


def test_no_new_workday_skips_sleep(monkeypatch, tmp_path):
    svc = importlib.import_module("tomic.cli.services.price_history_polygon")

    class FakeRateLimiter:
        def __init__(self, *_args, **_kwargs):
            pass

        def wait(self) -> None:
            pass

        def record(self) -> None:
            pass

        def time_until_ready(self) -> float:
            return 0.0

    monkeypatch.setattr(svc, "RateLimiter", FakeRateLimiter)

    base_dir = tmp_path / "prices"
    base_dir.mkdir()
    meta_file = tmp_path / "meta.json"
    meta_file.write_text("{}")

    def cfg_stub(name, default=None):
        if name == "PRICE_HISTORY_DIR":
            return str(base_dir)
        if name == "PRICE_META_FILE":
            return str(meta_file)
        if name == "DEFAULT_SYMBOLS":
            return []
        if name == "POLYGON_SLEEP_BETWEEN":
            return 0
        if name == "POLYGON_REQUESTS_PER_MINUTE":
            return 1
        return default

    monkeypatch.setattr(svc, "cfg_get", cfg_stub)

    class FakeClient:
        def connect(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(svc, "PolygonClient", lambda: FakeClient())

    monkeypatch.setattr(svc, "request_bars", lambda client, sym: ([], False))

    sleep_calls: list[float] = []
    monkeypatch.setattr(svc, "sleep", lambda s: sleep_calls.append(s))

    meta_store: dict[str, str] = {}
    monkeypatch.setattr(svc, "load_price_meta", lambda: meta_store.copy())
    monkeypatch.setattr(svc, "save_price_meta", lambda m: meta_store.update(m))

    monkeypatch.setattr(svc, "compute_polygon_volatility_stats", lambda syms: None)

    processed = svc.fetch_polygon_price_history(["AAA", "BBB"])

    assert processed == []
    assert sleep_calls == []
    assert meta_store == {}
