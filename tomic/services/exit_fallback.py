"""Helpers to orchestrate exit order fallbacks for exit flows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from tomic.helpers.numeric import safe_float
from tomic.logutils import logger
from tomic.strategy.models import StrategyProposal

from ._config import exit_fallback_config, exit_force_exit_config, exit_spread_config
from .exit_orders import (
    ExitIntent,
    ExitOrderPlan,
    build_exit_order_plan,
    build_exit_spread_policy,
)
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
    """Container describing an exit candidate for fallback execution."""

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


def build_vertical_execution_candidates(
    intent: ExitIntent,
) -> list[VerticalExecutionCandidate]:
    """Build a single fallback candidate for the full intent."""

    legs_iterable: Iterable[Mapping[str, Any]] = intent.legs or []
    full_width = _infer_spread_width(legs_iterable)

    try:
        plan = build_exit_order_plan(intent)
    except ValueError as exc:
        return [
            VerticalExecutionCandidate(
                wing="all",
                plan=None,
                width=full_width,
                gate_message=None,
                skip_reason=str(exc),
            )
        ]

    width = _infer_spread_width(plan.legs)
    return [
        VerticalExecutionCandidate(
            wing="all",
            plan=plan,
            width=width,
            gate_message=plan.tradeability,
        )
    ]


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
    force_exit: bool | None = None,
):
    """Submit ``plan`` via :class:`OrderSubmissionService` and return placement result."""

    spread_cfg = exit_spread_config()
    fallback_cfg = exit_fallback_config()
    force_cfg = exit_force_exit_config()

    spread_policy = build_exit_spread_policy(spread_cfg)
    allow_fallback = bool(fallback_cfg.get("allow_preview", False))
    allowed_sources = fallback_cfg.get("allowed_sources")
    max_quote_age = safe_float(spread_cfg.get("max_quote_age"))
    forced = force_exit if force_exit is not None else bool(force_cfg.get("enabled", False))

    submission = service or OrderSubmissionService(
        spread_policy=spread_policy,
        max_quote_age=max_quote_age,
        allow_fallback=allow_fallback,
        allowed_fallback_sources=allowed_sources,
        force=forced,
    )
    proposal = _proposal_from_exit_plan(plan)
    symbol = _resolve_symbol(plan) or ""
    instructions = submission.build_instructions(
        proposal,
        symbol=symbol,
        account=account,
        order_type=order_type,
        tif=tif,
        spread_overrides=spread_cfg,
        max_quote_age=max_quote_age,
        allow_fallback=allow_fallback,
        allowed_fallback_sources=allowed_sources,
        force=forced,
    )
    return submission.place_orders(
        instructions,
        host=host,
        port=port,
        client_id=client_id,
    )


def _resolve_repricer_state(
    step_lookup: Mapping[str, str],
    wing: str,
) -> str:
    """Resolve repricer state for a candidate using common aliases."""

    for key in (wing, "all", "combo", "primary"):
        if key in step_lookup:
            return step_lookup[key]
    return "skip"


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
        repricer_state = _resolve_repricer_state(step_lookup, candidate.wing)
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
        """Build fallback plans and send them sequentially."""

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

