from tomic.strategies import calendar


def test_calendar_candidates_with_valid_pair(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2024-07-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2},
        {"expiry": "2024-08-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.1, "delta": 0.3, "edge": 0.1, "iv": 0.25},
    ]
    cfg = {
        "strategies": {
            "calendar": {
                "strike_to_strategy_config": {
                    "expiry_gap_min_days": 15,
                    "base_strikes_relative_to_spot": [0],
                    "use_ATR": False,
                }
            }
        }
    }
    props, _ = calendar.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)


def test_calendar_candidates_no_pairs(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2024-07-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2},
        {"expiry": "2024-08-01", "strike": 105, "type": "C", "bid": 1, "ask": 1.1, "delta": 0.3, "edge": 0.1, "iv": 0.25},
        {"expiry": "2024-09-01", "strike": 100, "type": "C", "bid": 0, "ask": 0, "close": None, "delta": 0.35, "edge": 0.1, "iv": 0.3},
    ]
    cfg = {
        "strategies": {
            "calendar": {
                "strike_to_strategy_config": {
                    "expiry_gap_min_days": 15,
                    "base_strikes_relative_to_spot": [0],
                    "use_ATR": False,
                }
            }
        }
    }
    props, _ = calendar.generate("AAA", chain, cfg, 100.0, 1.0)
    assert not props


def test_calendar_candidates_put_fallback(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2024-07-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2},
        {"expiry": "2024-07-01", "strike": 100, "type": "P", "bid": 1, "ask": 1.2, "delta": -0.4, "edge": 0.1, "iv": 0.2, "model": 1.1},
        {"expiry": "2024-08-01", "strike": 100, "type": "P", "bid": 1, "ask": 1.1, "delta": -0.3, "edge": 0.1, "iv": 0.25, "model": 1.15},
    ]
    cfg = {
        "strategies": {
            "calendar": {
                "strike_to_strategy_config": {
                    "expiry_gap_min_days": 15,
                    "base_strikes_relative_to_spot": [0],
                    "use_ATR": False,
                }
            }
        }
    }
    props, _ = calendar.generate("AAA", chain, cfg, 100.0, 1.0)
    assert props and all(leg["type"] == "P" for leg in props[0].legs)
