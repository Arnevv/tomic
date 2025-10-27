import math
import pytest

from tomic.analysis import scoring
from tomic.criteria import load_criteria
from tomic.strategy_candidates import StrategyProposal


from tomic.strategy.reasons import ReasonCategory


def test_validate_leg_metrics_missing():
    legs = [{"type": "P", "strike": 100, "expiry": "20250101"}]
    ok, reasons = scoring.validate_leg_metrics("naked_put", legs)
    assert not ok
    assert reasons
    assert reasons[0].code == "METRICS_MISSING"
    assert legs[0]["missing_metrics"] == ["mid", "model", "delta"]


def test_validate_leg_metrics_accepts_known_mid_source():
    legs = [
        {
            "type": "P",
            "strike": 100,
            "expiry": "20250101",
            "mid": 1.25,
            "model": 1.40,
            "delta": -0.2,
            "mid_source": "parity_close",
            "bid": None,
            "ask": None,
            "close": 1.25,
        }
    ]
    ok, reasons = scoring.validate_leg_metrics("naked_put", legs)
    assert ok
    assert reasons == []
    assert legs[0]["missing_metrics"] == []


def test_validate_leg_metrics_rejects_unknown_mid_source():
    legs = [
        {
            "type": "P",
            "strike": 100,
            "expiry": "20250101",
            "mid": 1.25,
            "model": 1.40,
            "delta": -0.2,
            "mid_source": "snapshot",
        }
    ]
    ok, reasons = scoring.validate_leg_metrics("naked_put", legs)
    assert not ok
    assert "mid" in legs[0]["missing_metrics"]
    assert reasons and reasons[0].code == "METRICS_MISSING"


def test_validate_leg_metrics_long_missing_rejected(monkeypatch):
    legs = [
        {"type": "P", "strike": 100, "expiry": "20250101", "mid": 1.0, "model": 1.0, "delta": -0.2, "position": -1},
        {"type": "P", "strike": 95, "expiry": "20250101", "position": 1},
    ]
    monkeypatch.setattr(scoring, "cfg_get", lambda name, default=None: {})
    ok, reasons = scoring.validate_leg_metrics("short_put_spread", legs)
    assert not ok
    assert reasons and reasons[0].code == "METRICS_MISSING"
    assert legs[0]["missing_metrics"] == []
    assert legs[1]["missing_metrics"] == ["mid", "model", "delta"]
    assert "metrics_ignored" not in legs[1]


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
    assert legs[0]["missing_metrics"] == []
    assert legs[1]["missing_metrics"] == ["mid", "model", "delta"]
    assert legs[1]["metrics_ignored"] is True

    proposal = StrategyProposal(legs=legs)
    monkeypatch.setattr(scoring, "check_liquidity", lambda *a, **k: (True, []))
    monkeypatch.setattr(scoring, "heuristic_risk_metrics", lambda l, cb: {"max_profit": 200.0, "max_loss": -50.0})
    monkeypatch.setattr(scoring, "calculate_margin", lambda *a, **k: 100.0)
    monkeypatch.setattr(scoring, "calculate_rom", lambda mp, margin: 10.0)
    monkeypatch.setattr(scoring, "calculate_ev", lambda pos, mp, ml: 5.0)
    monkeypatch.setattr(scoring, "_bs_estimate_missing", lambda _l: None)
    monkeypatch.setattr(scoring, "load_criteria", lambda: load_criteria().model_copy())
    score, _ = scoring.calculate_score("short_put_spread", proposal, spot=100)
    assert proposal.legs[1]["missing_metrics"] == ["mid", "model", "delta"]
    assert proposal.legs[1]["metrics_ignored"] is True


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
    assert reasons and reasons[0].category == ReasonCategory.LOW_LIQUIDITY


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
    monkeypatch.setattr(
        scoring,
        "heuristic_risk_metrics",
        lambda l, cb: {"max_profit": 200.0, "max_loss": -50.0, "risk_reward": 4.0},
    )
    monkeypatch.setattr(scoring, "calculate_margin", lambda s, l, net_cashflow=0.0: 100.0)
    monkeypatch.setattr(scoring, "calculate_rom", lambda mp, margin: 10.0)
    monkeypatch.setattr(scoring, "calculate_ev", lambda pos, mp, ml: 5.0)

    score, reasons = scoring.compute_proposal_metrics("naked_put", proposal, legs, crit, spot=100)
    assert math.isclose(score or 0.0, 57.84, rel_tol=1e-3)
    assert reasons == []
    assert proposal.margin == 100.0
    assert math.isclose(proposal.risk_reward or 0.0, 2.0)
    assert math.isclose(proposal.rom_norm or 0.0, 0.5)
    assert math.isclose(proposal.pos_norm or 0.0, 0.8)
    assert math.isclose(proposal.ev_norm or 0.0, 0.5)
    assert math.isclose(proposal.rr_norm or 0.0, 0.5228, rel_tol=1e-3)
    assert proposal.score_breakdown is not None
    assert proposal.score_label == "B"


