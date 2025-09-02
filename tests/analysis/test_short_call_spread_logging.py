from types import SimpleNamespace
from tomic.strategies import short_call_spread
from tomic import logutils


def _chain():
    return [
        {
            "expiry": "2025-01-01",
            "strike": 90,
            "type": "put",
            "bid": 1.0,
            "ask": 1.1,
            "delta": -0.3,
            "edge": 0.1,
            "model": 0.1,
            "iv": 0.2,
        }
    ]


def test_short_call_spread_expiry_logging(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "long_leg_distance_points": 5,
        }
    }
    messages: list[str] = []
    monkeypatch.setattr(logutils, "logger", SimpleNamespace(info=lambda m: messages.append(m)))
    short_call_spread.generate("AAA", _chain(), cfg, 100.0, 1.0)
    assert any("short optie ontbreekt" in m and "expiry=2025-01-01" in m for m in messages)
