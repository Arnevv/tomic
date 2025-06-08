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
client_stub.fetch_market_metrics = lambda *a, **k: None
client_stub.start_app = lambda *a, **k: None
client_stub.await_market_data = lambda *a, **k: True
sys.modules.setdefault("tomic.api.market_client", client_stub)

from tomic.api.market_export import _write_option_chain, _HEADERS_CHAIN


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
    assert len(rows) == 2
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

    assert rows[1][-1] == ""
    assert rows[2][-1] == ""


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
        HV 30: 12%
        Skew -2.5
        ATR(14): 7.8
        VIX 19.5
        M1-M2 -0.3%
        M1-M3 -0.7%
        IV Rank 45
        Implied Volatility 20%
        IV Percentile 60%
    """

    mod = importlib.reload(importlib.import_module("tomic.cli.daily_vol_scraper"))
    monkeypatch.setattr(mod, "download_html", lambda sym: html)

    data = mod.fetch_volatility_metrics("ABC")
    assert data["atr14"] == 7.8
    assert data["vix"] == 19.5
    assert data["term_m1_m2"] == -0.3
    assert data["term_m1_m3"] == -0.7


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
    monkeypatch.setattr(client_mod, "start_app", lambda app: None)
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
            "term_m1_m2": -0.4,
            "term_m1_m3": -0.9,
            "iv_rank": 30.0,
            "implied_volatility": 25.0,
            "iv_percentile": 70.0,
        },
    )

    result = client_mod.fetch_market_metrics("XYZ")
    assert result["atr14"] == 5.5
    assert result["vix"] == 17.2
    assert result["term_m1_m2"] == -0.4
    assert result["term_m1_m3"] == -0.9
