import math
import pytest

from tomic.analysis.scoring import _populate_additional_metrics
from tomic.metrics import PROPOSAL_GREEK_SCHEMA, aggregate_greeks
from tomic.services.proposal_details import build_proposal_core
from tomic.strategy.models import StrategyProposal


def _sample_legs() -> list[dict[str, object]]:
    return [
        {
            "delta": 0.25,
            "gamma": 0.01,
            "vega": 0.12,
            "theta": -0.02,
            "position": -1,
            "multiplier": 100,
        },
        {
            "Delta": -0.4,
            "Gamma": -0.015,
            "Vega": -0.2,
            "Theta": 0.03,
            "qty": 2,
            "action": "BUY",
        },
        {
            "delta": 0.1,
            "gamma": 0.004,
            "vega": 0.05,
            "theta": -0.01,
            "quantity": 3,
            "action": "SELL",
            "multiplier": 50,
        },
        {
            "delta": None,
            "gamma": None,
            "vega": None,
            "theta": None,
            "position": 1,
        },
    ]


def test_greek_aggregation_consistent_across_modules() -> None:
    legs = _sample_legs()
    expected = aggregate_greeks(legs, schema=PROPOSAL_GREEK_SCHEMA)

    proposal = StrategyProposal(strategy="test", legs=[dict(leg) for leg in legs])
    _populate_additional_metrics(proposal, proposal.legs, spot=None)
    core = build_proposal_core(proposal)

    assert proposal.greeks is not None
    assert proposal.greeks_sum is not None

    for greek, expected_val in expected.items():
        scoring_val = proposal.greeks.get(greek)
        summary_val = core.greeks.get(greek)
        uppercase_val = proposal.greeks_sum.get(greek.capitalize())

        if expected_val is None:
            assert scoring_val is None
            assert summary_val is None
            assert uppercase_val is None
        else:
            assert scoring_val is not None
            assert summary_val is not None
            assert uppercase_val is not None
            assert math.isclose(scoring_val, expected_val, rel_tol=1e-9, abs_tol=1e-9)
            assert math.isclose(summary_val, expected_val, rel_tol=1e-9, abs_tol=1e-9)
            assert math.isclose(uppercase_val, expected_val, rel_tol=1e-9, abs_tol=1e-9)
