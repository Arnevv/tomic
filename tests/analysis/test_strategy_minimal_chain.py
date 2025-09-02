import pytest
from copy import deepcopy

from tomic import strategy_candidates
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.strategies.config_models import CONFIG_MODELS
from tomic.utils import normalize_right

# Base options chain with minimal coverage for all strategies
BASE_CHAIN = [
    {"expiry": "20250101", "strike": 100, "type": "call", "bid": 2.0, "ask": 2.2, "delta": 0.5, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250101", "strike": 110, "type": "call", "bid": 5.0, "ask": 5.2, "delta": 0.4, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250101", "strike": 120, "type": "call", "bid": 0.5, "ask": 0.6, "delta": 0.2, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250101", "strike": 80, "type": "put", "bid": 0.5, "ask": 0.6, "delta": -0.1, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250101", "strike": 90, "type": "put", "bid": 5.0, "ask": 5.2, "delta": -0.25, "edge": 5.0, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250101", "strike": 100, "type": "put", "bid": 2.0, "ask": 2.2, "delta": -0.5, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250301", "strike": 100, "type": "call", "bid": 5.0, "ask": 5.2, "delta": 0.45, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250301", "strike": 100, "type": "put", "bid": 5.0, "ask": 5.2, "delta": -0.45, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250301", "strike": 90, "type": "put", "bid": 1.0, "ask": 1.1, "delta": -0.2, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250301", "strike": 80, "type": "put", "bid": 1.0, "ask": 1.1, "delta": -0.15, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
    {"expiry": "20250301", "strike": 110, "type": "call", "bid": 1.0, "ask": 1.1, "delta": 0.35, "edge": 0.5, "model": 0, "iv": 0.2, "volume": 100, "open_interest": 1000},
]

# Minimal valid configuration per strategy
VALID_CONFIGS = {
    "naked_put": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {"short_put_delta_range": [-0.3, -0.2], "use_ATR": False},
    },
    "short_put_spread": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "short_put_delta_range": [-0.35, -0.2],
            "long_leg_distance_points": 10,
            "use_ATR": False,
        },
    },
    "short_call_spread": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "long_leg_distance_points": 10,
            "use_ATR": False,
        },
    },
    "ratio_spread": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "short_leg_delta_range": [0.3, 0.45],
            "long_leg_distance_points": 10,
            "use_ATR": False,
        },
    },
    "backspread_put": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "short_put_delta_range": [-0.3, -0.15],
            "long_leg_distance_points": 10,
            "expiry_gap_min_days": 0,
            "use_ATR": False,
        },
    },
    "atm_iron_butterfly": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "center_strike_relative_to_spot": [0],
            "wing_sigma_multiple": 0.66,
            "use_ATR": False,
        },
    },
    "iron_condor": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.2],
            "wing_sigma_multiple": 0.66,
            "use_ATR": False,
        },
    },
    "calendar": {
        "min_risk_reward": 0.1,
        "strike_to_strategy_config": {
            "base_strikes_relative_to_spot": [0],
            "expiry_gap_min_days": 0,
            "use_ATR": False,
        },
    },
}

ALL_STRATEGIES = list(VALID_CONFIGS)
POSITIVE_CREDIT_STRATS = {s.value for s in strategy_candidates.POSITIVE_CREDIT_STRATS}


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_strategy_generates_proposal(strategy, monkeypatch):
    """Each strategy should yield at least one proposal with valid config."""
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = deepcopy(BASE_CHAIN)
    cfg = deepcopy(VALID_CONFIGS[strategy])
    model_cls = CONFIG_MODELS[strategy]
    validated = model_cls(**cfg)
    cfg_norm = {"strategies": {strategy: validated.model_dump()}}
    assert "strike_config" not in cfg_norm["strategies"][strategy]
    props, reasons = generate_strategy_candidates(
        "AAA", strategy, chain, 1.0, cfg_norm, 100.0
    )
    if not props:
        bad_words = ["ongeldige", "ontbrekende", "delta", "ratio", "config"]
        assert not any(any(w in r for w in bad_words) for r in reasons), reasons
    if props and strategy in POSITIVE_CREDIT_STRATS:
        assert props[0].credit is None or props[0].credit > 0


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_min_risk_reward_enforced(strategy, monkeypatch):
    """A high min_risk_reward should filter out all proposals."""
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = deepcopy(BASE_CHAIN)
    cfg = deepcopy(VALID_CONFIGS[strategy])
    cfg["min_risk_reward"] = 99.0
    model_cls = CONFIG_MODELS[strategy]
    validated = model_cls(**cfg)
    cfg_norm = {"strategies": {strategy: validated.model_dump()}}
    props, _ = generate_strategy_candidates(
        "AAA", strategy, chain, 1.0, cfg_norm, 100.0
    )
    assert not props


def _set_mid(chain, opt_type, strike, price):
    for opt in chain:
        if normalize_right(opt["type"]) == normalize_right(opt_type) and opt["strike"] == strike:
            opt["bid"] = price
            opt["ask"] = price


NEGATIVE_CHAIN_ADJUSTERS = {
    "short_put_spread": lambda ch: _set_mid(ch, "put", 80, 20.0),
    "short_call_spread": lambda ch: _set_mid(ch, "call", 120, 20.0),
    "iron_condor": lambda ch: (_set_mid(ch, "call", 120, 20.0), _set_mid(ch, "put", 80, 20.0)),
    "atm_iron_butterfly": lambda ch: (
        _set_mid(ch, "call", 110, 20.0),
        _set_mid(ch, "put", 90, 20.0),
    ),
}


@pytest.mark.parametrize("strategy", NEGATIVE_CHAIN_ADJUSTERS)
def test_negative_credit_rejected(strategy, monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = deepcopy(BASE_CHAIN)
    NEGATIVE_CHAIN_ADJUSTERS[strategy](chain)
    cfg = deepcopy(VALID_CONFIGS[strategy])
    model_cls = CONFIG_MODELS[strategy]
    validated = model_cls(**cfg)
    cfg_norm = {"strategies": {strategy: validated.model_dump()}}
    props, reasons = generate_strategy_candidates(
        "AAA", strategy, chain, 1.0, cfg_norm, 100.0
    )
    assert not props
    assert "negatieve credit" in reasons

