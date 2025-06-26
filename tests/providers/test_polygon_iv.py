import importlib
import json
from datetime import datetime
from types import SimpleNamespace


def test_fetch_polygon_iv30d(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "ABC.json").write_text(json.dumps([{"date": "2024-01-01", "close": 100.0}]))

    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            "key"
            if name == "POLYGON_API_KEY"
            else str(price_dir)
            if name == "PRICE_HISTORY_DIR"
            else default
        ),
    )

    sample = {
        "results": {
            "options": [
                {"expiration_date": "2024-01-28", "strike_price": 100.5, "implied_volatility": 0.2},
                {"expiration_date": "2024-01-30", "strike_price": 99.8, "implied_volatility": 0.22},
                {"expiration_date": "2024-02-20", "strike_price": 100.0, "implied_volatility": 0.5},
            ]
        }
    }

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return sample

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: FakeResp(), raising=False)

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    iv = mod.fetch_polygon_iv30d("ABC")
    assert abs(iv - (0.2 + 0.22) / 2) < 1e-6
