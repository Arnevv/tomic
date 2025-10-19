from __future__ import annotations

import logging
import math

from tomic.services.ib_marketdata import IBMarketDataService, SnapshotResult, fetch_quote_snapshot
from tomic.services.strategy_pipeline import StrategyProposal


def test_apply_snapshot_updates_mid_and_greeks():
    service = IBMarketDataService()
    leg = {
        "symbol": "AAA",
        "expiry": "20240119",
        "strike": 100.0,
        "type": "call",
        "position": -1,
        "mid": 1.0,
        "mid_source": "close",
    }
    snapshot = {"bid": 1.1, "ask": 1.3, "delta": -0.25, "theta": -0.05, "vega": 0.12}
    log_entries: list[dict[str, float]] = []
    service._apply_snapshot(leg, snapshot, delta_log=log_entries, trigger="panel")  # type: ignore[attr-defined]
    assert math.isclose(leg["mid"], 1.2, rel_tol=1e-6)
    assert math.isclose(leg["delta"], 0.25, rel_tol=1e-6)
    assert math.isclose(leg["theta"], -0.05, rel_tol=1e-6)
    assert math.isclose(leg["vega"], 0.12, rel_tol=1e-6)
    assert "missing_edge" not in leg
    assert leg["mid_source"] == "true"
    assert leg["mid_reason"] == "ib_snapshot"
    assert leg["mid_refresh_trigger"] == "panel"
    assert math.isclose(leg["mid_previous"], 1.0, rel_tol=1e-6)
    assert math.isclose(leg["mid_delta"], 0.2, rel_tol=1e-6)
    assert log_entries and log_entries[0]["source_before"] == "close"


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
    assert "mid_refresh_timestamp" not in leg


def test_snapshot_disabled_when_generic_ticks_present():
    service = IBMarketDataService(generic_ticks="100,101", use_snapshot=True)
    assert service._should_use_snapshot() is False


def test_snapshot_respected_when_no_generic_ticks():
    service = IBMarketDataService(generic_ticks="", use_snapshot=True)
    assert service._should_use_snapshot() is True


def test_apply_snapshot_delta_logging(caplog):
    service = IBMarketDataService()
    leg = {
        "symbol": "BBB",
        "expiry": "20240119",
        "strike": 110.0,
        "type": "put",
        "position": -1,
        "mid": 0.8,
        "mid_source": "close",
    }
    caplog.set_level(logging.INFO)
    deltas: list[dict[str, float]] = []
    service._apply_snapshot(
        leg,
        {"bid": 0.9, "ask": 1.1, "delta": -0.35},
        delta_log=deltas,
        trigger="control_panel",
    )  # type: ignore[attr-defined]
    assert deltas and math.isclose(deltas[0]["delta"], 0.2, rel_tol=1e-6)
    assert leg["mid_source"] == "true"
    assert leg["mid_refresh_trigger"] == "control_panel"


def test_fetch_quote_snapshot_builds_governance_payload():
    proposal = StrategyProposal(
        strategy="iron_condor",
        legs=[
            {
                "symbol": "CCC",
                "expiry": "20250117",
                "strike": 120.0,
                "type": "call",
                "position": -1,
                "bid": 1.0,
                "ask": 1.2,
                "mid": 1.1,
                "mid_source": "close",
            }
        ],
        score=5.0,
        ev=100.0,
    )
    proposal.fallback_summary = {"close": 1}
    proposal.needs_refresh = True

    class DummyService:
        def refresh(self, proposal, **kwargs):  # type: ignore[no-untyped-def]
            for leg in proposal.legs:
                leg.update(
                    {
                        "bid": 1.2,
                        "ask": 1.4,
                        "mid": 1.3,
                        "mid_source": "true",
                        "missing_metrics": [],
                    }
                )
            proposal.score = 7.5
            proposal.ev = 140.0
            proposal.fallback_summary = {"true": len(proposal.legs)}
            proposal.needs_refresh = False
            return SnapshotResult(
                proposal=proposal,
                reasons=[],
                accepted=True,
                missing_quotes=[],
                delta_log=[{"before": 1.1, "after": 1.3, "delta": 0.2}],
            )

    result = fetch_quote_snapshot(
        proposal,
        trigger="panel",
        service=DummyService(),
    )

    assert result.trigger == "panel"
    assert result.metrics_delta
    assert math.isclose(result.metrics_delta["score"]["before"], 5.0, rel_tol=1e-6)
    assert math.isclose(result.metrics_delta["score"]["after"], 7.5, rel_tol=1e-6)
    assert math.isclose(result.metrics_delta["score"]["delta"], 2.5, rel_tol=1e-6)
    assert result.governance["mid_sources"][0] == "tradable"
    assert result.governance["needs_refresh"] is False
    assert proposal.needs_refresh is False
