import importlib
import pandas as pd
import pytest
from types import SimpleNamespace

from tomic.services.chain_processing import (
    ChainPreparationConfig,
    PreparedChain,
    SpotResolution,
)

if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)


def test_process_chain_respects_quality(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    csv_path = tmp_path / "chain.csv"
    csv_path.write_text("data")

    prep_cfg = ChainPreparationConfig(min_quality=70)
    monkeypatch.setattr(
        mod.ChainPreparationConfig,
        "from_app_config",
        classmethod(lambda cls: prep_cfg),
    )

    prepared = PreparedChain(
        path=csv_path,
        source_path=csv_path,
        dataframe=pd.DataFrame({"expiry": ["2024-01-01"]}),
        records=[{"expiry": "2024-01-01"}],
        quality=50.0,
        interpolation_applied=False,
    )
    monkeypatch.setattr(mod, "load_and_prepare_chain", lambda *a, **k: prepared)
    monkeypatch.setattr(
        mod,
        "resolve_chain_spot_price",
        lambda *a, **k: SpotResolution(100.0, "live", True, False),
    )
    monkeypatch.setattr(mod, "_spot_from_chain", lambda records: 100.0)

    evaluation = SimpleNamespace(
        context=SimpleNamespace(symbol="AAA", spot_price=100.0),
        filter_preview=SimpleNamespace(by_filter={}, by_reason={}),
        evaluated_trades=[],
        proposals=[],
        summary=SimpleNamespace(by_filter={}, by_reason={}),
    )
    evaluate_called: dict[str, bool] = {}

    def fake_evaluate(*args, **kwargs):
        evaluate_called["called"] = True
        return evaluation

    monkeypatch.setattr(mod, "evaluate_chain", fake_evaluate)
    monkeypatch.setattr(mod, "_print_reason_summary", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_print_evaluation_overview", lambda *a, **k: None)
    monkeypatch.setattr(mod, "prompt_yes_no", lambda text, default=False: False)

    mod._process_chain(csv_path)

    assert "called" not in evaluate_called


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
