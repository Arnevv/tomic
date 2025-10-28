from __future__ import annotations

import pytest

from tomic.core.pricing import SpreadPolicy


SHARED_POLICY_CONFIG = {
    "relative": 0.12,
    "absolute": [
        {"max_underlying": 100.0, "threshold": 0.25},
        {"max_underlying": None, "threshold": 0.50},
    ],
    "exceptions": [
        {
            "name": "vertical_combo",
            "match": {"structure": "vertical"},
            "relative": 0.08,
            "absolute": 0.30,
        },
        {
            "name": "iron_combo",
            "match": {"structure": ["iron_condor", "iron_fly"]},
            "relative": 0.10,
            "absolute": 0.45,
        },
    ],
}


SHARED_SPREAD_SCENARIOS = [
    {
        "description": "default_absolute_accept",
        "spread": 0.22,
        "mid": 1.20,
        "underlying": 80.0,
        "context": {"symbol": "AAA"},
        "expected": True,
        "reason": "abs",
    },
    {
        "description": "default_relative_accept",
        "spread": 0.26,
        "mid": 2.50,
        "underlying": 90.0,
        "context": {"symbol": "BBB"},
        "expected": True,
        "reason": "rel",
    },
    {
        "description": "vertical_exception",
        "spread": 0.28,
        "mid": 1.10,
        "underlying": 180.0,
        "context": {"structure": "vertical", "symbol": "CCC"},
        "expected": True,
        "reason": "abs",
    },
    {
        "description": "iron_condor_exception",
        "spread": 0.42,
        "mid": 2.10,
        "underlying": 320.0,
        "context": {"structure": "iron_condor", "symbol": "DDD"},
        "expected": True,
        "reason": "abs",
    },
    {
        "description": "too_wide_failure",
        "spread": 0.62,
        "mid": 2.30,
        "underlying": 140.0,
        "context": {"symbol": "EEE"},
        "expected": False,
        "reason": "too_wide",
    },
]


@pytest.mark.parametrize("case", SHARED_SPREAD_SCENARIOS, ids=lambda case: case["description"])
def test_spread_policy_decision(case: dict) -> None:
    policy = SpreadPolicy(SHARED_POLICY_CONFIG)
    decision = policy.evaluate(
        spread=case["spread"],
        mid=case["mid"],
        underlying=case.get("underlying"),
        context=case.get("context"),
    )
    assert decision.accepted is case["expected"]
    assert decision.reason == case["reason"]


def test_spread_policy_overrides_can_tighten_threshold() -> None:
    policy = SpreadPolicy(SHARED_POLICY_CONFIG)
    decision = policy.evaluate(
        spread=0.35,
        mid=1.8,
        underlying=160.0,
        context={"structure": "vertical"},
        overrides={"absolute": 0.20},
    )
    assert not decision.accepted
    assert decision.reason == "too_wide"
