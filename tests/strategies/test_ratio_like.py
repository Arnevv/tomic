from copy import deepcopy

from tomic.strategies import StrategyName

BASE_CHAIN = [
    {"expiry": "20250101", "strike": 100, "type": "call", "bid": 2.0, "ask": 2.2, "delta": 0.4, "edge": 0.5, "model": 0.0, "iv": 0.2},
    {"expiry": "20250101", "strike": 110, "type": "call", "bid": 0.5, "ask": 0.6, "delta": 0.2, "edge": 0.5, "model": 0.0, "iv": 0.2},
    {"expiry": "20250101", "strike": 90, "type": "put", "bid": 5.0, "ask": 5.2, "delta": -0.25, "edge": 5.0, "model": 0.0, "iv": 0.2},
    {"expiry": "20250301", "strike": 80, "type": "put", "bid": 1.0, "ask": 1.1, "delta": -0.15, "edge": 0.5, "model": 0.0, "iv": 0.2},
    {"expiry": "20250301", "strike": 90, "type": "put", "bid": 1.0, "ask": 1.1, "delta": -0.2, "edge": 0.5, "model": 0.0, "iv": 0.2},
]

RATIO_CFG = {
    "min_risk_reward": 0.1,
    "strike_to_strategy_config": {
        "short_leg_delta_range": [0.3, 0.45],
        "long_leg_atr_multiple": 10,
        "use_ATR": False,
    },
}

BACKSPREAD_CFG = {
    "min_risk_reward": 0.1,
    "strike_to_strategy_config": {
        "short_put_delta_range": [-0.3, -0.15],
        "long_leg_distance_points": 10,
        "expiry_gap_min_days": 0,
        "use_ATR": False,
    },
}


def test_ratio_spread_via_shared_generator(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = deepcopy(BASE_CHAIN)
    import tomic.utils  # ensure utils imported before strategies.utils
    from tomic.strategies.utils import generate_ratio_like
    props, reasons = generate_ratio_like(
        "AAA",
        chain,
        RATIO_CFG,
        100.0,
        1.0,
        strategy_name=StrategyName.RATIO_SPREAD,
        option_type="C",
        delta_range_key="short_leg_delta_range",
        use_expiry_pairs=False,
    )
    assert props, reasons
    assert props[0].legs[0]["expiry"] == "20250101"
    assert props[0].legs[1]["expiry"] == "20250101"


def test_backspread_put_via_shared_generator(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = deepcopy(BASE_CHAIN)
    import tomic.utils  # ensure utils imported before strategies.utils
    from tomic.strategies.utils import generate_ratio_like
    props, reasons = generate_ratio_like(
        "AAA",
        chain,
        BACKSPREAD_CFG,
        100.0,
        1.0,
        strategy_name=StrategyName.BACKSPREAD_PUT,
        option_type="P",
        delta_range_key="short_put_delta_range",
        use_expiry_pairs=True,
        max_pairs=3,
    )
    assert props, reasons
    assert props[0].legs[0]["expiry"] == "20250101"
    assert props[0].legs[1]["expiry"] == "20250301"
