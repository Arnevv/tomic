import importlib

import pytest

strategies = [
    ("naked_put", {"strategies": {"naked_put": {"strike_to_strategy_config": {"short_put_delta_range": [-0.3, -0.25], "use_ATR": False}}}}),
    ("short_put_spread", {"strategies": {"short_put_spread": {"strike_to_strategy_config": {"short_put_delta_range": [-0.35, -0.2], "long_put_distance_points": [5], "use_ATR": False}}}}),
    ("short_call_spread", {"strategies": {"short_call_spread": {"strike_to_strategy_config": {"short_call_delta_range": [0.2, 0.35], "long_call_distance_points": [5], "use_ATR": False}}}}),
    ("ratio_spread", {"strategies": {"ratio_spread": {"strike_to_strategy_config": {"short_leg_delta_range": [0.3, 0.45], "long_leg_distance_points": [5], "use_ATR": False}}}}),
    ("backspread_put", {"strategies": {"backspread_put": {"strike_to_strategy_config": {"short_put_delta_range": [0.15, 0.3], "long_put_distance_points": [5], "use_ATR": False}}}}),
    ("atm_iron_butterfly", {"strategies": {"atm_iron_butterfly": {"strike_to_strategy_config": {"center_strike_relative_to_spot": [0], "wing_width_points": [5], "use_ATR": False}}}}),
]

chain = [
    {"expiry": "20250101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.2, "delta": 0.4, "edge": 0.1, "model": 0},
    {"expiry": "20250101", "strike": 120, "type": "C", "bid": 0.5, "ask": 0.7, "delta": 0.2, "edge": 0.1, "model": 0},
    {"expiry": "20250101", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.1, "delta": -0.3, "edge": 0.1, "model": 0},
    {"expiry": "20250101", "strike": 80, "type": "P", "bid": 0.4, "ask": 0.6, "delta": -0.1, "edge": 0.1, "model": 0},
    {"expiry": "20250301", "strike": 90, "type": "P", "bid": 1.2, "ask": 1.4, "delta": -0.25, "edge": 0.1, "model": 0},
    {"expiry": "20250301", "strike": 110, "type": "C", "bid": 1.1, "ask": 1.3, "delta": 0.35, "edge": 0.1, "model": 0},
]

@pytest.mark.parametrize("name,cfg", strategies)
def test_strategy_modules_smoke(name, cfg):
    mod = importlib.import_module(f"tomic.strategies.{name}")
    props = mod.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)
