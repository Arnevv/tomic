from tomic.strategy_candidates import generate_strategy_candidates


def test_iron_condor_negative_credit_rejected():
    chain = [
        {"expiry": "20260101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.1, "delta": 0.4, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 120, "type": "C", "bid": 2.9, "ask": 3.1, "delta": 0.2, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.2, "delta": -0.3, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 80, "type": "P", "bid": 2.8, "ask": 3.2, "delta": -0.1, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
    ]
    cfg = {
        "strategies": {
            "iron_condor": {
                "strike_to_strategy_config": {
                    "short_call_multiplier": [10],
                    "short_put_multiplier": [10],
                    "long_call_distance_points": [10],
                    "long_put_distance_points": [10],
                    "use_ATR": False,
                }
            }
        }
    }
    props, reasons = generate_strategy_candidates("AAA", "iron_condor", chain, 1.0, config=cfg, spot=100.0)
    assert not props
    assert "negatieve credit" in reasons


def test_short_call_spread_negative_credit_rejected():
    chain = [
        {"expiry": "20260101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.1, "delta": 0.4, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
        {"expiry": "20260101", "strike": 120, "type": "C", "bid": 2.9, "ask": 3.1, "delta": 0.2, "edge": 0.1, "iv": 0.2, "volume": 100, "open_interest": 1000},
    ]
    cfg = {
        "strategies": {
            "short_call_spread": {
                "strike_to_strategy_config": {
                    "short_call_delta_range": [0.35, 0.45],
                    "long_call_distance_points": [10],
                    "use_ATR": False,
                }
            }
        }
    }
    props, reasons = generate_strategy_candidates("AAA", "short_call_spread", chain, 1.0, config=cfg, spot=100.0)
    assert not props
    assert "negatieve credit" in reasons
