import importlib
from types import SimpleNamespace


def test_process_chain_respects_quality(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    csv_path = tmp_path / "chain.csv"
    csv_path.write_text("data")

    monkeypatch.setattr(mod, "load_exported_chain", lambda p: [{"expiry": "20240101"}])
    monkeypatch.setattr(
        mod,
        "analyze_csv",
        lambda p: {"total": 10, "valid": 5, "partial_quality": 50},
    )
    monkeypatch.setattr(mod.cfg, "get", lambda name, default=None: 70 if name == "CSV_MIN_QUALITY" else default)
    monkeypatch.setattr(mod.cfg, "_load_yaml", lambda p: {})
    monkeypatch.setattr(mod, "load_strike_config", lambda strat, data: {})
    monkeypatch.setattr(mod, "_load_spot_from_metrics", lambda d, s: None)
    monkeypatch.setattr(mod, "_load_latest_close", lambda s: (100.0, "20240101"))

    called = {}
    monkeypatch.setattr(mod, "filter_by_expiry", lambda data, rng: called.setdefault("filter", True) or data)
    monkeypatch.setattr(mod, "prompt_yes_no", lambda text, default=False: False)

    mod._process_chain(csv_path)

    assert "filter" not in called


def test_write_option_chain_skips_selector_on_low_quality(tmp_path, monkeypatch):
    import tomic.api.market_export as mod

    market_data = {
        1: {"expiry": "20240101", "right": "CALL", "strike": 100, "bid": 1.0, "ask": 1.2},
    }
    app = SimpleNamespace(market_data=market_data, invalid_contracts=set(), spot_price=100.0)

    monkeypatch.setattr(
        mod,
        "analyze_csv",
        lambda p: {"total": 10, "valid": 5, "partial_quality": 50},
    )
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: 70 if name == "CSV_MIN_QUALITY" else default)

    class DummySelector:
        def __init__(self):
            self.called = False

        def select(self, data):
            self.called = True
            return data

    dummy = DummySelector()
    monkeypatch.setattr(mod, "StrikeSelector", lambda: dummy)

    mod._write_option_chain(app, "ABC", str(tmp_path), "111")

    assert not dummy.called
