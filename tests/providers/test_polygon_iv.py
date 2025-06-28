import importlib
import json
from datetime import datetime
from types import SimpleNamespace


def test_fetch_polygon_iv30d(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "ABC.json").write_text(
        json.dumps(
            [
                {"date": "2023-12-31", "close": 99.0},
                {"date": "2024-01-01", "close": 100.0},
            ]
        )
    )

    iv_dir = tmp_path / "iv_debug"
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            "key"
            if name == "POLYGON_API_KEY"
            else (
                str(price_dir)
                if name == "PRICE_HISTORY_DIR"
                else str(iv_dir) if name == "IV_DEBUG_DIR" else default
            )
        ),
    )

    exp1 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-01-19",
                    "strike_price": 100.0,
                    "implied_volatility": 0.2,
                    "delta": 0.5,
                    "option_type": "call",
                },
                {
                    "expiration_date": "2024-01-19",
                    "strike_price": 105.0,
                    "implied_volatility": 0.21,
                    "delta": 0.25,
                    "option_type": "call",
                },
                {
                    "expiration_date": "2024-01-19",
                    "strike_price": 90.0,
                    "implied_volatility": 0.24,
                    "delta": -0.24,
                    "option_type": "put",
                },
            ]
        }
    }
    exp2 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-02-16",
                    "strike_price": 100.0,
                    "implied_volatility": 0.19,
                    "delta": 0.5,
                    "option_type": "call",
                }
            ]
        }
    }
    exp3 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-03-15",
                    "strike_price": 100.0,
                    "implied_volatility": 0.18,
                    "delta": 0.5,
                    "option_type": "call",
                }
            ]
        }
    }

    def fake_get(url, params=None, timeout=10):
        exp = params.get("expiration_date") if params else None
        resp = SimpleNamespace(status_code=200)
        resp.raise_for_status = lambda: None
        if exp == "2024-01-19":
            resp.json = lambda: exp1
        elif exp == "2024-02-16":
            resp.json = lambda: exp2
        elif exp == "2024-03-15":
            resp.json = lambda: exp3
        else:
            resp.json = lambda: {"results": {"options": []}}
        return resp

    monkeypatch.setattr(mod.requests, "get", fake_get, raising=False)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            # Current date without close entry to ensure last known close is used
            return datetime(2024, 1, 3)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    metrics = mod.fetch_polygon_iv30d("ABC")
    assert metrics["atm_iv"] == 0.2
    assert metrics["term_m1_m2"] == 1.0
    assert metrics["term_m1_m3"] == 2.0
    assert metrics["skew"] == 3.0
    assert (iv_dir / "ABC.log").exists()


def test_fetch_polygon_iv30d_fallback(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "ABC.json").write_text(
        json.dumps(
            [
                {"date": "2023-12-31", "close": 99.0},
                {"date": "2024-01-01", "close": 100.0},
            ]
        )
    )

    iv_dir = tmp_path / "iv_debug"
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            "key"
            if name == "POLYGON_API_KEY"
            else (
                str(price_dir)
                if name == "PRICE_HISTORY_DIR"
                else str(iv_dir) if name == "IV_DEBUG_DIR" else default
            )
        ),
    )

    exp1 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-01-19",
                    "strike_price": 100.0,
                    "implied_volatility": 0.2,
                    "option_type": "call",
                    "delta": None,
                }
            ]
        }
    }
    exp2 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-02-16",
                    "strike_price": 100.0,
                    "implied_volatility": 0.19,
                    "delta": 0.5,
                    "option_type": "call",
                }
            ]
        }
    }
    exp3 = {
        "results": {
            "options": [
                {
                    "expiration_date": "2024-03-15",
                    "strike_price": 100.0,
                    "implied_volatility": 0.18,
                    "delta": 0.5,
                    "option_type": "call",
                }
            ]
        }
    }

    def fake_get(url, params=None, timeout=10):
        exp = params.get("expiration_date") if params else None
        resp = SimpleNamespace(status_code=200)
        resp.raise_for_status = lambda: None
        if exp == "2024-01-19":
            resp.json = lambda: exp1
        elif exp == "2024-02-16":
            resp.json = lambda: exp2
        elif exp == "2024-03-15":
            resp.json = lambda: exp3
        else:
            resp.json = lambda: {"results": {"options": []}}
        return resp

    monkeypatch.setattr(mod.requests, "get", fake_get, raising=False)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 3)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    metrics = mod.fetch_polygon_iv30d("ABC")
    assert metrics["atm_iv"] == 0.2
    assert metrics["term_m1_m2"] == 1.0
    assert metrics["term_m1_m3"] == 2.0
    assert metrics["skew"] is None
    assert (iv_dir / "ABC.log").exists()


