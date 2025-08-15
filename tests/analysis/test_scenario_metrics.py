import pytest
from tomic.strategy_candidates import _metrics
from tomic.logutils import logger
from tomic.criteria import load_criteria


SCENARIOS = [
    (
        "calendar",
        [
            {
                "type": "C",
                "strike": 55,
                "expiry": "2025-08-15",
                "position": -1,
                "mid": 0.40,
                "model": 0.40,
                "delta": -0.30,
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
        ],
        55.0,
        "Spot blijft ±2%",
    ),
    (
        "backspread_put",
        [
            {
                "type": "P",
                "strike": 50,
                "expiry": "2025-08-01",
                "position": -1,
                "mid": 1.00,
                "model": 1.00,
                "delta": -0.20,
            },
            {
                "type": "P",
                "strike": 45,
                "expiry": "2025-08-01",
                "position": 1,
                "mid": 0.50,
                "model": 0.50,
                "delta": 0.10,
            },
            {
                "type": "P",
                "strike": 40,
                "expiry": "2025-08-01",
                "position": 1,
                "mid": 0.30,
                "model": 0.30,
                "delta": 0.05,
            },
        ],
        50.0,
        "Explosieve daling (spot -15%)",
    ),
    (
        "ratio_spread",
        [
            {
                "expiry": "2025-08-01",
                "strike": 66,
                "type": "C",
                "position": -1,
                "mid": 1.20,
                "model": 1.20,
                "delta": 0.60,
            },
            {
                "expiry": "2025-08-01",
                "strike": 68,
                "type": "C",
                "position": 2,
                "mid": 0.60,
                "model": 0.60,
                "delta": 0.30,
            },
        ],
        66.0,
        "Spot beweegt richting short strike",
    ),
]


@pytest.mark.parametrize("strategy,legs,spot,label", SCENARIOS)
def test_scenario_metrics(strategy, legs, spot, label):
    from io import StringIO

    buf = StringIO()
    handler_id = logger.add(buf, level="INFO")
    metrics, reasons = _metrics(strategy, legs, spot, criteria=load_criteria())
    logger.remove(handler_id)
    assert metrics is not None
    assert reasons == []
    assert metrics.get("ev") is not None
    assert metrics.get("rom") is not None
    assert metrics.get("profit_estimated") is True
    info = metrics.get("scenario_info") or {}
    assert info.get("scenario_label") == label
    assert label in buf.getvalue()


def test_missing_scenario(monkeypatch):
    def fake_cfg_get(key, default=None):
        if key == "STRATEGY_SCENARIOS":
            return {}
        return default

    monkeypatch.setattr("tomic.metrics.cfg_get", fake_cfg_get)

    legs = [
        {
            "type": "C",
            "strike": 55,
            "expiry": "2025-08-15",
            "position": -1,
            "mid": 0.40,
            "model": 0.40,
            "delta": -0.30,
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

    metrics, reasons = _metrics("calendar", legs, 55.0, criteria=load_criteria())
    assert metrics is not None
    assert metrics.get("ev") is None
    assert metrics.get("rom") is None
    info = metrics.get("scenario_info") or {}
    assert info.get("error") == "no scenario defined"
