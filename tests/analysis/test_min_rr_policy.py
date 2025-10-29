import math
from copy import deepcopy

import pytest

from tomic.analysis import scoring
from tomic.criteria import RULES, load_criteria
from tomic.strategies import StrategyName


@pytest.mark.parametrize("strategy", [name.value for name in StrategyName])
def test_cli_min_rr_override_and_default(strategy, monkeypatch):
    criteria = load_criteria().model_copy()
    criteria.strategy.acceptance.min_risk_reward = None

    override = 1.7
    base_default = 0.9
    config_with_override = {
        "default": {"min_risk_reward": base_default},
        "strategies": {strategy: {"min_risk_reward": override}},
    }

    monkeypatch.setattr(
        scoring,
        "cfg_get",
        lambda key, default=None: deepcopy(config_with_override)
        if key == "STRATEGY_CONFIG"
        else default,
    )

    strategy_cfg = scoring._resolve_strategy_config(strategy)
    min_rr_override = scoring.resolve_min_risk_reward(strategy_cfg, criteria)
    assert math.isclose(min_rr_override, override)

    default_value = 1.25
    config_with_default = {"default": {"min_risk_reward": default_value}, "strategies": {}}

    monkeypatch.setattr(
        scoring,
        "cfg_get",
        lambda key, default=None: deepcopy(config_with_default)
        if key == "STRATEGY_CONFIG"
        else default,
    )

    strategy_cfg = scoring._resolve_strategy_config(strategy)
    min_rr_default = scoring.resolve_min_risk_reward(strategy_cfg, criteria)
    assert math.isclose(min_rr_default, default_value)

    monkeypatch.setattr(
        scoring,
        "cfg_get",
        lambda key, default=None: {}
        if key == "STRATEGY_CONFIG"
        else default,
    )
    strategy_cfg = scoring._resolve_strategy_config(strategy)
    min_rr_rules = scoring.resolve_min_risk_reward(strategy_cfg, criteria)
    expected_rules = scoring.resolve_min_risk_reward({}, None)
    assert math.isclose(min_rr_rules, expected_rules)
