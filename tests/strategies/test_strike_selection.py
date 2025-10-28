from pathlib import Path

import pytest

from tomic import config as app_config
from tomic.core.config.strike_selection import load_strategy_rules, reload as reload_selection
from tomic.criteria import load_criteria
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.strike_selector import StrikeSelector, load_filter_config


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "strategies.yaml"


BASE_CHAIN = [
    {
        "expiry": "2024-07-19",
        "type": "put",
        "strike": 95.0,
        "delta": -0.25,
        "bid": 3.2,
        "ask": 3.4,
        "mid": 3.3,
        "model_price": 3.1,
        "iv": 0.25,
        "rom": 15.0,
        "edge": 0.25,
        "pos": 0.72,
        "ev": 1.3,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.2,
        "theta": -0.03,
        "margin_requirement": 800.0,
    },
    {
        "expiry": "2024-07-19",
        "type": "put",
        "strike": 90.0,
        "delta": -0.18,
        "bid": 1.8,
        "ask": 2.0,
        "mid": 1.9,
        "model_price": 1.8,
        "iv": 0.24,
        "rom": 14.0,
        "edge": 0.22,
        "pos": 0.71,
        "ev": 1.1,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.18,
        "theta": -0.02,
        "margin_requirement": 600.0,
    },
    {
        "expiry": "2024-07-19",
        "type": "call",
        "strike": 105.0,
        "delta": 0.22,
        "bid": 2.1,
        "ask": 2.3,
        "mid": 2.2,
        "model_price": 2.0,
        "iv": 0.22,
        "rom": 13.5,
        "edge": 0.2,
        "pos": 0.7,
        "ev": 1.0,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.19,
        "theta": -0.02,
        "margin_requirement": 700.0,
    },
    {
        "expiry": "2024-07-19",
        "type": "call",
        "strike": 110.0,
        "delta": 0.32,
        "bid": 1.1,
        "ask": 1.3,
        "mid": 1.2,
        "model_price": 1.1,
        "iv": 0.21,
        "rom": 12.5,
        "edge": 0.18,
        "pos": 0.68,
        "ev": 0.9,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.15,
        "theta": -0.015,
        "margin_requirement": 650.0,
    },
    {
        "expiry": "2024-07-19",
        "type": "call",
        "strike": 115.0,
        "delta": 0.1,
        "bid": 0.6,
        "ask": 0.8,
        "mid": 0.7,
        "model_price": 0.6,
        "iv": 0.19,
        "rom": 11.5,
        "edge": 0.16,
        "pos": 0.63,
        "ev": 0.7,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.12,
        "theta": -0.012,
        "margin_requirement": 600.0,
    },
    {
        "expiry": "2024-07-19",
        "type": "put",
        "strike": 85.0,
        "delta": -0.12,
        "bid": 0.9,
        "ask": 1.1,
        "mid": 1.0,
        "model_price": 0.95,
        "iv": 0.22,
        "rom": 11.8,
        "edge": 0.19,
        "pos": 0.62,
        "ev": 0.75,
        "skew": 0.0,
        "term_m1_m3": 0.0,
        "gamma": 0.01,
        "vega": 0.14,
        "theta": -0.012,
        "margin_requirement": 580.0,
    },
]


@pytest.mark.parametrize(
    "strategy",
    ["short_put_spread", "iron_condor"],
)
def test_generator_uses_pipeline_selection(monkeypatch, strategy):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    reload_selection()
    monkeypatch.setattr(
        "tomic.analysis.scoring.calculate_score", lambda *_, **__: (1.0, [])
    )
    monkeypatch.setattr("tomic.analysis.scoring.passes_risk", lambda *_, **__: True)
    criteria = load_criteria()
    rules = load_strategy_rules(strategy, {})
    filter_config = load_filter_config(criteria=criteria, rules=rules)
    selector = StrikeSelector(config=filter_config, criteria=criteria)
    selected = selector.select(list(BASE_CHAIN))
    assert selected, "selector returned no options"

    config_data = app_config._load_yaml(CONFIG_PATH)
    proposals, reasons = generate_strategy_candidates(
        "AAA",
        strategy,
        selected,
        atr=1.0,
        config=config_data,
        spot=100.0,
    )
    assert proposals, f"no proposals generated: {reasons}"

    selected_keys = {
        (str(opt.get("expiry")), float(opt.get("strike")), str(opt.get("type")).lower())
        for opt in selected
    }

    for proposal in proposals:
        for leg in proposal.legs:
            if leg.get("position") == -1:
                key = (
                    str(leg.get("expiry")),
                    float(leg.get("strike")),
                    str(leg.get("type")).lower(),
                )
                assert key in selected_keys

