import importlib
import json
from datetime import datetime
from types import SimpleNamespace


def test_fetch_polygon_iv30d(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "ABC.json").write_text(
        json.dumps([
            {"date": "2023-12-31", "close": 99.0},
            {"date": "2024-01-01", "close": 100.0},
        ])
    )

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
                {
                    "expiration_date": "2024-01-28",
                    "strike_price": 102.5,
                    "implied_volatility": 0.2,
                    "delta": 0.3,
                    "option_type": "call",
                },
                {
                    "expiration_date": "2024-01-30",
                    "strike_price": 97.5,
                    "implied_volatility": 0.22,
                    "delta": -0.3,
                    "option_type": "put",
                },
                {
                    "expiration_date": "2024-02-20",
                    "strike_price": 100.0,
                    "implied_volatility": 0.5,
                    "delta": 0.1,
                    "option_type": "call",
                },
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
            # Current date without close entry to ensure last known close is used
            return datetime(2024, 1, 3)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    metrics = mod.fetch_polygon_iv30d("ABC")
    assert metrics["atm_iv"] == (0.2 + 0.22) / 2
    assert metrics["skew"] is not None
