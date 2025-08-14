import math
from tomic.strategy_candidates import _metrics


def test_metrics_iron_condor():
    legs = [
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": -1, "mid": 1.2, "model": 1.2, "delta": 0.2},
        {"type": "C", "strike": 65, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": 0.1},
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": -0.2},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.3, "model": 0.3, "delta": -0.1},
    ]
    metrics, reasons = _metrics("iron_condor", legs)
    assert reasons == []
    assert metrics is not None
    assert math.isclose(metrics["credit"], 150.0)
    assert math.isclose(metrics["margin"], 500.0)
    assert metrics["rom"] is not None
    assert math.isclose(metrics["ev_pct"], 10.0)
    assert math.isclose(metrics["score"], 41.0)


def test_metrics_atm_iron_butterfly():
    legs = [
        {"type": "C", "strike": 55, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": 0.4},
        {"type": "P", "strike": 55, "expiry": "2025-08-01", "position": -1, "mid": 1.2, "model": 1.2, "delta": -0.4},
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": 1, "mid": 0.3, "model": 0.3, "delta": 0.2},
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.2},
    ]
    metrics, reasons = _metrics("atm_iron_butterfly", legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_bull_put_spread():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.5, "model": 1.5, "delta": -0.3},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.5, "model": 0.5, "delta": -0.1},
    ]
    metrics, reasons = _metrics("bull put spread", legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_short_call_spread():
    legs = [
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": -1, "mid": 1.5, "model": 1.5, "delta": 0.4},
        {"type": "C", "strike": 65, "expiry": "2025-08-01", "position": 1, "mid": 0.5, "model": 0.5, "delta": 0.2},
    ]
    metrics, reasons = _metrics("short_call_spread", legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_naked_put():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": -0.3},
    ]
    metrics, reasons = _metrics("naked_put", legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_backspread_put():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 0.8, "model": 0.8, "delta": -0.3},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.15},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.15},
    ]
    metrics, reasons = _metrics("backspread_put", legs, 50.0)
    assert metrics is not None
    assert reasons == []
    assert math.isclose(metrics["margin"], 500.0)
    assert metrics["max_loss"] == -500.0
    assert metrics["rom"] is not None
    assert metrics["ev_pct"] is not None
    assert metrics["profit_estimated"] is True


def test_metrics_reports_close_fallback():
    legs = [
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.2,
            "model": 1.2,
            "delta": 0.2,
            "mid_fallback": "close",
        },
        {
            "type": "C",
            "strike": 65,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.4,
            "model": 0.4,
            "delta": 0.1,
        },
        {
            "type": "P",
            "strike": 50,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.0,
            "model": 1.0,
            "delta": -0.2,
        },
        {
            "type": "P",
            "strike": 45,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.3,
            "model": 0.3,
            "delta": -0.1,
        },
    ]
    metrics, reasons = _metrics("iron_condor", legs)
    assert metrics is not None
    assert metrics.get("fallback") == "close"
    assert "fallback naar close gebruikt voor midprijs" in reasons


def test_metrics_reports_parity_fallback():
    legs = [
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.2,
            "model": 1.2,
            "delta": 0.2,
            "mid_fallback": "parity",
        },
        {
            "type": "C",
            "strike": 65,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.4,
            "model": 0.4,
            "delta": 0.1,
        },
        {
            "type": "P",
            "strike": 50,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.0,
            "model": 1.0,
            "delta": -0.2,
        },
        {
            "type": "P",
            "strike": 45,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.3,
            "model": 0.3,
            "delta": -0.1,
        },
    ]
    metrics, reasons = _metrics("iron_condor", legs)
    assert metrics is not None
    assert metrics.get("fallback") == "parity"
    assert "fallback naar close gebruikt voor midprijs" not in reasons
