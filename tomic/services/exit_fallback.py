"""Helpers to orchestrate exit order fallbacks per vertical wing."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from tomic.logutils import logger
from tomic.strategy.models import StrategyProposal
from tomic.utils import get_leg_right

from .exit_orders import ExitIntent, ExitOrderPlan, build_exit_order_plan
from .order_submission import OrderSubmissionService


class ExitFallbackReason(Enum):
    """Enumeration of fallback triggers for exit execution."""

    MANUAL = "manual_trigger"
    MAIN_BAG_FAILURE = "main_bag_failure"
    GATE_FAILURE = "gate_failure"
    REPRICER_TIMEOUT = "repricer_timeout"
    CANCEL_ON_NO_FILL = "cancel_on_no_fill"


@dataclass(frozen=True)
class VerticalExecutionCandidate:
    """Container describing a vertical wing candidate for fallback execution."""

    wing: str
    plan: ExitOrderPlan | None
    width: float | None
    gate_message: str | None
    skip_reason: str | None = None


def detect_fallback_reason(
    error: Exception | str | None,
    *,
    repricer_timeout: bool = False,
    cancel_on_no_fill: bool = False,
) -> ExitFallbackReason:
    """Infer the fallback trigger based on exit workflow outcomes."""

    message = ""
    if error is not None:
        message = str(error).strip().lower()

    if "gate" in message or "niet verhandelbaar" in message:
        reason = ExitFallbackReason.GATE_FAILURE
    elif repricer_timeout:
        reason = ExitFallbackReason.REPRICER_TIMEOUT
    elif cancel_on_no_fill:
        reason = ExitFallbackReason.CANCEL_ON_NO_FILL
    elif error is not None:
        reason = ExitFallbackReason.MAIN_BAG_FAILURE
    else:
        reason = ExitFallbackReason.MANUAL

    logger.debug("[exit-fallback] start reason=%s", reason.value)
    return reason


def _infer_spread_width(legs: Sequence[Mapping[str, Any]]) -> float | None:
    strikes: list[float] = []
    for leg in legs:
        try:
            strike = float(leg.get("strike"))
        except (TypeError, ValueError):
            strike = None
        if strike is None:
            continue
        strikes.append(strike)
    if len(strikes) < 2:
        return None
    return abs(max(strikes) - min(strikes))


def _clone_strategy_with_legs(
    strategy: Mapping[str, Any] | None,
    legs: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    base: dict[str, Any] = {}
    if isinstance(strategy, Mapping):
        base.update(strategy)
    base["legs"] = [copy.deepcopy(leg) for leg in legs]
    return base


def build_vertical_execution_candidates(
    intent: ExitIntent,
) -> list[VerticalExecutionCandidate]:
    """Split ``intent`` into vertical wings and build order plans per wing."""

    candidates: list[VerticalExecutionCandidate] = []
    legs_iterable: Iterable[Mapping[str, Any]] = intent.legs or []
    grouped: dict[str, list[Mapping[str, Any]]] = {"call": [], "put": []}
    for leg in legs_iterable:
        wing = get_leg_right(leg)
        if wing in grouped:
            grouped[wing].append(dict(leg))

    for wing, wing_legs in grouped.items():
        if len(wing_legs) < 2:
            candidates.append(
                VerticalExecutionCandidate(
                    wing=wing,
                    plan=None,
                    width=_infer_spread_width(wing_legs),
                    gate_message=None,
                    skip_reason="insufficient_legs",
                )
            )
            continue

        wing_intent = ExitIntent(
            strategy=_clone_strategy_with_legs(intent.strategy, wing_legs),
            legs=[dict(leg) for leg in wing_legs],
            exit_rules=intent.exit_rules,
        )

        try:
            plan = build_exit_order_plan(wing_intent)
            candidates.append(
                VerticalExecutionCandidate(
                    wing=wing,
                    plan=plan,
                    width=_infer_spread_width(wing_legs),
                    gate_message=plan.tradeability,
                )
            )
        except ValueError as exc:  # gate or NBBO failure per wing
            candidates.append(
                VerticalExecutionCandidate(
                    wing=wing,
                    plan=None,
                    width=_infer_spread_width(wing_legs),
                    gate_message=None,
                    skip_reason=str(exc),
                )
            )

    # Sort widest spreads first to reduce riskier wing before narrow wing.
    return sorted(
        candidates,
        key=lambda item: (item.width or 0.0),
        reverse=True,
    )


def _resolve_symbol(plan: ExitOrderPlan) -> str | None:
    strategy = plan.intent.strategy
    symbol: Any = None
    if isinstance(strategy, Mapping):
        symbol = strategy.get("symbol") or strategy.get("underlying")
    if not symbol and plan.legs:
        symbol = plan.legs[0].get("symbol")
    if symbol in (None, ""):
        return None
    return str(symbol)


def _proposal_from_exit_plan(plan: ExitOrderPlan) -> StrategyProposal:
    strategy_name: str | None = None
    if isinstance(plan.intent.strategy, Mapping):
        strategy_name = plan.intent.strategy.get("type") or plan.intent.strategy.get("strategy")
    proposal = StrategyProposal(strategy=strategy_name)
    proposal.legs = [dict(leg) for leg in plan.legs]
    proposal.tradeability_notes = plan.tradeability
    proposal.credit = float(plan.per_combo_credit or 0.0) * max(plan.quantity, 1)
    return proposal


def default_exit_order_dispatcher(
    plan: ExitOrderPlan,
    *,
    host: str,
    port: int,
    client_id: int,
    account: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
    service: OrderSubmissionService | None = None,
):
    """Submit ``plan`` via :class:`OrderSubmissionService` and return placement result."""

    submission = service or OrderSubmissionService()
    proposal = _proposal_from_exit_plan(plan)
    symbol = _resolve_symbol(plan) or ""
    instructions = submission.build_instructions(
        proposal,
        symbol=symbol,
        account=account,
        order_type=order_type,
        tif=tif,
    )
    return submission.place_orders(
        instructions,
        host=host,
        port=port,
        client_id=client_id,
    )


def dispatch_vertical_execution(
    candidates: Sequence[VerticalExecutionCandidate],
    dispatcher: Callable[[ExitOrderPlan], Any],
    *,
    reason: ExitFallbackReason,
    repricer_steps: Mapping[str, str] | None = None,
) -> list[Any]:
    """Send vertical exit plans sequentially and log per wing."""

    logger.info(
        "[exit-fallback] executing %d verticals (reason=%s)",
        len(candidates),
        reason.value,
    )

    results: list[Any] = []
    step_lookup = {k: v for k, v in (repricer_steps or {}).items()}

    for candidate in candidates:
        repricer_state = step_lookup.get(candidate.wing, "skip")
        if candidate.plan is None:
            logger.info(
                "[exit-fallback][%s] gate=fail repricer=%s skip=%s",
                candidate.wing,
                repricer_state,
                candidate.skip_reason or "unknown",
            )
            results.append(None)
            continue

        logger.info(
            "[exit-fallback][%s] gate=ok(%s) repricer=%s skip=-",
            candidate.wing,
            candidate.gate_message or "tradeability_ok",
            repricer_state,
        )
        results.append(dispatcher(candidate.plan))

    return results


class ExitFallbackExecutor:
    """High-level coordinator to trigger and execute exit fallbacks."""

    def __init__(
        self,
        *,
        dispatcher: Callable[[ExitOrderPlan], Any],
    ) -> None:
        self._dispatcher = dispatcher

    def execute(
        self,
        intent: ExitIntent,
        *,
        error: Exception | str | None = None,
        repricer_timeout: bool = False,
        cancel_on_no_fill: bool = False,
        repricer_steps: Mapping[str, str] | None = None,
    ) -> list[Any]:
        """Build wing plans and send them sequentially."""

        reason = detect_fallback_reason(
            error,
            repricer_timeout=repricer_timeout,
            cancel_on_no_fill=cancel_on_no_fill,
        )
        candidates = build_vertical_execution_candidates(intent)
        return dispatch_vertical_execution(
            candidates,
            self._dispatcher,
            reason=reason,
            repricer_steps=repricer_steps,
        )


__all__ = [
    "ExitFallbackReason",
    "VerticalExecutionCandidate",
    "detect_fallback_reason",
    "build_vertical_execution_candidates",
    "dispatch_vertical_execution",
    "default_exit_order_dispatcher",
    "ExitFallbackExecutor",
]

