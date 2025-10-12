from contextlib import nullcontext

import pytest

from tomic.strategy_candidates import generate_strategy_candidates


@pytest.mark.parametrize(
    "cfg,expect_warn",
    [
        (
            {
                "strategies": {
                    "iron_condor": {
                        "strike_to_strategy_config": {
                            "short_call_delta_range": [0.35, 0.45],
                            "short_put_delta_range": [-0.35, -0.25],
                            "wing_sigma_multiple": 0.35,
                            "use_ATR": False,
                        }
                    }
                }
            },
            False,
        ),
        (
            {
                "strategies": {
                    "iron_condor": {
                        "strike_config": {
                            "short_call_multiplier": [0.35, 0.45],
                            "short_put_multiplier": [-0.35, -0.25],
                            "wing_width": 0.35,
                            "use_ATR": False,
                        }
                    }
                }
            },
            True,
        ),
    ],
)
def test_iron_condor_negative_credit_rejected(cfg, expect_warn):
    chain = [
        {"expiry": "20260101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.1, "delta": 0.4, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 120, "type": "C", "bid": 2.9, "ask": 3.1, "delta": 0.2, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.2, "delta": -0.3, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 80, "type": "P", "bid": 2.8, "ask": 3.2, "delta": -0.1, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
    ]
    ctx = pytest.warns(DeprecationWarning) if expect_warn else nullcontext()
    with ctx:
        props, reasons = generate_strategy_candidates(
            "AAA", "iron_condor", chain, 1.0, config=cfg, spot=100.0
        )
    assert not props
    assert "negatieve credit" in reasons


@pytest.mark.parametrize(
    "cfg,expect_warn",
    [
        (
            {
                "strategies": {
                    "short_call_spread": {
                        "strike_to_strategy_config": {
                            "short_call_delta_range": [0.35, 0.45],
                            "long_leg_distance_points": 0.1,
                            "use_ATR": False,
                        }
                    }
                }
            },
            False,
        ),
        (
            {
                "strategies": {
                    "short_call_spread": {
                        "strike_config": {
                            "short_delta_range": [0.35, 0.45],
                            "long_call_distance_points": 0.1,
                            "use_ATR": False,
                        }
                    }
                }
            },
            True,
        ),
    ],
)
def test_short_call_spread_negative_credit_rejected(cfg, expect_warn):
    chain = [
        {"expiry": "20260101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.1, "delta": 0.4, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 120, "type": "C", "bid": 2.9, "ask": 3.1, "delta": 0.2, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
    ]
    ctx = pytest.warns(DeprecationWarning) if expect_warn else nullcontext()
    with ctx:
        props, reasons = generate_strategy_candidates(
            "AAA", "short_call_spread", chain, 1.0, config=cfg, spot=100.0
        )
    assert not props
    assert "negatieve credit" in reasons
