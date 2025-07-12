import math
from tomic.strategy_candidates import _metrics


def test_ratio_spread_metrics_quantities():
    legs = [
        {
            "expiry": "2025-08-01",
            "strike": 66,
            "type": "C",
            "position": -1,
            "mid": 1.20,
            "model": 1.20,
            "delta": 0.6,
        },
        {
            "expiry": "2025-08-01",
            "strike": 68,
            "type": "C",
            "position": 2,
            "mid": 0.60,
            "model": 0.60,
            "delta": 0.3,
        },
    ]
    metrics, reasons = _metrics("ratio_spread", legs)
    assert reasons == []
    assert metrics is not None
    assert math.isclose(metrics["credit"], 0.0)
    assert math.isclose(metrics["margin"], 200.0)
    assert math.isclose(metrics["max_loss"], -200.0)
