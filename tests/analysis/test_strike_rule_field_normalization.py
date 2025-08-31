import os
from tomic import loader
from tomic.strategies import calendar, ratio_spread


def _calendar_chain():
    return [
        {"expiry": "2025-01-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2, "model": 1.5},
        {"expiry": "2025-02-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.1, "delta": 0.3, "edge": 0.1, "iv": 0.25, "model": 1.3},
        {"expiry": "2025-03-01", "strike": 105, "type": "C", "bid": 1, "ask": 1.3, "delta": 0.2, "edge": 0.1, "iv": 0.3, "model": 1.4},
    ]


def _ratio_chain():
    return [
        {"expiry": "20250101", "strike": 110, "type": "C", "bid": 1.4, "ask": 1.6, "delta": 0.4, "edge": 0.2, "model": 1.7},
        {"expiry": "20250101", "strike": 120, "type": "C", "bid": 0.3, "ask": 0.5, "delta": 0.25, "edge": 0.1, "model": 0.55},
        {"expiry": "20250101", "strike": 130, "type": "C", "bid": 0.1, "ask": 0.2, "delta": 0.1, "edge": 0.05, "model": 0.22},
    ]


def test_calendar_field_compat(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = _calendar_chain()
    old_cfg = {"calendar": {"strike_distance": [0], "expiry_gap_min": 20, "dte_range": [20, 80]}}
    new_cfg = {"calendar": {"base_strikes_relative_to_spot": [0], "expiry_gap_min_days": 20, "dte_range": [20, 80]}}
    rules_old = loader.load_strike_config("calendar", old_cfg)
    rules_new = loader.load_strike_config("calendar", new_cfg)
    cfg_old = {"strike_to_strategy_config": rules_old}
    cfg_new = {"strike_to_strategy_config": rules_new}
    props_old, _ = calendar.generate("AAA", chain, cfg_old, 100.0, 1.0)
    props_new, _ = calendar.generate("AAA", chain, cfg_new, 100.0, 1.0)
    assert props_old == props_new


def test_ratio_spread_field_compat():
    chain = _ratio_chain()
    old_cfg = {"ratio_spread": {"short_delta_range": [0.3, 0.45], "long_leg_distance": [10], "use_ATR": False}}
    new_cfg = {"ratio_spread": {"short_delta_range": [0.3, 0.45], "long_leg_distance_points": [10], "use_ATR": False}}
    rules_old = loader.load_strike_config("ratio_spread", old_cfg)
    rules_new = loader.load_strike_config("ratio_spread", new_cfg)
    cfg_old = {"strike_to_strategy_config": rules_old}
    cfg_new = {"strike_to_strategy_config": rules_new}
    props_old, _ = ratio_spread.generate("AAA", chain, cfg_old, 100.0, 1.0)
    props_new, _ = ratio_spread.generate("AAA", chain, cfg_new, 100.0, 1.0)
    assert props_old == props_new
