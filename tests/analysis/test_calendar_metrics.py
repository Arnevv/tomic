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
    metrics, reasons = _metrics("calendar", legs, 55.0)
    assert metrics is not None
    assert reasons == []
    assert math.isclose(metrics["credit"], -20.0)
    assert metrics["margin"] is not None
    assert metrics["rom"] is not None
    assert metrics["ev_pct"] is not None
    assert metrics["profit_estimated"] is True
    assert metrics["scenario_info"]["preferred_move"] == "flat"


def test_calendar_rejects_short_fallback():
    legs = [
        {
            "type": "C",
            "strike": 55,
            "expiry": "2025-08-15",
            "position": -1,
            "mid": 0.40,
            "model": 0.40,
            "delta": -0.3,
            "mid_fallback": "close",
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
    metrics, reasons = _metrics("calendar", legs, 55.0)
    assert metrics is None
    assert reasons == ["short legs vereisen true/parity mid"]


def test_calendar_rejects_model_long_fallback():
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
            "mid_fallback": "model",
        },
    ]
    metrics, reasons = _metrics("calendar", legs, 55.0)
    assert metrics is None
    assert reasons == ["calendar long leg vereist parity of close mid"]


def test_calendar_allows_close_long_fallback():
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
            "mid_fallback": "close",
        },
    ]
    metrics, reasons = _metrics("calendar", legs, 55.0)
    assert metrics is not None
    assert reasons == ["fallback naar close gebruikt voor midprijs"]
