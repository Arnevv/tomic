"""Tests voor PortfolioService module."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping
from unittest.mock import Mock

import pytest

from tomic.services.portfolio_service import (
    Candidate,
    CandidateRankingError,
    Factsheet,
    PortfolioService,
)
from tomic.services.market_snapshot_service import ScanRow
from tomic.strategy.models import StrategyProposal


@pytest.fixture
def portfolio_service():
    """Return PortfolioService instance with fixed today date."""
    return PortfolioService(today_fn=lambda: date(2025, 1, 15))


@pytest.fixture
def full_record() -> dict[str, Any]:
    """Return volledig record met alle velden."""
    return {
        "symbol": "AAPL",
        "strategy": "IronCondor",
        "spot": 150.25,
        "iv": 0.35,
        "hv20": 0.30,
        "hv30": 0.32,
        "hv90": 0.28,
        "hv252": 0.25,
        "term_m1_m2": 0.05,
        "term_m1_m3": 0.08,
        "iv_rank": 65.5,
        "iv_percentile": 70.2,
        "skew": 1.15,
        "criteria": "HIGH_IV",
        "next_earnings": "2025-02-20",
        "days_until_earnings": 36,
    }


@pytest.fixture
def partial_record() -> dict[str, Any]:
    """Return record met ontbrekende velden."""
    return {
        "symbol": "MSFT",
        "strategy": "CreditSpread",
        "spot": 250.0,
        "iv": 0.28,
        # HV velden ontbreken
        "iv_rank": 50.0,
        # iv_percentile ontbreekt
        # skew ontbreekt
    }


@pytest.fixture
def sample_proposal() -> StrategyProposal:
    """Return sample StrategyProposal."""
    return StrategyProposal(
        strategy="IronCondor",
        legs=[
            {
                "symbol": "AAPL",
                "strike": 145.0,
                "type": "put",
                "expiry": "2025-02-21",
                "bid": 1.50,
                "ask": 1.60,
                "delta": -0.25,
            },
            {
                "symbol": "AAPL",
                "strike": 155.0,
                "type": "call",
                "expiry": "2025-02-21",
                "bid": 1.40,
                "ask": 1.50,
                "delta": 0.25,
            },
        ],
        score=85.5,
        ev=125.0,
        pos=0.65,
        rom=15.5,
        credit=290.0,
        margin=1800.0,
        max_profit=290.0,
        max_loss=-1510.0,
        risk_reward=0.19,
    )


class TestBuildFactsheet:
    """Tests voor build_factsheet method."""

    def test_build_factsheet_with_full_data(self, portfolio_service, full_record):
        """Test build_factsheet met volledige data."""
        factsheet = portfolio_service.build_factsheet(full_record)

        assert isinstance(factsheet, Factsheet)
        assert factsheet.symbol == "AAPL"
        assert factsheet.strategy == "IronCondor"
        assert factsheet.spot == 150.25
        assert factsheet.iv == 0.35
        assert factsheet.hv20 == 0.30
        assert factsheet.hv30 == 0.32
        assert factsheet.hv90 == 0.28
        assert factsheet.hv252 == 0.25
        assert factsheet.term_m1_m2 == 0.05
        assert factsheet.term_m1_m3 == 0.08
        assert abs(factsheet.iv_rank - 0.655) < 0.001  # normalized to 0-1
        assert abs(factsheet.iv_percentile - 0.702) < 0.001  # normalized to 0-1
        assert factsheet.skew == 1.15
        assert factsheet.criteria == "HIGH_IV"
        assert factsheet.next_earnings == date(2025, 2, 20)
        assert factsheet.days_until_earnings == 36

    def test_build_factsheet_with_partial_data(self, portfolio_service, partial_record):
        """Test build_factsheet met ontbrekende velden."""
        factsheet = portfolio_service.build_factsheet(partial_record)

        assert isinstance(factsheet, Factsheet)
        assert factsheet.symbol == "MSFT"
        assert factsheet.strategy == "CreditSpread"
        assert factsheet.spot == 250.0
        assert factsheet.iv == 0.28
        # Ontbrekende velden moeten None zijn
        assert factsheet.hv20 is None
        assert factsheet.hv30 is None
        assert factsheet.hv90 is None
        assert factsheet.hv252 is None
        assert factsheet.iv_percentile is None
        assert factsheet.skew is None

    def test_build_factsheet_with_missing_earnings(self, portfolio_service):
        """Test build_factsheet zonder earnings data."""
        record = {
            "symbol": "GOOGL",
            "strategy": "Strangle",
            "spot": 140.0,
            "iv": 0.30,
        }

        factsheet = portfolio_service.build_factsheet(record)

        assert factsheet.symbol == "GOOGL"
        assert factsheet.next_earnings is None
        assert factsheet.days_until_earnings is None

    def test_build_factsheet_with_invalid_strategy_type(self, portfolio_service):
        """Test build_factsheet met niet-string strategy type."""
        record = {
            "symbol": "TSLA",
            "strategy": 123,  # invalid type
            "spot": 200.0,
        }

        factsheet = portfolio_service.build_factsheet(record)

        # Niet-string strategy moet None worden
        assert factsheet.strategy is None

    def test_build_factsheet_with_invalid_criteria_type(self, portfolio_service):
        """Test build_factsheet met niet-string criteria type."""
        record = {
            "symbol": "NVDA",
            "strategy": "IronCondor",
            "criteria": ["HIGH_IV", "LOW_HV"],  # invalid type
        }

        factsheet = portfolio_service.build_factsheet(record)

        # Niet-string criteria moet None worden
        assert factsheet.criteria is None

    def test_build_factsheet_normalizes_percent_values(self, portfolio_service):
        """Test dat percent waarden correct genormaliseerd worden."""
        record = {
            "symbol": "AMD",
            "iv_rank": 75.0,  # should be normalized to 0.75
            "iv_percentile": 80.0,  # should be normalized to 0.80
        }

        factsheet = portfolio_service.build_factsheet(record)

        assert factsheet.iv_rank == 0.75
        assert factsheet.iv_percentile == 0.80


class TestRankCandidates:
    """Tests voor rank_candidates method."""

    def test_rank_candidates_basic(self, portfolio_service):
        """Test rank_candidates met basis scenario."""
        # Maak 3 proposals met verschillende scores
        proposals = [
            StrategyProposal(strategy="IronCondor", score=85.0, ev=100.0, legs=[]),
            StrategyProposal(strategy="CreditSpread", score=92.0, ev=120.0, legs=[]),
            StrategyProposal(strategy="Strangle", score=78.0, ev=90.0, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol="AAPL",
                strategy=p.strategy,
                proposal=p,
                metrics={"iv_rank": 65.0, "iv_percentile": 70.0, "skew": 1.15},
                spot=150.0,
                next_earnings=None,
            )
            for p in proposals
        ]

        candidates = portfolio_service.rank_candidates(scan_rows)

        assert len(candidates) == 3
        # Hoogste score eerst (92.0)
        assert candidates[0].score == 92.0
        assert candidates[0].strategy == "CreditSpread"
        # Dan 85.0
        assert candidates[1].score == 85.0
        assert candidates[1].strategy == "IronCondor"
        # Dan 78.0
        assert candidates[2].score == 78.0
        assert candidates[2].strategy == "Strangle"

    def test_rank_candidates_with_none_scores(self, portfolio_service):
        """Test rank_candidates met None scores."""
        proposals = [
            StrategyProposal(strategy="IronCondor", score=85.0, legs=[]),
            StrategyProposal(strategy="CreditSpread", score=None, legs=[]),
            StrategyProposal(strategy="Strangle", score=92.0, legs=[]),
            StrategyProposal(strategy="Butterfly", score=None, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol="AAPL",
                strategy=p.strategy,
                proposal=p,
                metrics={},
                spot=150.0,
                next_earnings=None,
            )
            for p in proposals
        ]

        candidates = portfolio_service.rank_candidates(scan_rows)

        assert len(candidates) == 4
        # None scores worden behandeld als 0.0 en komen onderaan
        assert candidates[0].score == 92.0
        assert candidates[1].score == 85.0
        assert candidates[2].score is None
        assert candidates[3].score is None

    def test_rank_candidates_stable_ordering(self, portfolio_service):
        """Test dat rank_candidates stabiele sortering heeft."""
        # Maak meerdere proposals met dezelfde score
        proposals = [
            StrategyProposal(strategy="IronCondor", score=85.0, legs=[]),
            StrategyProposal(strategy="CreditSpread", score=85.0, legs=[]),
            StrategyProposal(strategy="Strangle", score=85.0, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol=sym,
                strategy=p.strategy,
                proposal=p,
                metrics={},
                spot=150.0,
                next_earnings=None,
            )
            for sym, p in zip(["AAPL", "MSFT", "GOOGL"], proposals)
        ]

        # Run meerdere keren en check dat volgorde consistent is
        results = [
            portfolio_service.rank_candidates(scan_rows)
            for _ in range(3)
        ]

        # Alle runs moeten dezelfde volgorde hebben
        for i in range(1, len(results)):
            assert [c.symbol for c in results[i]] == [c.symbol for c in results[0]]

    def test_rank_candidates_with_top_n_limit(self, portfolio_service):
        """Test rank_candidates met top_n limiet."""
        proposals = [
            StrategyProposal(strategy="Strategy1", score=90.0, legs=[]),
            StrategyProposal(strategy="Strategy2", score=85.0, legs=[]),
            StrategyProposal(strategy="Strategy3", score=80.0, legs=[]),
            StrategyProposal(strategy="Strategy4", score=75.0, legs=[]),
            StrategyProposal(strategy="Strategy5", score=70.0, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol=f"SYM{i}",
                strategy=p.strategy,
                proposal=p,
                metrics={},
                spot=150.0,
                next_earnings=None,
            )
            for i, p in enumerate(proposals)
        ]

        # Limiteer tot top 3
        rules = {"top_n": 3}
        candidates = portfolio_service.rank_candidates(scan_rows, rules=rules)

        assert len(candidates) == 3
        assert candidates[0].score == 90.0
        assert candidates[1].score == 85.0
        assert candidates[2].score == 80.0

    def test_rank_candidates_with_zero_top_n(self, portfolio_service):
        """Test rank_candidates met top_n=0 (geen limiet)."""
        proposals = [
            StrategyProposal(strategy=f"Strategy{i}", score=float(90 - i * 5), legs=[])
            for i in range(5)
        ]

        scan_rows = [
            ScanRow(
                symbol=f"SYM{i}",
                strategy=p.strategy,
                proposal=p,
                metrics={},
                spot=150.0,
                next_earnings=None,
            )
            for i, p in enumerate(proposals)
        ]

        # top_n=0 betekent geen limiet
        rules = {"top_n": 0}
        candidates = portfolio_service.rank_candidates(scan_rows, rules=rules)

        assert len(candidates) == 5

    def test_rank_candidates_with_invalid_rules(self, portfolio_service):
        """Test rank_candidates met invalid top_n waarde."""
        proposals = [
            StrategyProposal(strategy="IronCondor", score=85.0, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol="AAPL",
                strategy=p.strategy,
                proposal=p,
                metrics={},
                spot=150.0,
                next_earnings=None,
            )
            for p in proposals
        ]

        # Invalid top_n waarde zou exception moeten geven
        rules = {"top_n": "invalid"}
        with pytest.raises(CandidateRankingError, match="invalid top_n value"):
            portfolio_service.rank_candidates(scan_rows, rules=rules)

    def test_rank_candidates_with_non_sequence_input(self, portfolio_service):
        """Test rank_candidates met niet-sequence input."""
        # Een niet-sequence type zoals int of dict
        with pytest.raises(CandidateRankingError, match="symbols must be a sequence"):
            portfolio_service.rank_candidates(123)

    def test_rank_candidates_skips_non_scanrow_entries(self, portfolio_service):
        """Test dat rank_candidates niet-ScanRow entries overslaat."""
        proposals = [
            StrategyProposal(strategy="IronCondor", score=85.0, legs=[]),
        ]

        scan_rows = [
            ScanRow(
                symbol="AAPL",
                strategy=proposals[0].strategy,
                proposal=proposals[0],
                metrics={},
                spot=150.0,
                next_earnings=None,
            ),
            "not a ScanRow",  # invalid entry
        ]

        candidates = portfolio_service.rank_candidates(scan_rows)

        # Alleen de geldige ScanRow moet worden verwerkt
        assert len(candidates) == 1
        assert candidates[0].symbol == "AAPL"

    def test_rank_candidates_includes_all_fields(self, portfolio_service):
        """Test dat rank_candidates alle velden correct overneemt."""
        proposal = StrategyProposal(
            strategy="IronCondor",
            score=85.0,
            ev=125.0,
            pos=0.65,
            rom=15.5,
            credit=290.0,
            margin=1800.0,
            max_profit=290.0,
            max_loss=-1510.0,
            risk_reward=0.19,
            legs=[
                {
                    "symbol": "AAPL",
                    "strike": 145.0,
                    "expiry": "2025-02-21",
                    "bid": 1.50,
                    "ask": 1.60,
                },
            ],
        )

        scan_row = ScanRow(
            symbol="AAPL",
            strategy="IronCondor",
            proposal=proposal,
            metrics={"iv_rank": 65.0, "iv_percentile": 70.0, "skew": 1.15},
            spot=150.0,
            next_earnings=date(2025, 2, 20),
        )

        candidates = portfolio_service.rank_candidates([scan_row])

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.symbol == "AAPL"
        assert cand.strategy == "IronCondor"
        assert cand.score == 85.0
        assert cand.ev == 125.0
        assert cand.iv_rank == 0.65  # normalized
        assert cand.iv_percentile == 0.70  # normalized
        assert cand.skew == 1.15
        assert cand.spot == 150.0
        assert cand.next_earnings == date(2025, 2, 20)
        assert cand.dte_summary is not None  # should be formatted


class TestHelperMethods:
    """Tests voor helper methods."""

    def test_avg_bid_ask_pct_with_valid_data(self, portfolio_service):
        """Test _avg_bid_ask_pct met geldige data."""
        proposal = StrategyProposal(
            legs=[
                {"bid": 1.50, "ask": 1.60},  # spread = 0.10, mid = 1.55, pct = 6.45%
                {"bid": 2.00, "ask": 2.10},  # spread = 0.10, mid = 2.05, pct = 4.88%
            ]
        )

        result = portfolio_service._avg_bid_ask_pct(proposal)

        # Gemiddelde van 6.45% en 4.88% ≈ 5.67%
        assert result is not None
        assert 5.0 < result < 7.0

    def test_avg_bid_ask_pct_with_missing_data(self, portfolio_service):
        """Test _avg_bid_ask_pct met ontbrekende data."""
        proposal = StrategyProposal(
            legs=[
                {"bid": 1.50},  # ask ontbreekt
                {"ask": 2.10},  # bid ontbreekt
            ]
        )

        result = portfolio_service._avg_bid_ask_pct(proposal)

        # Geen geldige spreads
        assert result is None

    def test_avg_bid_ask_pct_with_zero_mid(self, portfolio_service):
        """Test _avg_bid_ask_pct met mid=0."""
        proposal = StrategyProposal(
            legs=[
                {"bid": 0.0, "ask": 0.05},  # mid = 0.025
            ]
        )

        result = portfolio_service._avg_bid_ask_pct(proposal)

        # Moet nog steeds percentage berekenen
        assert result is not None

    def test_risk_reward_with_valid_data(self, portfolio_service):
        """Test _risk_reward met geldige data."""
        proposal = StrategyProposal(
            strategy="IronCondor",
            max_profit=290.0,
            max_loss=-1510.0,
            credit=290.0,
            margin=1800.0,
            legs=[],
        )

        result = portfolio_service._risk_reward(proposal)

        # risk_reward = max_profit / abs(max_loss) = 290 / 1510 ≈ 0.19
        assert result is not None
        assert 0.19 <= result <= 0.20

    def test_risk_reward_with_none_values(self, portfolio_service):
        """Test _risk_reward met None waarden."""
        proposal = StrategyProposal(
            strategy="IronCondor",
            max_profit=None,
            max_loss=None,
            legs=[],
        )

        result = portfolio_service._risk_reward(proposal)

        assert result is None

    def test_risk_reward_with_zero_loss(self, portfolio_service):
        """Test _risk_reward met loss=0."""
        proposal = StrategyProposal(
            strategy="IronCondor",
            max_profit=290.0,
            max_loss=0.0,
            legs=[],
        )

        result = portfolio_service._risk_reward(proposal)

        assert result is None

    def test_mid_sources_with_mid_tags(self, portfolio_service):
        """Test _mid_sources met MidTagSnapshot."""
        from tomic.core.pricing.mid_tags import MidTagSnapshot

        snapshot = MidTagSnapshot(
            tags=("tradable", "quotes:2", "model:1"),
            counters={"quotes": 2, "model": 1},
        )

        proposal = StrategyProposal(
            mid_tags=snapshot,
            legs=[],
        )

        result = portfolio_service._mid_sources(proposal)

        assert result == ("tradable", "quotes:2", "model:1")

    def test_mid_sources_without_mid_tags(self, portfolio_service):
        """Test _mid_sources zonder MidTagSnapshot."""
        proposal = StrategyProposal(
            mid_tags=None,
            legs=[
                {
                    "symbol": "AAPL",
                    "strike": 145.0,
                    "bid": 1.50,
                    "ask": 1.60,
                    "mid": 1.55,
                }
            ],
        )

        result = portfolio_service._mid_sources(proposal)

        # Moet fallback logic gebruiken
        assert isinstance(result, tuple)
        assert len(result) > 0

    def test_mid_sources_with_needs_refresh(self, portfolio_service):
        """Test _mid_sources met needs_refresh flag."""
        from tomic.core.pricing.mid_tags import MidTagSnapshot

        snapshot = MidTagSnapshot(
            tags=("advisory", "needs_refresh", "preview:1"),
            counters={"preview": 1},
        )

        proposal = StrategyProposal(
            mid_tags=snapshot,
            needs_refresh=True,
            legs=[],
        )

        result = portfolio_service._mid_sources(proposal)

        assert "needs_refresh" in result or "advisory" in result
