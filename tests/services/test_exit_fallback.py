from __future__ import annotations

import copy
from typing import Any

import pytest

from tomic.services.exit_fallback import (
    ExitFallbackExecutor,
    ExitFallbackReason,
    build_vertical_execution_candidates,
    detect_fallback_reason,
    dispatch_vertical_execution,
)
from tomic.services.exit_orders import ExitOrderPlan, build_exit_order_plan
from tomic.services.trade_management_service import StrategyExitIntent


@pytest.fixture
def iron_condor_intent() -> StrategyExitIntent:
    strategy = {
        "symbol": "XYZ",
        "expiry": "20240119",
        "legs": [
            {"strike": 100.0, "right": "call", "position": -1},
            {"strike": 105.0, "right": "call", "position": 1},
            {"strike": 95.0, "right": "put", "position": -1},
            {"strike": 90.0, "right": "put", "position": 1},
        ],
    }
    legs = [
        {
            "conId": 1001,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 100.0,
            "right": "C",
            "position": -1,
            "bid": 1.1,
            "ask": 1.2,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1002,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 105.0,
            "right": "C",
            "position": 1,
            "bid": 0.55,
            "ask": 0.65,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1003,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 95.0,
            "right": "P",
            "position": -1,
            "bid": 1.05,
            "ask": 1.2,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1004,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 90.0,
            "right": "P",
            "position": 1,
            "bid": 0.35,
            "ask": 0.45,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
    ]
    return StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)


def _plan_from_leg_subset(intent: StrategyExitIntent, selector: Any) -> ExitOrderPlan:
    subset = [leg for leg in intent.legs if selector(leg)]
    wing_intent = StrategyExitIntent(
        strategy={"symbol": intent.strategy.get("symbol"), "legs": subset},
        legs=copy.deepcopy(subset),
        exit_rules=None,
    )
    return build_exit_order_plan(wing_intent)


def test_detect_fallback_reason_prioritizes_gate_failure():
    reason = detect_fallback_reason("combo niet verhandelbaar: gate fail")
    assert reason == ExitFallbackReason.GATE_FAILURE

    reason = detect_fallback_reason(RuntimeError("boom"))
    assert reason == ExitFallbackReason.MAIN_BAG_FAILURE

    reason = detect_fallback_reason(None, repricer_timeout=True)
    assert reason == ExitFallbackReason.REPRICER_TIMEOUT

    reason = detect_fallback_reason(None, cancel_on_no_fill=True)
    assert reason == ExitFallbackReason.CANCEL_ON_NO_FILL


def test_build_vertical_execution_candidates_returns_single_plan(iron_condor_intent):
    candidates = build_vertical_execution_candidates(iron_condor_intent)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.wing == "all"
    assert isinstance(candidate.plan, ExitOrderPlan)
    assert candidate.width is not None
    assert abs(candidate.width - 15.0) < 1e-9
    assert candidate.gate_message


def test_dispatch_vertical_execution_orders_single_candidate(iron_condor_intent):
    candidate = build_vertical_execution_candidates(iron_condor_intent)[0]

    dispatched: list[ExitOrderPlan] = []

    def recorder(plan: ExitOrderPlan):
        dispatched.append(plan)
        return "ok"

    results = dispatch_vertical_execution(
        [candidate],
        recorder,
        reason=ExitFallbackReason.MAIN_BAG_FAILURE,
        repricer_steps={"all": "waited"},
    )

    assert results == ["ok"]
    assert len(dispatched) == 1
    assert dispatched[0] is candidate.plan



def test_executor_runs_candidates(iron_condor_intent):
    dispatched: list[ExitOrderPlan] = []

    def recorder(plan: ExitOrderPlan):
        dispatched.append(plan)
        return plan.action

    executor = ExitFallbackExecutor(dispatcher=recorder)
    results = executor.execute(
        iron_condor_intent,
        error=RuntimeError("main failure"),
        repricer_steps={"all": "retry"},
    )

    assert len(results) == 1
    assert dispatched and all(isinstance(plan, ExitOrderPlan) for plan in dispatched)
    assert results[0] in {"BUY", "SELL"}