def test_calculate_score_additional_metrics(monkeypatch):
    legs = [
        {
            "type": "P",
            "strike": 100,
            "expiry": "2025-01-01",
            "mid": 2.0,
            "model": 2.0,
            "delta": -0.2,
            "edge": 0.1,
            "volume": 500,
            "open_interest": 1000,
            "position": -1,
            "dte": 45,
            "HV20": 0.2,
            "HV30": 0.25,
            "HV90": 0.3,
            "IV_Rank": 0.4,
            "IV_Percentile": 0.5,
            "ATR14": 1.2,
        },
        {
            "type": "P",
            "strike": 95,
            "expiry": "2025-01-01",
            "mid": 0.5,
            "model": 0.5,
            "delta": -0.05,
            "edge": 0.05,
            "volume": 500,
            "open_interest": 1000,
            "position": 1,
            "dte": 45,
            "HV20": 0.21,
            "HV30": 0.24,
            "HV90": 0.29,
            "IV_Rank": 0.41,
            "IV_Percentile": 0.51,
            "ATR14": 1.1,
        },
    ]

    proposal = StrategyProposal(legs=legs)
    monkeypatch.setattr(
        scoring,
        "heuristic_risk_metrics",
        lambda l, cb: {"max_profit": 200.0, "max_loss": -50.0, "risk_reward": 4.0},
    )
    monkeypatch.setattr(scoring, "calculate_margin", lambda *a, **k: 100.0)
    monkeypatch.setattr(scoring, "calculate_rom", lambda mp, margin: 10.0)
    monkeypatch.setattr(scoring, "calculate_ev", lambda pos, mp, ml: 5.0)

    score, reasons = scoring.calculate_score(
        "short_put_spread", proposal, spot=100.0, atr=1.5
    )
    assert score is not None
    assert reasons == []
    assert math.isclose(proposal.atr or 0.0, 1.5)
    assert math.isclose(proposal.iv_rank or 0.0, 0.405)
    assert math.isclose(proposal.iv_percentile or 0.0, 0.505)
    assert math.isclose(proposal.hv20 or 0.0, 0.205)
    assert math.isclose(proposal.hv30 or 0.0, 0.245)
    assert math.isclose(proposal.hv90 or 0.0, 0.295)
    assert proposal.dte == {
        "min": 45,
        "max": 45,
        "values": [45],
        "by_expiry": {"2025-01-01": 45},
    }
    assert proposal.wing_width is not None
    assert math.isclose(proposal.wing_width["put"], 5.0)
    assert proposal.wing_symmetry is None
    assert proposal.breakeven_distances is not None
    assert proposal.breakeven_distances["dollar"] and math.isclose(
        proposal.breakeven_distances["dollar"][0], 1.5
    )
    assert proposal.breakeven_distances["percent"] and math.isclose(
        proposal.breakeven_distances["percent"][0], 1.5
    )
    assert proposal.score_breakdown
    assert proposal.score_label in {"A", "B", "C", "D"}


def test_compute_proposal_metrics_rejects_low_risk_reward(monkeypatch):
    legs = [
        {
            "type": "C",
            "strike": 100,
            "expiry": "2025-01-01",
            "mid": 2.0,
            "model": 2.0,
            "delta": 0.2,
            "edge": 0.1,
            "volume": 500,
            "open_interest": 1000,
            "position": -1,
        },
        {
            "type": "C",
            "strike": 105,
            "expiry": "2025-01-01",
            "mid": 1.5,
            "model": 1.5,
            "delta": 0.05,
            "edge": 0.05,
            "volume": 500,
            "open_interest": 1000,
            "position": 1,
        },
    ]

    proposal = StrategyProposal(legs=legs)
    crit = load_criteria().model_copy()

    monkeypatch.setattr(
        scoring,
        "heuristic_risk_metrics",
        lambda l, cb: {"max_profit": 100.0, "max_loss": -400.0},
    )
    monkeypatch.setattr(scoring, "calculate_margin", lambda *a, **k: 500.0)
    monkeypatch.setattr(scoring, "calculate_rom", lambda mp, margin: 2.0)
    monkeypatch.setattr(scoring, "calculate_ev", lambda pos, mp, ml: 5.0)
    monkeypatch.setattr(scoring, "_bs_estimate_missing", lambda _l: None)
    monkeypatch.setattr(scoring, "check_liquidity", lambda *a, **k: (True, []))
    monkeypatch.setattr(scoring, "load_criteria", lambda: crit)
    monkeypatch.setattr(
        scoring,
        "cfg_get",
        lambda name, default=None: {"default": {"min_risk_reward": 1.0}}
        if name == "STRATEGY_CONFIG"
        else {},
    )

    score, reasons = scoring.compute_proposal_metrics("iron_condor", proposal, legs, crit, spot=100)

    assert score is None
    assert any(detail.category == ReasonCategory.RR_BELOW_MIN for detail in reasons)
    assert math.isclose(proposal.risk_reward or 0.0, 0.25)
