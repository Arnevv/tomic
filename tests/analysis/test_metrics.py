import math
from tomic.strategy_candidates import _metrics
from tomic.strategies import StrategyName


def test_metrics_iron_condor():
    legs = [
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": -1, "mid": 1.2, "model": 1.2, "delta": 0.2},
        {"type": "C", "strike": 65, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": 0.1},
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": -0.2},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.3, "model": 0.3, "delta": -0.1},
    ]
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert reasons == []
    assert metrics is not None
    assert math.isclose(metrics["credit"], 150.0)
    assert math.isclose(metrics["margin"], 350.0)
    assert metrics["rom"] is not None
    assert math.isclose(metrics["ev_pct"], 14.285714285714285)
    assert math.isclose(metrics["score"], 48.29)


def test_metrics_atm_iron_butterfly():
    legs = [
        {"type": "C", "strike": 55, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": 0.4},
        {"type": "P", "strike": 55, "expiry": "2025-08-01", "position": -1, "mid": 1.2, "model": 1.2, "delta": -0.4},
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": 1, "mid": 0.3, "model": 0.3, "delta": 0.2},
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.2},
    ]
    metrics, reasons = _metrics(StrategyName.ATM_IRON_BUTTERFLY, legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_short_put_spread():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.5, "model": 1.5, "delta": -0.3},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.5, "model": 0.5, "delta": -0.1},
    ]
    metrics, reasons = _metrics(StrategyName.SHORT_PUT_SPREAD, legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_short_call_spread():
    legs = [
        {"type": "C", "strike": 60, "expiry": "2025-08-01", "position": -1, "mid": 1.5, "model": 1.5, "delta": 0.4},
        {"type": "C", "strike": 65, "expiry": "2025-08-01", "position": 1, "mid": 0.5, "model": 0.5, "delta": 0.2},
    ]
    metrics, reasons = _metrics(StrategyName.SHORT_CALL_SPREAD, legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_naked_put():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 1.0, "model": 1.0, "delta": -0.3},
    ]
    metrics, reasons = _metrics(StrategyName.NAKED_PUT, legs)
    assert metrics is None
    assert "negatieve EV of score" in reasons


def test_metrics_naked_put_requires_positive_credit():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": 1, "mid": 1.0, "model": 1.0, "delta": -0.3},
    ]
    metrics, reasons = _metrics(StrategyName.NAKED_PUT, legs)
    assert metrics is None
    assert reasons == ["negatieve credit"]


def test_metrics_backspread_put():
    legs = [
        {"type": "P", "strike": 50, "expiry": "2025-08-01", "position": -1, "mid": 0.8, "model": 0.8, "delta": -0.3},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.15},
        {"type": "P", "strike": 45, "expiry": "2025-08-01", "position": 1, "mid": 0.4, "model": 0.4, "delta": -0.15},
    ]
    metrics, reasons = _metrics(StrategyName.BACKSPREAD_PUT, legs, 50.0)
    assert metrics is not None
    assert reasons == []
    assert math.isclose(metrics["margin"], 500.0)
    assert metrics["max_loss"] == -500.0
    assert metrics["rom"] is not None
    assert metrics["ev_pct"] is not None
    assert metrics["profit_estimated"] is True


def test_metrics_rejects_short_leg_close_fallback():
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
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is None
    assert reasons == ["short legs vereisen true/parity mid"]


def test_metrics_parity_mid_treated_as_real_mid():
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
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is not None
    assert metrics.get("fallback") is None
    assert "fallback naar close gebruikt voor midprijs" not in reasons
    assert all("parity" not in reason for reason in reasons)


def test_metrics_rejects_short_leg_model_fallback():
    legs = [
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.2,
            "model": 1.2,
            "delta": 0.2,
            "mid_fallback": "model",
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
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is None
    assert reasons == ["short legs vereisen true/parity mid"]


def test_metrics_rejects_excessive_long_fallbacks():
    legs = [
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.2,
            "model": 1.2,
            "delta": 0.2,
        },
        {
            "type": "C",
            "strike": 65,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.4,
            "model": 0.4,
            "delta": 0.1,
            "mid_fallback": "model",
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
            "mid_fallback": "close",
        },
        {
            "type": "P",
            "strike": 40,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.2,
            "model": 0.2,
            "delta": -0.05,
            "mid_fallback": "close",
        },
    ]
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is None
    assert reasons == ["te veel fallbacks op long legs (max 2 toegestaan)"]
