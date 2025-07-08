import importlib
import json
from datetime import date, datetime


def _setup_paths(monkeypatch, tmp_path, mod):
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    meta_file = tmp_path / "meta.json"
    meta_file.write_text("{}")

    cfg = lambda name, default=None: (
        str(price_dir)
        if name == "PRICE_HISTORY_DIR"
        else str(meta_file)
        if name == "PRICE_META_FILE"
        else default
    )
    monkeypatch.setattr(mod, "cfg_get", cfg)
    import tomic.helpers.price_meta as price_meta
    monkeypatch.setattr(price_meta, "cfg_get", cfg)
    return price_dir, meta_file


def test_intraday_overwrite(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_intraday_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    price_dir, meta_file = _setup_paths(monkeypatch, tmp_path, mod)

    # preset previous day record
    (price_dir / "ABC.json").write_text(
        json.dumps([{"symbol": "ABC", "date": "2024-01-01", "close": 1.0}])
    )

    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2024, 1, 2)

    times = [
        datetime(2024, 1, 2, 15, 0),
        datetime(2024, 1, 2, 16, 0),
    ]

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            dt = times.pop(0)
            if tz is not None:
                return dt.replace(tzinfo=tz)
            return dt

    monkeypatch.setattr(mod, "date", FakeDate)
    monkeypatch.setattr(mod, "datetime", FakeDT)

    responses = [
        {"results": [{"t": 1704198000000, "c": 10.0, "v": 100}]},
        {"results": [{"t": 1704201600000, "c": 11.0, "v": 150}]},
    ]

    class FakeClient:
        def connect(self):
            pass

        def disconnect(self):
            pass

        def _request(self, path, params):
            return responses.pop(0)

    monkeypatch.setattr(mod, "PolygonClient", lambda: FakeClient())
    monkeypatch.setattr(mod, "sleep", lambda s: None)

    # first fetch
    mod.main(["ABC"])
    data = json.loads((price_dir / "ABC.json").read_text())
    assert len(data) == 2
    assert data[-1]["close"] == 10.0
    meta1 = json.loads(meta_file.read_text())
    ts1 = meta1.get("ABC")
    assert ts1

    # second fetch should overwrite today's record
    mod.main(["ABC"])
    data2 = json.loads((price_dir / "ABC.json").read_text())
    assert len(data2) == 2
    assert data2[-1]["close"] == 11.0
    meta2 = json.loads(meta_file.read_text())
    assert meta2.get("ABC") != ts1
