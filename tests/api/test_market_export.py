# ruff: noqa: E402
import csv
import sys
import types
from types import SimpleNamespace

# Stub pandas so market_export can be imported without the real dependency
sys.modules.setdefault("pandas", types.ModuleType("pandas"))
contract_stub = types.ModuleType("ibapi.contract")


class Contract:  # noqa: D401 - simple stub
    """Stub contract object."""

    pass


contract_stub.Contract = Contract  # type: ignore[attr-defined]
sys.modules.setdefault("ibapi.contract", contract_stub)
client_stub = types.ModuleType("tomic.api.market_client")
client_stub.MarketClient = object
client_stub.OptionChainClient = object
client_stub.TermStructureClient = object
client_stub.fetch_market_metrics = lambda *a, **k: None
client_stub.start_app = lambda *a, **k: None
client_stub.await_market_data = lambda *a, **k: True
sys.modules.setdefault("tomic.api.market_client", client_stub)

from tomic.api.market_export import (
    _write_option_chain,
    _write_option_chain_simple,
    _HEADERS_CHAIN,
    _HEADERS_SIMPLE,
)


def test_write_option_chain_skips_invalid(tmp_path):
    market_data = {
        1: {
            "expiry": "20240101",
            "right": "C",
            "strike": 100,
            "bid": 1.0,
            "ask": 1.2,
            "iv": 0.25,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
            "volume": 5,
        },
        2: {
            "expiry": "20240101",
            "right": "P",
            "strike": 90,
            "bid": 0.8,
            "ask": 1.0,
            "iv": 0.3,
            "delta": -0.4,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
            "volume": 7,
        },
    }
    invalid_contracts = {2}
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=invalid_contracts,
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_CHAIN
    assert len(rows) == 3
    assert len(rows[0]) == len(_HEADERS_CHAIN)
    assert rows[1][2] == "100"  # strike of valid contract


