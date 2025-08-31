import pytest

from tomic.strategies import StrategyName
from tomic.strategy_candidates import (
    StrategyProposal,
    _metrics,
    POSITIVE_CREDIT_STRATS,
)
import tomic.criteria as criteria
import tomic.strategy_candidates as sc


@pytest.fixture
def mock_rules(monkeypatch):
    rules = criteria.load_criteria().model_copy()
    rules.strategy.score_weight_rom = 1.0
    rules.strategy.score_weight_pos = 2.0
    rules.strategy.score_weight_ev = 3.0
    monkeypatch.setattr(criteria, "RULES", rules)
    monkeypatch.setattr(sc, "load_criteria", lambda: rules)
    return rules


def _build_legs():
    return {
        StrategyName.NAKED_PUT: [
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 10,
                "mid": 2.0,
                "model": 2.0,
                "delta": -0.01,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            }
        ],
        StrategyName.SHORT_PUT_SPREAD: [
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 95,
                "mid": 2.0,
                "model": 2.0,
                "delta": -0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 90,
                "mid": 0.5,
                "model": 0.5,
                "delta": -0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
        ],
        StrategyName.SHORT_CALL_SPREAD: [
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 105,
                "mid": 2.0,
                "model": 2.0,
                "delta": 0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 110,
                "mid": 0.5,
                "model": 0.5,
                "delta": 0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
        ],
        StrategyName.IRON_CONDOR: [
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 95,
                "mid": 1.5,
                "model": 1.5,
                "delta": -0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 90,
                "mid": 0.5,
                "model": 0.5,
                "delta": -0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 105,
                "mid": 1.5,
                "model": 1.5,
                "delta": 0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 110,
                "mid": 0.5,
                "model": 0.5,
                "delta": 0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
        ],
        StrategyName.ATM_IRON_BUTTERFLY: [
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 100,
                "mid": 2.0,
                "model": 2.0,
                "delta": -0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 95,
                "mid": 1.0,
                "model": 1.0,
                "delta": -0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 100,
                "mid": 2.0,
                "model": 2.0,
                "delta": 0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 105,
                "mid": 1.0,
                "model": 1.0,
                "delta": 0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
        ],
        StrategyName.RATIO_SPREAD: [
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 105,
                "mid": 2.0,
                "model": 2.0,
                "delta": 0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 110,
                "mid": 0.5,
                "model": 0.5,
                "delta": 0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 2,
            },
        ],
        StrategyName.BACKSPREAD_PUT: [
            {
                "expiry": "20250101",
                "type": "P",
                "strike": 95,
                "mid": 1.5,
                "model": 1.5,
                "delta": -0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250301",
                "type": "P",
                "strike": 90,
                "mid": 0.3,
                "model": 0.3,
                "delta": -0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 2,
            },
        ],
        StrategyName.CALENDAR: [
            {
                "expiry": "20250101",
                "type": "C",
                "strike": 100,
                "mid": 1.0,
                "model": 1.0,
                "delta": 0.1,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": -1,
            },
            {
                "expiry": "20250301",
                "type": "C",
                "strike": 100,
                "mid": 1.3,
                "model": 1.3,
                "delta": 0.05,
                "edge": 0.0,
                "volume": 100,
                "open_interest": 1000,
                "position": 1,
            },
        ],
    }


def test_strategy_scoring_applies_weights(mock_rules):
    legs_by_strategy = _build_legs()
    spot = 100.0
    for strat, legs in legs_by_strategy.items():
        metrics, reasons = _metrics(strat, legs, spot, criteria=mock_rules)
        assert metrics, f"{strat} rejected: {'; '.join(reasons)}"
        proposal = StrategyProposal(legs=legs, **metrics)
        weights = mock_rules.strategy
        expected = round(
            proposal.rom * weights.score_weight_rom
            + proposal.pos * weights.score_weight_pos
            + proposal.ev_pct * weights.score_weight_ev,
            2,
        )
        assert proposal.score == expected
        if strat in POSITIVE_CREDIT_STRATS:
            neg_legs = [dict(l) for l in legs]
            if strat == StrategyName.NAKED_PUT:
                neg_legs[0]["position"] = 1
            else:
                for l in neg_legs:
                    if l["position"] > 0:
                        l["mid"] += 10
            metrics2, reasons2 = _metrics(strat, neg_legs, spot, criteria=mock_rules)
            assert metrics2 is None
            assert "negatieve credit" in reasons2
