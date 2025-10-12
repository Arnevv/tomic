import math
from tomic.analysis import scoring
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
        },
        {
            "type": "C",
            "strike": 65,
            "expiry": "2025-08-01",
            "position": 1,
            "mid": 0.4,
            "model": 0.4,
            "delta": 0.1,
            "mid_fallback": "close",
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
            "mid_fallback": "parity_true",
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
    assert "fallback" not in metrics
    assert reasons == []


def test_metrics_reports_model_fallback():
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
        },
    ]
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is not None
    assert metrics.get("fallback") == "model"
    assert "model-mid gebruikt" in reasons


def test_metrics_short_fallbacks_warn_but_allowed(monkeypatch):
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
            "mid_fallback": "parity_close",
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
    captured: list[str] = []

    def fake_warning(message: str, *args, **kwargs) -> None:
        captured.append(str(message))

    monkeypatch.setattr(scoring.logger, "warning", fake_warning)

    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is not None
    assert all("te veel fallback-legs" not in reason for reason in reasons)
    assert any("short leg fallback" in msg for msg in captured)


def test_metrics_rejects_when_long_fallback_limit_exceeded(monkeypatch):
    original_cfg = scoring.cfg_get

    def fake_cfg(name, default=None):
        if name == "MID_FALLBACK_MAX_PER_4":
            return 1
        return original_cfg(name, default)

    monkeypatch.setattr(scoring, "cfg_get", fake_cfg)

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
            "mid_fallback": "close",
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
            "mid_fallback": "model",
        },
    ]
    metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs)
    assert metrics is None
    assert reasons and reasons[0].startswith("te veel fallback-legs op long wings")


def test_short_call_spread_logs_short_fallback():
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
    ]
    metrics, reasons = _metrics(StrategyName.SHORT_CALL_SPREAD, legs)
    assert metrics is None
    assert "model-mid gebruikt" in reasons
    assert any(reason.lower() == "negatieve ev of score" for reason in reasons)


def test_calendar_rejects_model_long_fallback():
    legs = [
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-08-01",
            "position": -1,
            "mid": 1.2,
            "model": 1.2,
            "delta": 0.25,
        },
        {
            "type": "C",
            "strike": 60,
            "expiry": "2025-09-01",
            "position": 1,
            "mid": 0.8,
            "model": 0.8,
            "delta": 0.2,
            "mid_fallback": "model",
        },
    ]
    metrics, reasons = _metrics(StrategyName.CALENDAR, legs)
    assert metrics is None
    assert reasons and reasons[0].startswith("calendar long leg vereist parity of close")
