from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import pytest

from tomic.services.pipeline_refresh import (
    PipelineStats,
    Proposal as RefreshProposal,
    RefreshResult,
    RefreshSource,
    build_proposal_from_entry,
)
from tomic.services.proposal_details import build_proposal_core, build_proposal_viewmodel


@pytest.fixture
def sample_refresh_result() -> RefreshResult:
    entry = {
        "strategy": "iron_condor",
        "metrics": {
            "credit": 0.70,
            "margin": 4.0,
            "max_profit": 0.70,
            "max_loss": 3.30,
            "score": 0.52,
            "ev": 0.18,
            "rom": 0.16,
            "pos": 0.54,
            "breakevens": [95.5, 89.5],
        },
        "legs": [
            {
                "expiry": "2025-01-17",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "bid": 1.45,
                "ask": 1.55,
                "mid": 1.5,
                "iv": 0.25,
                "delta": -0.30,
                "gamma": 0.012,
                "vega": -0.18,
                "theta": 0.04,
            },
            {
                "expiry": "2025-01-17",
                "strike": 90.0,
                "type": "put",
                "position": -1,
                "bid": 0.75,
                "ask": 0.85,
                "mid": 0.8,
                "iv": 0.28,
                "delta": 0.12,
                "gamma": -0.006,
                "vega": 0.09,
                "theta": -0.02,
            },
        ],
        "meta": {"symbol": "AAA"},
    }
    proposal = build_proposal_from_entry(entry)
    assert proposal is not None
    source = RefreshSource(index=0, entry=entry, symbol="AAA")
    core = build_proposal_core(proposal, symbol="AAA", entry=entry)
    refresh_proposal = RefreshProposal(
        proposal=proposal,
        source=source,
        reasons=[],
        missing_quotes=[],
        core=core,
        accepted=True,
    )
    stats = PipelineStats(total=1, accepted=1, rejected=0, failed=0, duration=0.0, attempts=1, retries=0)
    return RefreshResult(accepted=[refresh_proposal], rejections=[], stats=stats)


def test_build_proposal_viewmodel_without_nan(sample_refresh_result: RefreshResult) -> None:
    candidate = sample_refresh_result.accepted[0]
    vm = build_proposal_viewmodel(
        candidate,
        {"next_earnings": date(2025, 1, 10), "days_until_earnings": 5},
    )

    for leg in vm.legs:
        for attr in ("bid", "ask", "mid", "iv", "delta", "gamma", "vega", "theta"):
            value = getattr(leg, attr)
            if value is not None:
                assert math.isfinite(value)

    summary = vm.summary
    for value in (
        summary.credit,
        summary.margin,
        summary.max_profit,
        summary.max_loss,
        summary.pos,
        summary.ev,
        summary.rom,
        summary.score,
        summary.risk_reward,
    ):
        if value is not None:
            assert math.isfinite(value)

    assert vm.core.symbol == "AAA"
    assert vm.accepted is True
    assert vm.earnings.next_earnings == date(2025, 1, 10)
    assert vm.earnings.occurs_before_expiry is False


def test_build_proposal_viewmodel_marks_missing_quotes_pending(
    sample_refresh_result: RefreshResult,
) -> None:
    candidate = replace(sample_refresh_result.accepted[0], missing_quotes=["195"], accepted=True)

    vm = build_proposal_viewmodel(candidate, None)

    assert vm.accepted is None
    assert "⚠️ Geen verse quotes voor: 195" in vm.warnings
