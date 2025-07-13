import math
from tomic.strategy_candidates import _metrics


def test_calendar_metrics_allows_negative_credit():
    legs = [
        {
            "type": "C",
            "strike": 55,
            "expiry": "2025-08-15",
            "position": -1,
            "mid": 0.40,
            "model": 0.40,
            "delta": -0.3,
        },
        {
            "type": "C",
            "strike": 55,
            "expiry": "2025-09-19",
            "position": 1,
            "mid": 0.60,
            "model": 0.60,
            "delta": 0.25,
        },
    ]
    metrics, reasons = _metrics("calendar", legs)
    assert metrics is not None
    assert "ROM kon niet worden berekend" in reasons[0]
    assert math.isclose(metrics["credit"], -20.0)
    assert metrics["margin"] is not None
