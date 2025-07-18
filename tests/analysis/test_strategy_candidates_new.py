import pytest
from tomic.strategies import iron_condor


def test_generate_strategy_candidates_requires_spot():
    chain = [{"expiry": "20250101", "strike": 100, "type": "C", "bid": 1, "ask": 1.2}]
    with pytest.raises(ValueError):
        iron_condor.generate("AAA", chain, {}, None, 1.0)


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
    props = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)
    if props:
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
    props = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert not props


def test_parity_mid_used_for_missing_bidask(monkeypatch):
    import pandas as pd
    if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
        pytest.skip("pandas not available", allow_module_level=True)

    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "C",
            "delta": 0.4,
            "edge": 0.1,
            "model": 0,
            "mid": None,
        },
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "P",
            "delta": -0.4,
            "edge": 0.1,
            "model": 0,
            "mid": 10.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 120,
            "type": "C",
            "delta": 0.2,
            "edge": 0.1,
            "model": 0,
            "mid": 1.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 90,
            "type": "P",
            "delta": -0.3,
            "edge": 0.1,
            "model": 0,
            "mid": 1.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 80,
            "type": "P",
            "delta": -0.1,
            "edge": 0.1,
            "model": 0,
            "mid": 0.5,
        },
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
    props = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert props
    sc_leg = next(
        (
            l
            for l in props[0].legs
            if l.get("position") < 0
            and (l.get("type") or l.get("right")) == "C"
            and float(l.get("strike")) == 110
        ),
        None,
    )
    assert sc_leg is not None
    assert sc_leg.get("mid_from_parity") is True
    assert sc_leg.get("mid") is not None
