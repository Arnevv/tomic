import importlib

import pytest

from tomic import loader
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.criteria import RULES
from tomic.strategies import StrategyName

strategies = [
    (
        StrategyName.NAKED_PUT,
        {"strike_to_strategy_config": {"short_put_delta_range": [-0.3, -0.25], "use_ATR": False}},
    ),
    (
        StrategyName.SHORT_PUT_SPREAD,
        {"strike_to_strategy_config": {"short_put_delta_range": [-0.35, -0.2], "long_leg_distance_points": 0.1, "use_ATR": False}},
    ),
    (
        StrategyName.SHORT_CALL_SPREAD,
        {"strike_to_strategy_config": {"short_call_delta_range": [0.2, 0.35], "long_leg_distance_points": 0.1, "use_ATR": False}},
    ),
    (
        StrategyName.RATIO_SPREAD,
        {"strike_to_strategy_config": {"short_leg_delta_range": [0.3, 0.45], "long_leg_distance_points": 0.1, "use_ATR": False}},
    ),
    (
        StrategyName.BACKSPREAD_PUT,
        {"strike_to_strategy_config": {"short_put_delta_range": [0.15, 0.3], "long_leg_distance_points": 0.1, "use_ATR": False}},
    ),
    (
        StrategyName.ATM_IRON_BUTTERFLY,
        {"strike_to_strategy_config": {"center_strike_relative_to_spot": [0], "wing_sigma_multiple": 1.0, "use_ATR": False}},
    ),
]

legacy_strategies = [
    (
        StrategyName.NAKED_PUT,
        {"short_delta_range": [-0.3, -0.25], "use_ATR": False},
    ),
    (
        StrategyName.SHORT_PUT_SPREAD,
        {"short_delta_range": [-0.35, -0.2], "long_put_distance_points": 5, "use_ATR": False},
    ),
    (
        StrategyName.SHORT_CALL_SPREAD,
        {"short_delta_range": [0.2, 0.35], "long_call_distance_points": 5, "use_ATR": False},
    ),
    (
        StrategyName.RATIO_SPREAD,
        {"short_delta_range": [0.3, 0.45], "long_leg_target_delta": 5, "use_ATR": False},
    ),
    (
        StrategyName.BACKSPREAD_PUT,
        {"short_delta_range": [0.15, 0.3], "long_put_distance_points": 5, "use_ATR": False},
    ),
    (
        StrategyName.ATM_IRON_BUTTERFLY,
        {"center_strike_relative_to_spot": [0], "wing_width_points": 5, "use_ATR": False},
    ),
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
    mod = importlib.import_module(f"tomic.strategies.{name.value}")
    props, _ = mod.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)


@pytest.mark.parametrize("name,rules", legacy_strategies)
def test_strategy_modules_legacy_keys_warn(name, rules):
    mod = importlib.import_module(f"tomic.strategies.{name.value}")
    with pytest.warns(DeprecationWarning):
        normalized = loader.load_strike_config(name.value, {name.value: rules})
    props, _ = mod.generate(
        "AAA", chain, {"strike_to_strategy_config": normalized}, 100.0, 1.0
    )
    assert isinstance(props, list)


def test_strategy_uses_default_block(monkeypatch):
    mod = importlib.import_module("tomic.strategies.naked_put")
    captured: dict = {}

    def fake_generate(symbol, option_chain, cfg, spot, atr):
        captured["cfg"] = cfg
        return [], []

    monkeypatch.setattr(mod, "generate", fake_generate)
    cfg = {
        "default": {"min_risk_reward": 99},
        "strategies": {
            "naked_put": {
                "strike_to_strategy_config": {
                    "short_put_delta_range": [-0.3, -0.25],
                    "use_ATR": False,
                }
            }
        },
    }
    generate_strategy_candidates("AAA", "naked_put", chain, 1.0, config=cfg, spot=100.0)
    assert captured["cfg"]["min_risk_reward"] == 99


def test_strategy_uses_rules_default(monkeypatch):
    mod = importlib.import_module("tomic.strategies.naked_put")
    captured: dict = {}

    def fake_generate(symbol, option_chain, cfg, spot, atr):
        captured["cfg"] = cfg
        return [], []

    monkeypatch.setattr(mod, "generate", fake_generate)
    cfg = {
        "strategies": {
            "naked_put": {
                "strike_to_strategy_config": {
                    "short_put_delta_range": [-0.3, -0.25],
                    "use_ATR": False,
                }
            }
        }
    }
    generate_strategy_candidates("AAA", "naked_put", chain, 1.0, config=cfg, spot=100.0)
    assert (
        captured["cfg"]["min_risk_reward"]
        == RULES.strategy.acceptance.min_risk_reward
    )
