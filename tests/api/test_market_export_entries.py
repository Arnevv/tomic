import importlib
import types
import csv
from types import SimpleNamespace


class DummyApp:
    def __init__(self):
        self.market_data = {
            1: {
                "expiry": "20240101",
                "right": "C",
                "strike": 100,
                "bid": 1.0,
                "ask": 1.2,
                "iv": 0.2,
                "delta": 0.5,
                "gamma": 0.1,
                "vega": 0.2,
                "theta": -0.1,
            }
        }
        self.invalid_contracts = set()
        self.spot_price = 100.0
        self.expiries = ["20240101"]
        self._spot_req_ids = set()
        self._spot_req_id = None
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def _patch_pandas(monkeypatch):
    pd = importlib.import_module("pandas")
    monkeypatch.setattr(pd, "DataFrame", lambda *a, **k: object())


def test_export_option_chain_writes_csv(monkeypatch, tmp_path):
    _patch_pandas(monkeypatch)
    mod = importlib.reload(importlib.import_module("tomic.api.market_export"))
    dummy = DummyApp()
    monkeypatch.setattr(mod, "OptionChainClient", lambda sym: dummy)
    monkeypatch.setattr(mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(mod, "await_market_data", lambda app, sym, timeout=30: True)

    mod.export_option_chain("XYZ", str(tmp_path))

    files = list(tmp_path.glob("option_chain_XYZ_*.csv"))
    assert files
    with open(files[0], newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "Expiry"
    assert dummy.disconnected


def test_export_option_chain_logs_error(monkeypatch, tmp_path):
    mod = importlib.reload(importlib.import_module("tomic.api.market_export"))
    errors = []
    monkeypatch.setattr(mod.logger, "error", lambda msg: errors.append(msg))
    res = mod.export_option_chain("", str(tmp_path))
    assert res is None
    assert any("ongeldig" in e.lower() for e in errors)


def test_export_market_data_creates_csvs(monkeypatch, tmp_path):
    _patch_pandas(monkeypatch)
    mod = importlib.reload(importlib.import_module("tomic.api.market_export"))
    dummy = DummyApp()
    monkeypatch.setattr(mod, "OptionChainClient", lambda sym: dummy)
    monkeypatch.setattr(mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(mod, "await_market_data", lambda app, sym, timeout=30: True)
    monkeypatch.setattr(
        mod,
        "fetch_market_metrics",
        lambda *a, **k: {
            "spot_price": 100.0,
            "hv30": 10.0,
            "atr14": 1.0,
            "vix": 20.0,
            "skew": 0.0,
            "term_m1_m2": None,
            "term_m1_m3": None,
            "iv_rank": 0.05,
            "implied_volatility": 0.2,
            "iv_percentile": 0.50,
        },
    )

    mod.export_market_data("XYZ", str(tmp_path))

    chain_files = list(tmp_path.glob("option_chain_XYZ_*.csv"))
    metrics_files = list(tmp_path.glob("other_data_XYZ_*.csv"))
    assert chain_files and metrics_files
    with open(chain_files[0], newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "Expiry"
    with open(metrics_files[0], newline="") as f:
        mrows = list(csv.reader(f))
    assert mrows[0][0] == "Symbol"
    assert dummy.disconnected


def test_export_market_data_logs_error(monkeypatch, tmp_path):
    mod = importlib.reload(importlib.import_module("tomic.api.market_export"))
    dummy = DummyApp()
    monkeypatch.setattr(mod, "OptionChainClient", lambda sym: dummy)
    monkeypatch.setattr(mod, "start_app", lambda app, **k: None)
    monkeypatch.setattr(mod, "await_market_data", lambda app, sym, timeout=30: True)
    monkeypatch.setattr(mod, "fetch_market_metrics", lambda *a, **k: None)

    errors = []
    monkeypatch.setattr(mod.logger, "error", lambda msg: errors.append(msg))
    res = mod.export_market_data("XYZ", str(tmp_path))
    assert res is None
    assert any("geen expiries" in e.lower() for e in errors)