def test_extract_skew_greeks_none():
    mod = importlib.import_module("tomic.providers.polygon_iv")
    options = [
        {
            "strike_price": 100.0,
            "implied_volatility": 0.2,
            "delta": 0.5,
            "option_type": "call",
            "greeks": None,
        },
        {
            "strike_price": 105.0,
            "implied_volatility": 0.21,
            "delta": 0.25,
            "option_type": "call",
            "greeks": None,
        },
        {
            "strike_price": 90.0,
            "implied_volatility": 0.24,
            "delta": -0.24,
            "option_type": "put",
            "greeks": None,
        },
    ]
    atm, call, put = mod.IVExtractor.extract_skew(options, 100.0)
    assert atm == 0.2
    assert call == 0.21
    assert put == 0.24


def test_extract_skew_delta_fallback():
    mod = importlib.import_module("tomic.providers.polygon_iv")
    options = [
        {
            "strike_price": 100.0,
            "implied_volatility": 0.2,
            "delta": None,
            "option_type": "call",
            "greeks": {"delta": 0.5},
        },
        {
            "strike_price": 105.0,
            "implied_volatility": 0.21,
            "delta": None,
            "option_type": "call",
            "greeks": {"delta": 0.25},
        },
        {
            "strike_price": 90.0,
            "implied_volatility": 0.24,
            "delta": None,
            "option_type": "put",
            "greeks": {"delta": -0.24},
        },
    ]
    atm, call, put = mod.IVExtractor.extract_skew(options, 100.0)
    assert atm == 0.2
    assert call == 0.21
    assert put == 0.24


def test_extract_skew_greeks_only():
    mod = importlib.import_module("tomic.providers.polygon_iv")
    options = [
        {
            "strike_price": 100.0,
            "option_type": "call",
            "greeks": {"delta": 0.5, "iv": 0.2},
        },
        {
            "strike_price": 105.0,
            "option_type": "call",
            "greeks": {"delta": 0.22, "iv": 0.21},
        },
        {
            "strike_price": 90.0,
            "option_type": "put",
            "greeks": {"delta": -0.23, "iv": 0.24},
        },
    ]
    atm, call, put = mod.IVExtractor.extract_skew(options, 100.0)
    assert atm == 0.2
    assert call == 0.21
    assert put == 0.24
    atm_call, strike = mod.IVExtractor.extract_atm_call(options, 100.0, "ABC")
    assert atm_call == 0.2


def test_extract_skew_missing_delta_atm_only():
    mod = importlib.import_module("tomic.providers.polygon_iv")
    options = [
        {
            "strike_price": 100.0,
            "implied_volatility": 0.2,
            "option_type": "call",
            "delta": None,
        },
        {
            "strike_price": 105.0,
            "implied_volatility": 0.21,
            "option_type": "call",
            "delta": None,
        },
    ]
    atm, call, put = mod.IVExtractor.extract_skew(options, 100.0)
    assert atm == 0.2
    assert call is None
    assert put is None


def test_extract_skew_delta_near_threshold():
    mod = importlib.import_module("tomic.providers.polygon_iv")
    options = [
        {
            "strike_price": 100.0,
            "implied_volatility": 0.2,
            "delta": 0.26,
            "option_type": "call",
        },
        {
            "strike_price": 90.0,
            "implied_volatility": 0.23,
            "delta": -0.27,
            "option_type": "put",
        },
    ]
    atm, call, put = mod.IVExtractor.extract_skew(options, 100.0)
    assert atm == 0.2
    assert call == 0.2
    assert put == 0.23
