import math

import pytest

from tomic.services.ib_marketdata import SnapshotResult, fetch_quote_snapshot
from tomic.services.portfolio_service import PortfolioService
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.services.market_snapshot_service import ScanRow


def _build_row(proposal: StrategyProposal) -> ScanRow:
    return ScanRow(
        symbol="AAA",
        strategy=proposal.strategy,
        proposal=proposal,
        metrics={},
        spot=100.0,
        next_earnings=None,
    )


def test_preview_to_tradable_transition(monkeypatch):
    proposal = StrategyProposal(
        strategy="iron_condor",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20250117",
                "strike": 120.0,
                "type": "call",
                "position": -1,
                "bid": 1.0,
                "ask": 1.2,
                "mid": 1.1,
                "mid_source": "close",
            },
            {
                "symbol": "AAA",
                "expiry": "20250117",
                "strike": 100.0,
                "type": "put",
                "position": -1,
                "bid": 1.05,
                "ask": 1.25,
                "mid": 1.15,
                "mid_source": "close",
            },
        ],
        score=12.0,
        ev=420.0,
    )
    proposal.fallback_summary = {"close": 2}
    proposal.needs_refresh = True

    portfolio = PortfolioService()
    before = portfolio.rank_candidates([_build_row(proposal)])[0]
    assert before.mid_status == "advisory"
    assert before.needs_refresh is True

    class DummyService:
        def refresh(self, proposal, **kwargs):  # type: ignore[no-untyped-def]
            for leg in proposal.legs:
                leg.update(
                    {
                        "bid": 1.3,
                        "ask": 1.5,
                        "mid": 1.4,
                        "mid_source": "true",
                        "missing_metrics": [],
                    }
                )
            proposal.fallback_summary = {"true": len(proposal.legs)}
            proposal.needs_refresh = False
            proposal.score = 18.0
            proposal.ev = 630.0
            return SnapshotResult(
                proposal=proposal,
                reasons=[],
                accepted=True,
                missing_quotes=[],
                delta_log=[{"before": 1.1, "after": 1.4, "delta": 0.3}],
            )

    result = fetch_quote_snapshot(proposal, trigger="panel", service=DummyService())

    assert result.accepted is True
    assert result.governance["needs_refresh"] is False
    assert result.governance["mid_sources"][0] == "tradable"

    after = portfolio.rank_candidates([_build_row(proposal)])[0]
    assert after.mid_status == "tradable"
    assert after.needs_refresh is False
    assert math.isclose(after.score or 0.0, 18.0, rel_tol=1e-6)
