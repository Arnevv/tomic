import importlib
import json
from datetime import datetime, date
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
    cfg_lambda = lambda name, default=None: (
        "key"
        if name == "POLYGON_API_KEY"
        else (
            str(price_dir)
            if name == "PRICE_HISTORY_DIR"
            else (
                str(iv_dir)
                if name in {"IV_DEBUG_DIR", "IV_SUMMARY_DIR"}
                else default
            )
        )
    )
    monkeypatch.setattr(mod, "cfg_get", cfg_lambda)
    import tomic.helpers.price_utils as price_utils
    monkeypatch.setattr(price_utils, "cfg_get", cfg_lambda)

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

    def fake_request(path, params=None):
        exp = params.get("expiration_date") if params else None
        if exp == "2024-01-19":
            return exp1
        elif exp == "2024-02-16":
            return exp2
        elif exp == "2024-03-15":
            return exp3
        return {"results": {"options": []}}

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def connect(self):
            pass

        def disconnect(self):
            pass

        def _request(self, path, params=None):
            return fake_request(path, params or {})

    monkeypatch.setattr(mod, "PolygonClient", lambda api_key=None: FakeClient())
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod, "_get_closes", lambda sym: [])

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            # Current date without close entry to ensure last known close is used
            return datetime(2024, 1, 3, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    metrics = mod.fetch_polygon_iv30d("ABC")
    assert metrics["atm_iv"] == 0.2
    assert metrics["term_m1_m2"] == 1.0
    assert metrics["term_m1_m3"] == 2.0
    assert metrics["skew"] == 3.0
    assert metrics["iv_rank (HV)"] is None
    assert metrics["iv_percentile (HV)"] is None
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
    cfg_lambda = lambda name, default=None: (
        "key"
        if name == "POLYGON_API_KEY"
        else (
            str(price_dir)
            if name == "PRICE_HISTORY_DIR"
            else (
                str(iv_dir)
                if name in {"IV_DEBUG_DIR", "IV_SUMMARY_DIR"}
                else default
            )
        )
    )
    monkeypatch.setattr(mod, "cfg_get", cfg_lambda)
    import tomic.helpers.price_utils as price_utils
    monkeypatch.setattr(price_utils, "cfg_get", cfg_lambda)

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

    def fake_request(path, params=None):
        exp = params.get("expiration_date") if params else None
        if exp == "2024-01-19":
            return exp1
        elif exp == "2024-02-16":
            return exp2
        elif exp == "2024-03-15":
            return exp3
        return {"results": {"options": []}}

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def connect(self):
            pass

        def disconnect(self):
            pass

        def _request(self, path, params=None):
            return fake_request(path, params or {})

    monkeypatch.setattr(mod, "PolygonClient", lambda api_key=None: FakeClient())
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod, "_get_closes", lambda sym: [])

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 3, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    metrics = mod.fetch_polygon_iv30d("ABC")
    assert metrics["atm_iv"] == 0.2
    assert metrics["term_m1_m2"] == 1.0
    assert metrics["term_m1_m3"] == 2.0
    assert metrics["skew"] is None
    assert metrics["iv_rank (HV)"] is None
    assert metrics["iv_percentile (HV)"] is None
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


def test_export_option_chain_rounding(monkeypatch, tmp_path):
    import csv

    mod = importlib.import_module("tomic.providers.polygon_iv")

    from pathlib import Path as RealPath

    monkeypatch.setattr(mod, "Path", lambda p="": RealPath(tmp_path) / p if p else RealPath(tmp_path))

    options = [
        {
            "strike_price": 101.1234,
            "expiration_date": "2024-01-19",
            "option_type": "call",
            "implied_volatility": 0.9271568240260529,
            "delta": 0.9880879838832902,
            "gamma": 0.0026639649196562956,
            "theta": -0.010407970021571658,
            "vega": 0.004738239548408383,
            "day": {"open": 11.3, "high": 11.3, "low": 11.3, "close": 11.3, "volume": 1, "vwap": 11.3},
            "details": {},
        }
    ]

    mod._export_option_chain("XYZ", options)

    csv_file = next(tmp_path.glob("**/*optionchainpolygon.csv"))
    with csv_file.open(newline="") as f:
        rows = list(csv.reader(f))

    assert rows[1][2] == "101.12"
    assert rows[1][0] == "2024-01-19"
    assert rows[1][6] == "0.9272"
    assert rows[1][7] == "0.9881"
    assert rows[1][8] == "0.0027"
    assert rows[1][10] == "-0.0104"
    assert rows[1][9] == "0.0047"


def test_load_polygon_expiries(monkeypatch):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    fridays = [
        date(2024, 1, 19),
        date(2024, 2, 16),
        date(2024, 3, 15),
        date(2024, 4, 19),
    ]

    monkeypatch.setattr(
        mod.ExpiryPlanner,
        "get_next_third_fridays",
        lambda start, count=4: fridays[:count],
    )
    monkeypatch.setattr(mod, "today", lambda: date(2024, 1, 1))
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: {
            "AMOUNT_REGULARS": 2,
            "AMOUNT_WEEKLIES": 1,
        }.get(n, d),
    )

    calls = []

    class FakeFetcher:
        def __init__(self, key=None):
            pass

        def fetch_expiry(self, symbol, expiry):
            calls.append(expiry)
            if expiry in {"2024-01-19", "2024-01-26"}:
                return [{}]
            return []

    monkeypatch.setattr(mod, "SnapshotFetcher", lambda key=None: FakeFetcher())

    expiries = mod.load_polygon_expiries("ABC")
    assert expiries == ["2024-01-19", "2024-01-26"]
    assert calls == ["2024-01-19", "2024-02-16", "2024-01-26"]


def test_fetch_polygon_option_chain_filters(monkeypatch):
    mod = importlib.import_module("tomic.providers.polygon_iv")

    opts1 = [
        {"expiration_date": "2024-01-19", "delta": 0.5},
        {"expiration_date": "2024-01-19", "delta": 0.9},
        {"expiration_date": "2024-01-19", "greeks": {"delta": 0.7}},
    ]
    opts2 = [
        {"expiration_date": "2024-02-16", "delta": -0.9},
        {"expiration_date": "2024-02-16", "delta": None, "greeks": {"delta": 0.2}},
        {"expiration_date": "2024-02-16", "delta": None},
    ]

    monkeypatch.setattr(
        mod,
        "load_polygon_expiries",
        lambda s, k=None, include_contracts=False: (
            ["2024-01-19", "2024-02-16"],
            {"2024-01-19": opts1, "2024-02-16": opts2},
        ),
    )
    captured = []
    monkeypatch.setattr(mod, "_export_option_chain", lambda s, opts: captured.append(opts))

    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda n, d=None: {
            "DELTA_MIN": -0.8,
            "DELTA_MAX": 0.8,
            "POLYGON_API_KEY": "key",
        }.get(n, d),
    )

    mod.fetch_polygon_option_chain("XYZ")

    assert captured
    exported = captured[0]
    assert len(exported) == 4

