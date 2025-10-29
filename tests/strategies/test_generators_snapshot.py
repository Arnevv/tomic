import json
from pathlib import Path
from copy import deepcopy

import pytest

from tomic.strategies import (
    atm_iron_butterfly,
    backspread_put,
    calendar,
    iron_condor,
    naked_put,
    ratio_spread,
    short_call_spread,
    short_put_spread,
)

SAMPLE_CHAIN = [
    {
        "expiry": "20250101",
        "strike": 100.0,
        "type": "call",
        "bid": 2.0,
        "ask": 2.2,
        "mid": 2.1,
        "delta": 0.42,
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
        "strike": 105.0,
        "type": "call",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "delta": 0.32,
        "edge": 0.45,
        "rom": 11.0,
        "ev": 0.7,
        "pos": 0.6,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 0.95,
        "iv": 0.19,
        "gamma": 0.01,
        "vega": 0.14,
        "theta": -0.015,
        "margin_requirement": 650.0,
    },
    {
        "expiry": "20250301",
        "strike": 100.0,
        "type": "call",
        "bid": 3.5,
        "ask": 3.7,
        "mid": 3.6,
        "delta": 0.38,
        "edge": 0.55,
        "rom": 13.0,
        "ev": 0.9,
        "pos": 0.7,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 3.1,
        "iv": 0.21,
        "gamma": 0.02,
        "vega": 0.2,
        "theta": -0.03,
        "margin_requirement": 720.0,
    },
    {
        "expiry": "20250301",
        "strike": 105.0,
        "type": "call",
        "bid": 2.4,
        "ask": 2.6,
        "mid": 2.5,
        "delta": 0.28,
        "edge": 0.52,
        "rom": 10.5,
        "ev": 0.68,
        "pos": 0.58,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 2.2,
        "iv": 0.205,
        "gamma": 0.015,
        "vega": 0.18,
        "theta": -0.022,
        "margin_requirement": 680.0,
    },
    {
        "expiry": "20250101",
        "strike": 95.0,
        "type": "put",
        "bid": 1.8,
        "ask": 1.95,
        "mid": 1.875,
        "delta": -0.25,
        "edge": 0.6,
        "rom": 14.0,
        "ev": 0.85,
        "pos": 0.7,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 1.6,
        "iv": 0.22,
        "gamma": 0.02,
        "vega": 0.18,
        "theta": -0.025,
        "margin_requirement": 750.0,
    },
    {
        "expiry": "20250101",
        "strike": 90.0,
        "type": "put",
        "bid": 1.2,
        "ask": 1.35,
        "mid": 1.275,
        "delta": -0.35,
        "edge": 0.65,
        "rom": 15.0,
        "ev": 0.9,
        "pos": 0.72,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 1.1,
        "iv": 0.225,
        "gamma": 0.018,
        "vega": 0.19,
        "theta": -0.027,
        "margin_requirement": 780.0,
    },
    {
        "expiry": "20250301",
        "strike": 95.0,
        "type": "put",
        "bid": 2.6,
        "ask": 2.8,
        "mid": 2.7,
        "delta": -0.22,
        "edge": 0.58,
        "rom": 11.5,
        "ev": 0.75,
        "pos": 0.65,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 2.3,
        "iv": 0.215,
        "gamma": 0.017,
        "vega": 0.19,
        "theta": -0.024,
        "margin_requirement": 730.0,
    },
    {
        "expiry": "20250301",
        "strike": 90.0,
        "type": "put",
        "bid": 1.9,
        "ask": 2.05,
        "mid": 1.975,
        "delta": -0.3,
        "edge": 0.6,
        "rom": 12.2,
        "ev": 0.82,
        "pos": 0.68,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "model_price": 1.7,
        "iv": 0.22,
        "gamma": 0.016,
        "vega": 0.185,
        "theta": -0.023,
        "margin_requirement": 760.0,
    },
]

SPOT = 100.0
ATR = 5.0

