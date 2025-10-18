from __future__ import annotations

import math
from typing import Any, Mapping

from tomic.services.pipeline_refresh import (
    IncompleteData,
    PipelineStats,
    RefreshContext,
    RefreshParams,
    build_proposal_from_entry,
    refresh_pipeline,
)
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.services.ib_marketdata import SnapshotResult
from tomic.strategy.reasons import ReasonDetail


def _make_entry(symbol: str, strategy: str) -> Mapping[str, Any]:
    return {
        "status": "reject",
        "strategy": strategy,
        "metrics": {"score": 10.0, "pos": 0.5},
        "legs": [
            {
                "symbol": symbol,
                "expiry": "2025-12-19",
                "type": "call",
                "strike": 420.0,
                "position": -1,
            }
        ],
        "meta": {"symbol": symbol},
    }


def test_build_proposal_from_entry_sets_symbol():
    entry = {
        "strategy": "iron_condor",
        "metrics": {"score": 1.0},
        "legs": [
            {
                "expiry": "2025-11-21",
                "type": "call",
                "strike": 490.0,
                "position": -1,
            }
        ],
        "meta": {"symbol": "AAA"},
    }

    proposal = build_proposal_from_entry(entry)

    assert isinstance(proposal, StrategyProposal)
    assert proposal.legs[0]["symbol"] == "AAA"


def test_refresh_pipeline_accepts_and_rejects(monkeypatch):
    entries = [_make_entry("AAA", "iron_condor"), _make_entry("BBB", "short_put")] 

    calls: list[str] = []

    def fake_fetch(proposal: StrategyProposal, **kwargs: Any) -> SnapshotResult:
        calls.append(proposal.strategy)
        accepted = proposal.strategy == "iron_condor"
        reasons = []
        if not accepted:
            reasons = [ReasonDetail(code="test", message="niet goed", data={})]
        return SnapshotResult(
            proposal=proposal,
            reasons=reasons,
            accepted=accepted,
            missing_quotes=[],
        )

    params = RefreshParams(entries=entries, fetch_snapshot=fake_fetch)
    result = refresh_pipeline(RefreshContext(trace_id="abc"), params=params)

    assert calls == ["iron_condor", "short_put"]
    assert len(result.accepted) == 1
    assert len(result.rejections) == 1
    assert result.accepted[0].proposal.strategy == "iron_condor"
    assert result.rejections[0].proposal.strategy == "short_put"
    assert isinstance(result.stats, PipelineStats)
    assert math.isclose(result.stats.duration, result.stats.duration, rel_tol=1e-9)


def test_refresh_pipeline_retries_and_errors(monkeypatch):
    entry = _make_entry("AAA", "iron_condor")

    attempts: list[str] = []

    def flaky_fetch(proposal: StrategyProposal, **kwargs: Any) -> SnapshotResult:
        if not attempts:
            attempts.append("fail")
            raise TimeoutError("timeout")
        attempts.append("ok")
        return SnapshotResult(
            proposal=proposal,
            reasons=[],
            accepted=True,
            missing_quotes=[],
        )

    params = RefreshParams(
        entries=[entry],
        fetch_snapshot=flaky_fetch,
        max_attempts=2,
        retry_delay=0.0,
    )
    result = refresh_pipeline(RefreshContext(trace_id="retry"), params=params)

    assert attempts == ["fail", "ok"]
    assert result.stats.attempts == 2
    assert result.stats.retries == 1
    assert len(result.accepted) == 1

    bad_entry = {"strategy": "broken", "metrics": {}, "legs": []}
    params = RefreshParams(entries=[bad_entry])
    failure = refresh_pipeline(RefreshContext(), params=params)

    assert not failure.accepted
    assert failure.rejections
    assert isinstance(failure.rejections[0].error, IncompleteData)

