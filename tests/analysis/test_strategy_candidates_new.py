import pytest
from tomic.strategy_candidates import generate_strategy_candidates


def test_generate_strategy_candidates_requires_spot():
    chain = [{"expiry": "20250101", "strike": 100, "type": "C", "bid": 1, "ask": 1.2}]
    with pytest.raises(ValueError):
        generate_strategy_candidates("AAA", "iron_condor", chain, 1.0, {}, None, interactive_mode=False)


def test_generate_strategy_candidates_with_strings():
    chain = [
        {"expiry": "20250101", "strike": "110", "type": "C", "bid": "1", "ask": "1.2", "delta": "0.4", "edge": "0.1", "model": "0"},
        {"expiry": "20250101", "strike": "120", "type": "C", "bid": "0.5", "ask": "0.7", "delta": "0.2", "edge": "0.1", "model": "0"},
        {"expiry": "20250101", "strike": "90", "type": "P", "bid": "1.0", "ask": "1.1", "delta": "-0.3", "edge": "0.1", "model": "0"},
        {"expiry": "20250101", "strike": "80", "type": "P", "bid": "0.4", "ask": "0.6", "delta": "-0.1", "edge": "0.1", "model": "0"},
    ]
    cfg = {
        "strategies": {
            "iron_condor": {
                "strike_to_strategy_config": {
                    "short_call_multiplier": [10],
                    "short_put_multiplier": [10],
                    "wing_width": 10,
                    "use_ATR": False,
                }
            }
        }
    }
    props, reasons = generate_strategy_candidates(
        "AAA",
        "iron_condor",
        chain,
        1.0,
        cfg,
        100.0,
        interactive_mode=False,
    )
    assert reasons == []
    assert props
    for leg in props[0].legs:
        assert isinstance(leg["strike"], float)
        assert isinstance(leg["bid"], float)
        assert isinstance(leg["ask"], float)


def test_generate_strategy_candidates_missing_metrics_reason():
    chain = [
        {"expiry": "20250101", "strike": 110, "type": "C", "bid": 0.5, "ask": 0.7},
        {"expiry": "20250101", "strike": 120, "type": "C", "bid": 2.0, "ask": 2.2},
        {"expiry": "20250101", "strike": 90, "type": "P", "bid": 0.6, "ask": 0.8},
        {"expiry": "20250101", "strike": 80, "type": "P", "bid": 1.5, "ask": 1.7},
    ]
    cfg = {
        "strategies": {
            "iron_condor": {
                "strike_to_strategy_config": {
                    "short_call_multiplier": [10],
                    "short_put_multiplier": [10],
                    "wing_width": 10,
                    "use_ATR": False,
                }
            }
        }
    }
    props, reasons = generate_strategy_candidates(
        "AAA",
        "iron_condor",
        chain,
        1.0,
        cfg,
        100.0,
        interactive_mode=False,
    )
    assert not props
    assert (
        "Edge, model of delta ontbreekt — metrics kunnen niet worden berekend"
        in reasons
    )