CONFIGS = {
    "short_call_spread": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "short_call_delta_range": [0.3, 0.5],
            "long_leg_atr_multiple": 1.0,
        },
    },
    "short_put_spread": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "short_put_delta_range": [-0.4, -0.2],
            "long_leg_atr_multiple": 1.0,
        },
    },
    "naked_put": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": False,
            "short_put_delta_range": [-0.4, -0.2],
            "dte_range": [0, 400],
        },
    },
    "ratio_spread": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "short_leg_delta_range": [0.3, 0.5],
            "long_leg_atr_multiple": 1.0,
        },
    },
    "backspread_put": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "short_put_delta_range": [-0.4, -0.2],
            "long_leg_distance_points": 5,
            "expiry_gap_min_days": 0,
        },
    },
    "iron_condor": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "short_call_delta_range": [0.3, 0.5],
            "short_put_delta_range": [-0.4, -0.2],
            "wing_sigma_multiple": 1.0,
        },
    },
    "atm_iron_butterfly": {
        "min_risk_reward": 0.0,
        "strike_to_strategy_config": {
            "use_ATR": True,
            "center_strike_relative_to_spot": [0],
            "wing_sigma_multiple": 1.0,
        },
    },
    "calendar": {
        "min_risk_reward": 0.0,
        "preferred_option_type": "C",
        "strike_to_strategy_config": {
            "use_ATR": True,
            "base_strikes_relative_to_spot": [0],
            "expiry_gap_min_days": 30,
            "dte_range": [0, 400],
        },
    },
}

GENERATORS = {
    "short_call_spread": short_call_spread.generate,
    "short_put_spread": short_put_spread.generate,
    "naked_put": naked_put.generate,
    "ratio_spread": ratio_spread.generate,
    "backspread_put": backspread_put.generate,
    "iron_condor": iron_condor.generate,
    "atm_iron_butterfly": atm_iron_butterfly.generate,
    "calendar": calendar.generate,
}

EXPECTATION_PATH = Path(__file__).with_name("expectations").joinpath("generators.json")


def _sanitize_leg(leg: dict[str, object]) -> dict[str, object]:
    keys = ["expiry", "strike", "type", "position"]
    return {key: leg.get(key) for key in keys}


def _sanitize_proposal(proposal):
    return {
        "strategy": proposal.strategy,
        "legs": [_sanitize_leg(dict(leg)) for leg in proposal.legs],
        "score": proposal.score,
        "credit": proposal.credit,
    }


def _sanitize_output(proposals, reasons):
    sanitized = {
        "proposals": [_sanitize_proposal(p) for p in proposals],
        "reasons": sorted(reasons),
    }
    sanitized["proposals"].sort(
        key=lambda item: [(leg["expiry"], leg["strike"], leg["position"]) for leg in item["legs"]]
    )
    return sanitized


@pytest.fixture(autouse=True)
def _patch_scoring(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")

    def _fake_score(strategy, proposal, spot, atr=0.0, **kwargs):
        proposal.score = 1.0
        if proposal.credit is None:
            proposal.credit = 1.0
        return 1.0, []

    targets = [
        "tomic.analysis.scoring",
        "tomic.strategies.naked_put",
        "tomic.strategies.calendar",
    ]
    for target in targets:
        monkeypatch.setattr(f"{target}.calculate_score", _fake_score)
        monkeypatch.setattr(f"{target}.passes_risk", lambda *_, **__: True)
    monkeypatch.setattr("tomic.strategy_candidates._validate_ratio", lambda *_, **__: True)


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_strategy_generators_snapshot(name):
    generator = GENERATORS[name]
    config = deepcopy(CONFIGS[name])
    chain = deepcopy(SAMPLE_CHAIN)

    proposals, reasons = generator("AAA", chain, config, SPOT, ATR)
    actual = _sanitize_output(proposals, reasons)

    expected_all = json.loads(EXPECTATION_PATH.read_text())
    expected = expected_all[name]
    assert actual == expected
