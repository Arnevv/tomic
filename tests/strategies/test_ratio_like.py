from copy import deepcopy

from tomic.strategies import StrategyName

BASE_CHAIN = [
    {
        "expiry": "20250101",
        "strike": 100,
        "type": "call",
        "bid": 2.0,
        "ask": 2.2,
        "mid": 2.1,
        "delta": 0.4,
        "edge": 0.5,
        "rom": 12.0,
        "ev": 0.8,
        "pos": 0.65,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 1.9,
        "iv": 0.2,
        "gamma": 0.01,
        "vega": 0.15,
        "theta": -0.02,
        "margin_requirement": 700.0,
    },
    {
        "expiry": "20250101",
        "strike": 110,
        "type": "call",
        "bid": 0.5,
        "ask": 0.6,
        "mid": 0.55,
        "delta": 0.2,
        "edge": 0.5,
        "rom": 11.0,
        "ev": 0.7,
        "pos": 0.6,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 0.45,
        "iv": 0.19,
        "gamma": 0.01,
        "vega": 0.12,
        "theta": -0.015,
        "margin_requirement": 650.0,
    },
    {
        "expiry": "20250101",
        "strike": 101,
        "type": "call",
        "bid": 1.4,
        "ask": 1.6,
        "mid": 1.5,
        "delta": 0.35,
        "edge": 0.45,
        "rom": 11.5,
        "ev": 0.75,
        "pos": 0.62,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 1.3,
        "iv": 0.195,
        "gamma": 0.01,
        "vega": 0.14,
        "theta": -0.018,
        "margin_requirement": 680.0,
    },
    {
        "expiry": "20250101",
        "strike": 90,
        "type": "put",
        "bid": 5.0,
        "ask": 5.2,
        "mid": 5.1,
        "delta": -0.25,
        "edge": 5.0,
        "rom": 18.0,
        "ev": 1.5,
        "pos": 0.75,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 4.8,
        "iv": 0.21,
        "gamma": 0.02,
        "vega": 0.2,
        "theta": -0.03,
        "margin_requirement": 800.0,
    },
    {
        "expiry": "20250301",
        "strike": 80,
        "type": "put",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "delta": -0.15,
        "edge": 0.5,
        "rom": 10.0,
        "ev": 0.6,
        "pos": 0.6,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 0.95,
        "iv": 0.18,
        "gamma": 0.01,
        "vega": 0.1,
        "theta": -0.01,
        "margin_requirement": 500.0,
    },
    {
        "expiry": "20250301",
        "strike": 90,
        "type": "put",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "delta": -0.2,
        "edge": 0.5,
        "rom": 9.5,
        "ev": 0.55,
        "pos": 0.58,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 0.95,
        "iv": 0.18,
        "gamma": 0.01,
        "vega": 0.1,
        "theta": -0.01,
        "margin_requirement": 520.0,
    },
]

RATIO_CFG = {
    "min_risk_reward": 0.0,
    "strike_to_strategy_config": {
        "short_leg_delta_range": [0.3, 0.45],
        "long_leg_atr_multiple": 1,
        "use_ATR": False,
    },
}

BACKSPREAD_CFG = {
    "min_risk_reward": 0.0,
    "strike_to_strategy_config": {
        "short_put_delta_range": [-0.3, -0.15],
        "long_leg_distance_points": 5,
        "expiry_gap_min_days": 0,
        "use_ATR": False,
    },
}


def test_ratio_spread_via_shared_generator(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    monkeypatch.setattr(
        "tomic.analysis.scoring.calculate_score", lambda *_, **__: (1.0, [])
    )
    monkeypatch.setattr("tomic.analysis.scoring.passes_risk", lambda *_, **__: True)
    monkeypatch.setattr("tomic.strategy_candidates._validate_ratio", lambda *_, **__: True)
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
    monkeypatch.setattr(
        "tomic.analysis.scoring.calculate_score", lambda *_, **__: (1.0, [])
    )
    monkeypatch.setattr("tomic.analysis.scoring.passes_risk", lambda *_, **__: True)
    monkeypatch.setattr("tomic.strategy_candidates._validate_ratio", lambda *_, **__: True)
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
