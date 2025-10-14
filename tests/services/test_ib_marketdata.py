from __future__ import annotations

import math

from tomic.services.ib_marketdata import IBMarketDataService


def test_apply_snapshot_updates_mid_and_greeks():
    service = IBMarketDataService()
    leg = {
        "symbol": "AAA",
        "expiry": "20240119",
        "strike": 100.0,
        "type": "call",
        "position": -1,
    }
    snapshot = {"bid": 1.1, "ask": 1.3, "delta": -0.25, "theta": -0.05, "vega": 0.12}
    service._apply_snapshot(leg, snapshot)  # type: ignore[attr-defined]
    assert math.isclose(leg["mid"], 1.2, rel_tol=1e-6)
    assert math.isclose(leg["delta"], -0.25, rel_tol=1e-6)
    assert math.isclose(leg["theta"], -0.05, rel_tol=1e-6)
    assert math.isclose(leg["vega"], 0.12, rel_tol=1e-6)
    assert "missing_edge" not in leg


def test_apply_snapshot_marks_missing_edge_when_no_prices():
    service = IBMarketDataService()
    leg = {
        "symbol": "AAA",
        "expiry": "20240119",
        "strike": 100.0,
        "type": "put",
        "position": -1,
    }
    service._apply_snapshot(leg, {})  # type: ignore[attr-defined]
    assert leg.get("missing_edge") is True
    assert "mid" not in leg
