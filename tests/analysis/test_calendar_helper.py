import pytest
import tomic.strategy_candidates as sc
from tomic.strategies import calendar


def test_options_by_strike_filters_missing_mid():
    chain = [
        {"expiry": "2025-01-01", "strike": 100, "type": "C", "bid": 1.0, "ask": 1.2},
        {"expiry": "2025-02-01", "strike": 100, "type": "C", "bid": 0, "ask": 0, "close": 0.8},
        {"expiry": "2025-03-01", "strike": 100, "type": "C", "bid": 0, "ask": 0, "close": None},
    ]
    res = sc._options_by_strike(chain, "C")
    assert sorted(res.keys()) == [100.0]
    assert set(res[100.0]) == {"2025-01-01", "2025-02-01"}


def test_calendar_generates_from_valid_pairs(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2025-01-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.1, "delta": 0.3, "edge": 0.1, "iv": 0.25},
        {"expiry": "2025-03-01", "strike": 105, "type": "C", "bid": 1, "ask": 1.3, "delta": 0.2, "edge": 0.1, "iv": 0.3},
    ]
    cfg = {
        "strategies": {
            "calendar": {
                "strike_to_strategy_config": {
                    "expiry_gap_min_days": 20,
                    "base_strikes_relative_to_spot": [0],
                    "use_ATR": False,
                }
            }
        }
    }
    props, _ = calendar.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)
    if props:
        assert props[0].legs[0]["strike"] == 100.0


def test_calendar_logs_skip_on_missing_mid(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2025-01-01", "strike": 100, "type": "C", "bid": 1, "ask": 1.2, "delta": 0.4, "edge": 0.1, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 100, "type": "C", "bid": 0, "ask": 0, "close": None, "delta": 0.3, "edge": 0.1, "iv": 0.25},
    ]
    cfg = {
        "strategies": {
            "calendar": {
                "strike_to_strategy_config": {
                    "expiry_gap_min_days": 20,
                    "base_strikes_relative_to_spot": [0],
                    "use_ATR": False,
                }
            }
        }
    }
    infos: list[str] = []
    monkeypatch.setattr(
        sc.logger, "info", lambda msg, *a, **k: infos.append(msg.format(*a))
    )
    props, _ = calendar.generate("AAA", chain, cfg, 100.0, 1.0)
    assert not props