def test_write_option_chain_negative_bid(tmp_path):
    """parity deviation should be empty when bid or ask is negative."""

    market_data = {
        1: {
            "expiry": "20240101",
            "right": "C",
            "strike": 100,
            "bid": -1.0,
            "ask": 1.2,
            "iv": 0.25,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
            "volume": 0,
        },
        2: {
            "expiry": "20240101",
            "right": "P",
            "strike": 100,
            "bid": 0.8,
            "ask": 1.0,
            "iv": 0.3,
            "delta": -0.4,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
            "volume": 0,
        },
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[1][-2] == ""
    assert rows[2][-2] == ""


def test_write_option_chain_no_records(tmp_path):
    """When no market data arrives, no CSV should be written."""

    app = SimpleNamespace(
        market_data={},
        invalid_contracts=set(),
        spot_price=100.0,
    )

    result = _write_option_chain(app, "ABC", str(tmp_path), "123")

    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_fetch_volatility_metrics_parses_new_fields(monkeypatch):
    import importlib

    html = """
        \"lastPrice\": 101.5
        HV:</span></span><span><strong>12%</strong></span>
        Skew:</span> <span><strong>-2.5%</strong></span>
        ATR(14):</span></span><span><strong>7.8</strong></span>
        VIX:</span> <span><strong>19.5</strong></span>
        M1 - M2:</span></span><span><strong>-0.3%</strong></span>
        M1-M3:</span></span><span><strong>-0.7%</strong></span>
        IV Rank 45
        Implied Volatility:</span></span><span><strong>20%</strong></span>
        IV Percentile:</span></span><span><strong>60%</strong></span>
    """

    mod = importlib.reload(importlib.import_module("tomic.cli.daily_vol_scraper"))

    async def fake_download(sym):
        return html

    monkeypatch.setattr(mod, "download_html_async", fake_download)

    data = mod.fetch_volatility_metrics("ABC")
    assert data["atr14"] == 7.8
    assert data["vix"] == 19.5
    assert "term_m1_m2" not in data
    assert "term_m1_m3" not in data


def test_fetch_market_metrics_includes_new_fields(monkeypatch):
    import importlib
    client_mod = importlib.reload(importlib.import_module("tomic.api.market_client"))

    class DummyApp:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.spot_price = 99.0

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_mod, "MarketClient", DummyApp)
    monkeypatch.setattr(client_mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(client_mod, "await_market_data", lambda app, symbol, timeout=10: True)

    monkeypatch.setattr(
        client_mod,
        "fetch_volatility_metrics",
        lambda sym: {
            "spot_price": 98.0,
            "hv30": 11.0,
            "atr14": 5.5,
            "vix": 17.2,
            "skew": -1.0,
            "iv_rank": 30.0,
            "implied_volatility": 25.0,
            "iv_percentile": 70.0,
        },
    )

    result = client_mod.fetch_market_metrics("XYZ", timeout=10)
    assert result["atr14"] == 5.5
    assert result["vix"] == 17.2
    assert result["term_m1_m2"] is None
    assert result["term_m1_m3"] is None


def test_fetch_market_metrics_computes_term_structure(monkeypatch):
    import importlib

    client_mod = importlib.reload(importlib.import_module("tomic.api.market_client"))

    class DummyApp:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.spot_price = 100.0
            self.market_data = {
                1: {"expiry": "20240101", "strike": 100.0, "iv": 0.2},
                2: {"expiry": "20240201", "strike": 100.0, "iv": 0.21},
                3: {"expiry": "20240301", "strike": 100.0, "iv": 0.22},
            }
            self.invalid_contracts = set()
            self.expiries = ["20240101", "20240201", "20240301"]

        def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_mod, "OptionChainClient", DummyApp)
    monkeypatch.setattr(client_mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(client_mod, "await_market_data", lambda app, symbol, timeout=10: True)
    monkeypatch.setattr(
        client_mod,
        "fetch_volatility_metrics",
        lambda sym: {
            "spot_price": None,
            "hv30": 11.0,
            "atr14": 5.5,
            "vix": 17.2,
            "skew": -1.0,
            "iv_rank": 30.0,
            "implied_volatility": 25.0,
            "iv_percentile": 70.0,
        },
    )

    app = DummyApp("XYZ")
    result = client_mod.fetch_market_metrics("XYZ", app=app, timeout=10)

    assert result["term_m1_m2"] == -1.0
    assert result["term_m1_m3"] == -2.0


def test_write_option_chain_simple(tmp_path):
    market_data = {
        1: {"expiry": "20240101", "right": "C", "strike": 100, "bid": 1.0, "ask": 1.2},
        2: {"expiry": "20240101", "right": "P", "strike": 90, "bid": 0.8, "ask": 1.0},
        3: {"expiry": "20240101", "right": "C", "strike": 110, "bid": None, "ask": None},
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts={3},
        _spot_req_id=1,
    )

    _write_option_chain_simple(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_SIMPLE
    assert len(rows) == 3  # header + valid + invalid


def test_write_option_chain_simple_close_only(tmp_path):
    market_data = {
        1: {"expiry": "20240101", "right": "C", "strike": 100, "close": 2.0},
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
    )

    _write_option_chain_simple(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_SIMPLE
    assert len(rows) == 2
    idx = _HEADERS_SIMPLE.index("Close")
    assert rows[1][idx] == "2.0"


def test_write_option_chain_skips_spot_id(tmp_path):
    market_data = {
        1: {"expiry": "20240101", "right": "C", "strike": 100, "bid": 1.0, "ask": 1.2},
        2: {"expiry": "20240101", "right": "P", "strike": 100, "bid": 0.8, "ask": 1.0},
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
        _spot_req_id=1,
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_CHAIN
    assert len(rows) == 2  # header + one option record


def test_write_option_chain_all_rows_exported(tmp_path):
    market_data = {
        10: {"expiry": "20240101", "right": "C", "strike": 100, "bid": 1.0, "ask": 1.2},
        11: {"expiry": "20240101", "right": "P", "strike": 100, "bid": 0.8, "ask": 1.0},
        12: {"expiry": "20240101", "right": "C", "strike": 110, "bid": 1.5, "ask": 1.7},
        13: {"expiry": "20240101", "right": "P", "strike": 110, "bid": 1.3, "ask": 1.6},
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
        _spot_req_id=1,
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "999")

    path = tmp_path / "option_chain_ABC_999.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 5  # header + four option records


def test_write_option_chain_ignores_multiple_spot_ids(tmp_path):
    market_data = {
        1: {"expiry": "20240101", "right": "C", "strike": 100, "bid": 1.0, "ask": 1.2},
        2: {"expiry": "20240101", "right": "P", "strike": 100, "bid": 0.8, "ask": 1.0},
        3: {"expiry": "20240101", "right": "C", "strike": 110, "bid": 1.5, "ask": 1.7},
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
        _spot_req_id=2,
        _spot_req_ids={1, 2},
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "777")

    path = tmp_path / "option_chain_ABC_777.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_CHAIN
    assert len(rows) == 2  # header + one option record (req_id 3)


def test_export_option_chain_simple_flag(monkeypatch, tmp_path):
    import importlib

    mod = importlib.reload(importlib.import_module("tomic.api.market_export"))

    dummy_app = SimpleNamespace(market_data={}, invalid_contracts=set(), disconnect=lambda: None)

    monkeypatch.setattr(mod, "OptionChainClient", lambda sym: dummy_app)
    monkeypatch.setattr(mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(mod, "await_market_data", lambda app, symbol, timeout=60: True)

    called = []
    monkeypatch.setattr(
        mod,
        "_write_option_chain_simple",
        lambda app, sym, out, ts: called.append((sym, out)),
    )
    monkeypatch.setattr(mod, "_write_option_chain", lambda *a, **k: None)

    mod.export_option_chain("XYZ", str(tmp_path), simple=True)

    assert called == [("XYZ", str(tmp_path))]
