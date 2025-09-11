import pytest

from tomic.analysis import scoring
from tomic.criteria import load_criteria
from tomic.strategy_candidates import StrategyProposal


def test_validate_leg_metrics_missing():
    legs = [{"type": "P", "strike": 100, "expiry": "20250101"}]
    ok, reasons = scoring.validate_leg_metrics("naked_put", legs)
    assert not ok
    assert reasons


def test_validate_leg_metrics_long_missing_rejected(monkeypatch):
    legs = [
        {"type": "P", "strike": 100, "expiry": "20250101", "mid": 1.0, "model": 1.0, "delta": -0.2, "position": -1},
        {"type": "P", "strike": 95, "expiry": "20250101", "position": 1},
    ]
    monkeypatch.setattr(scoring, "cfg_get", lambda name, default=None: {})
    ok, reasons = scoring.validate_leg_metrics("short_put_spread", legs)
    assert not ok
    assert reasons


def test_validate_leg_metrics_long_missing_allowed(monkeypatch):
    legs = [
        {"type": "P", "strike": 100, "expiry": "20250101", "mid": 1.0, "model": 1.0, "delta": -0.2, "position": -1},
        {"type": "P", "strike": 95, "expiry": "20250101", "position": 1},
    ]
    cfg = {"default": {}, "strategies": {"short_put_spread": {"allow_unpriced_wings": True}}}
    monkeypatch.setattr(scoring, "cfg_get", lambda name, default=None: cfg if name == "STRATEGY_CONFIG" else {})
    ok, reasons = scoring.validate_leg_metrics("short_put_spread", legs)
    assert ok
    assert reasons == []


def test_check_liquidity_failure():
    crit = load_criteria().model_copy()
    crit.market_data.min_option_volume = 10
    crit.market_data.min_option_open_interest = 10
    legs = [
        {
            "type": "P",
            "strike": 100,
            "expiry": "20250101",
            "mid": 1.0,
            "model": 1.0,
            "delta": -0.1,
            "volume": 0,
            "open_interest": 0,
            "position": -1,
        }
    ]
    ok, reasons = scoring.check_liquidity("naked_put", legs, crit)
    assert not ok
    assert reasons == ["onvoldoende volume/open interest"]


def test_compute_proposal_metrics(monkeypatch):
    legs = [
        {
            "type": "P",
            "strike": 100,
            "expiry": "20250101",
            "mid": 2.0,
            "model": 2.0,
            "delta": -0.1,
            "edge": 0.0,
            "volume": 100,
            "open_interest": 1000,
            "position": -1,
        }
    ]
    proposal = StrategyProposal(legs=legs)
    crit = load_criteria().model_copy()
    crit.strategy.score_weight_rom = 1
    crit.strategy.score_weight_pos = 1
    crit.strategy.score_weight_ev = 1

    monkeypatch.setattr(scoring, "heuristic_risk_metrics", lambda l, cb: {"max_profit": 200.0, "max_loss": -50.0})
    monkeypatch.setattr(scoring, "calculate_margin", lambda s, l, net_cashflow=0.0: 100.0)
    monkeypatch.setattr(scoring, "calculate_rom", lambda mp, margin: 10.0)
    monkeypatch.setattr(scoring, "calculate_ev", lambda pos, mp, ml: 5.0)

    score, reasons = scoring.compute_proposal_metrics("naked_put", proposal, legs, crit, spot=100)
    assert score == 105.0
    assert reasons == []
    assert proposal.margin == 100.0
