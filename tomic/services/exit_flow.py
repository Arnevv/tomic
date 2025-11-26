"""High-level orchestration helpers for executing exit orders."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar
from uuid import uuid4

from tomic.config import get as cfg_get
from tomic.helpers.numeric import safe_float
from tomic.logutils import logger
from tomic.infrastructure.storage import save_json

T = TypeVar("T")
U = TypeVar("U")

from ._config import (
    exit_force_exit_config,
    exit_price_ladder_config,
    exit_spread_config,
)
from .exit_fallback import (
    build_vertical_execution_candidates,
    detect_fallback_reason,
)
from .exit_orders import ExitIntent, ExitOrderPlan, build_exit_order_plan
from .exit_fallback import default_exit_order_dispatcher


@dataclass(frozen=True)
class ExitAttemptResult:
    """Outcome for a single stage within the exit workflow."""

    stage: str
    status: str
    limit_price: float | None
    order_ids: tuple[int, ...]
    reason: str | None = None


@dataclass(frozen=True)
class ExitFlowResult:
    """Aggregated result for executing the exit workflow."""

    status: str
    reason: str | None
    limit_prices: tuple[float, ...]
    order_ids: tuple[int, ...]
    attempts: tuple[ExitAttemptResult, ...] = ()
    forced: bool = False
    errors: tuple[str, ...] = ()
    quote_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExitFlowConfig:
    """Resolved configuration for running the exit workflow."""

    host: str
    port: int
    client_id: int
    account: str | None
    order_type: str
    tif: str
    fetch_only: bool
    force_exit_enabled: bool
    market_order_on_force: bool
    log_directory: Path

    @classmethod
    def from_app_config(cls) -> "ExitFlowConfig":
        """Construct configuration from :mod:`tomic.config`."""

        host = str(cfg_get("IB_HOST", "127.0.0.1"))
        paper_mode = bool(cfg_get("IB_PAPER_MODE", True))
        port_key = "IB_PORT" if paper_mode else "IB_LIVE_PORT"
        default_port = 7497 if paper_mode else 7496
        port = int(cfg_get(port_key, default_port))
        client_id = int(cfg_get("IB_ORDER_CLIENT_ID", cfg_get("IB_CLIENT_ID", 100)))
        account_raw = str(cfg_get("IB_ACCOUNT_ALIAS", "") or "").strip()
        account = account_raw or None
        order_type = str(cfg_get("DEFAULT_ORDER_TYPE", "LMT")).upper()
        tif = str(cfg_get("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
        fetch_only = bool(cfg_get("IB_FETCH_ONLY", False))
        force_cfg = exit_force_exit_config()
        forced = bool(force_cfg.get("enabled", False))
        market = bool(force_cfg.get("market_order", False))
        export_dir = Path(cfg_get("EXPORT_DIR", "exports")) / "exit_results"
        return cls(
            host=host,
            port=port,
            client_id=client_id,
            account=account,
            order_type=order_type,
            tif=tif,
            fetch_only=fetch_only,
            force_exit_enabled=forced,
            market_order_on_force=market,
            log_directory=export_dir,
        )

    def order_type_for(self, force_exit: bool) -> str:
        """Return the order type to use for ``force_exit`` state."""

        if force_exit and self.market_order_on_force:
            return "MKT"
        return self.order_type

    def create_dispatcher(
        self,
        *,
        force_exit: bool,
        tif: str | None = None,
    ) -> Callable[[ExitOrderPlan], tuple[int, ...]]:
        """Return dispatcher calling IB with proper cleanup."""

        resolved_tif = (tif or self.tif).upper()
        order_type = self.order_type_for(force_exit)

        def _dispatch(plan: ExitOrderPlan) -> tuple[int, ...]:
            app = None
            try:
                result = default_exit_order_dispatcher(
                    plan,
                    host=self.host,
                    port=self.port,
                    client_id=self.client_id,
                    account=self.account,
                    order_type=order_type,
                    tif=resolved_tif,
                    force_exit=force_exit,
                )
                order_payload: Any = result
                if isinstance(result, Sequence) and len(result) == 2:
                    first, second = result
                    if hasattr(first, "disconnect"):
                        app = first  # type: ignore[assignment]
                        order_payload = second
                    elif hasattr(second, "disconnect"):
                        app = second  # type: ignore[assignment]
                        order_payload = first
                    else:
                        order_payload = second
                return _normalize_order_ids(order_payload)
            finally:
                if app is not None:
                    try:
                        app.disconnect()
                    except Exception:  # pragma: no cover - best effort cleanup
                        logger.debug(
                            "Kon IB verbinding niet sluiten na exit-dispatch",
                            exc_info=True,
                        )

        return _dispatch


def _fmt_ms(seconds: float) -> str:
    """Format seconds as milliseconds string."""
    return f"{seconds * 1000:.0f}ms"


def execute_exit_flow(
    intent: ExitIntent,
    *,
    config: ExitFlowConfig | None = None,
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]] | None = None,
    repricer_steps: Mapping[str, str] | None = None,
    force_exit: bool | None = None,
) -> ExitFlowResult:
    """Execute the exit workflow for ``intent`` and return a structured result."""

    t_flow_start = time.perf_counter()
    logger.info("[execute_exit_flow] START")

    # ===== Setup phase =====
    t_setup_start = time.perf_counter()
    cfg = config or ExitFlowConfig.from_app_config()
    forced = cfg.force_exit_enabled if force_exit is None else bool(force_exit)
    force_policy = exit_force_exit_config()
    limit_cap_cfg = force_policy.get("limit_cap") if forced else None
    active_dispatcher = dispatcher
    if active_dispatcher is None:
        active_dispatcher = cfg.create_dispatcher(force_exit=forced)
    t_setup_elapsed = time.perf_counter() - t_setup_start
    logger.info("[execute_exit_flow] setup: %s (forced=%s)", _fmt_ms(t_setup_elapsed), forced)

    attempts: list[ExitAttemptResult] = []
    limit_prices: list[float] = []
    placed_ids: list[int] = []

    # ===== Build order plan =====
    t_plan_start = time.perf_counter()
    try:
        plan = build_exit_order_plan(intent)
    except ValueError as exc:
        t_plan_elapsed = time.perf_counter() - t_plan_start
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.warning(
            "[execute_exit_flow] build_exit_order_plan FAILED: %s (%s, total: %s)",
            exc,
            _fmt_ms(t_plan_elapsed),
            _fmt_ms(t_flow_elapsed),
        )
        return ExitFlowResult(
            status="failed",
            reason=str(exc),
            limit_prices=tuple(),
            order_ids=tuple(),
            attempts=tuple(),
            forced=forced,
        )
    t_plan_elapsed = time.perf_counter() - t_plan_start
    logger.info(
        "[execute_exit_flow] build_exit_order_plan: %s (legs=%d, limit=%.2f)",
        _fmt_ms(t_plan_elapsed),
        len(plan.legs),
        plan.limit_price or 0,
    )

    base_limit = safe_float(plan.limit_price)

    policy = exit_spread_config()
    combo_mid = safe_float(getattr(plan.nbbo, "mid", None)) or 0.0
    combo_spread = safe_float(getattr(plan.nbbo, "width", None)) or 0.0
    allow_abs = safe_float(policy.get("absolute")) or 0.0
    rel_cfg = policy.get("relative")
    rel_value = safe_float(rel_cfg) or 0.0
    allow_rel = rel_value * combo_mid
    allow = max(allow_abs, allow_rel)

    logger.debug(
        f"[exit-policy] mid={combo_mid:.2f} spread={combo_spread:.2f} "
        f"abs_limit={allow_abs:.2f} rel_cfg={rel_cfg} rel_limit={allow_rel:.2f} "
        f"used_allow={allow:.2f} source=EXIT_ORDER_OPTIONS.spread"
    )

    if cfg.fetch_only:
        if base_limit is not None:
            limit_prices.append(base_limit)
        attempts.append(
            ExitAttemptResult(
                stage="primary",
                status="fetch_only",
                limit_price=base_limit,
                order_ids=tuple(),
                reason="fetch_only_mode",
            )
        )
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_exit_flow] DONE (fetch_only) total: %s", _fmt_ms(t_flow_elapsed))
        return ExitFlowResult(
            status="fetch_only",
            reason="fetch_only_mode",
            limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
            order_ids=tuple(),
            attempts=tuple(attempts),
            forced=forced,
        )

    ladder_cfg = exit_price_ladder_config()
    use_ladder = bool(ladder_cfg.get("enabled"))
    logger.info(
        "[execute_exit_flow] ladder_enabled=%s, steps=%s, step_wait=%ss",
        use_ladder,
        ladder_cfg.get("steps", []),
        ladder_cfg.get("step_wait_seconds", 0),
    )
    primary_error: Exception | None = None

    if use_ladder:
        t_ladder_start = time.perf_counter()
        logger.info("[execute_exit_flow] Starting price ladder dispatch...")
        (
            ladder_attempts,
            ladder_limits,
            ladder_ids,
            ladder_error,
        ) = _dispatch_with_price_ladder(
            plan,
            active_dispatcher,
            ladder_cfg=ladder_cfg,
            forced=forced,
            limit_cap=limit_cap_cfg,
        )
        t_ladder_elapsed = time.perf_counter() - t_ladder_start
        logger.info(
            "[execute_exit_flow] ladder dispatch: %s (attempts=%d, ids=%d)",
            _fmt_ms(t_ladder_elapsed),
            len(ladder_attempts),
            len(ladder_ids),
        )
        attempts.extend(ladder_attempts)
        limit_prices.extend(ladder_limits)
        if ladder_ids:
            placed_ids.extend(ladder_ids)
            final_stage = ladder_attempts[-1].stage if ladder_attempts else "primary"
            t_flow_elapsed = time.perf_counter() - t_flow_start
            logger.info(
                "[execute_exit_flow] DONE (ladder success) total: %s",
                _fmt_ms(t_flow_elapsed),
            )
            return ExitFlowResult(
                status="success",
                reason=final_stage,
                limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
                order_ids=_unique_values(placed_ids, transform=int),
                attempts=tuple(attempts),
                forced=forced,
            )
        primary_error = ladder_error or RuntimeError("price_ladder_failed")
        logger.info("[execute_exit_flow] ladder failed: %s", primary_error)
    else:
        t_primary_start = time.perf_counter()
        logger.info("[execute_exit_flow] Starting primary dispatch (no ladder)...")
        if base_limit is not None:
            limit_prices.append(base_limit)
        order_ids, dispatch_error = _call_dispatcher(active_dispatcher, plan)
        t_primary_elapsed = time.perf_counter() - t_primary_start
        logger.info(
            "[execute_exit_flow] primary dispatch: %s (ids=%d, error=%s)",
            _fmt_ms(t_primary_elapsed),
            len(order_ids) if order_ids else 0,
            dispatch_error,
        )
        if dispatch_error is not None:
            primary_error = dispatch_error
            attempts.append(
                ExitAttemptResult(
                    stage="primary",
                    status="failed",
                    limit_price=base_limit,
                    order_ids=tuple(),
                    reason=str(dispatch_error),
                )
            )
        else:
            status = "success" if order_ids else "failed"
            reason = None if order_ids else "no_order_ids"
            attempts.append(
                ExitAttemptResult(
                    stage="primary",
                    status=status,
                    limit_price=base_limit,
                    order_ids=order_ids,
                    reason=reason,
                )
            )
            if order_ids:
                placed_ids.extend(order_ids)
                t_flow_elapsed = time.perf_counter() - t_flow_start
                logger.info(
                    "[execute_exit_flow] DONE (primary success) total: %s",
                    _fmt_ms(t_flow_elapsed),
                )
                return ExitFlowResult(
                    status="success",
                    reason="primary",
                    limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
                    order_ids=_unique_values(placed_ids, transform=int),
                    attempts=tuple(attempts),
                    forced=forced,
                )
            primary_error = RuntimeError("no_orders")

    # ===== Fallback dispatch =====
    t_fallback_start = time.perf_counter()
    logger.info("[execute_exit_flow] Starting fallback dispatch...")
    (
        fallback_attempts,
        fallback_ids,
        fallback_limits,
        fallback_reason,
    ) = _execute_fallback(
        intent,
        active_dispatcher,
        error=primary_error,
        repricer_steps=repricer_steps,
    )
    t_fallback_elapsed = time.perf_counter() - t_fallback_start
    logger.info(
        "[execute_exit_flow] fallback dispatch: %s (attempts=%d, ids=%d)",
        _fmt_ms(t_fallback_elapsed),
        len(fallback_attempts),
        len(fallback_ids),
    )
    attempts.extend(fallback_attempts)
    limit_prices.extend(fallback_limits)
    placed_ids.extend(fallback_ids)

    # If fallback succeeded, return success
    if placed_ids:
        status = "success"
        reason = f"fallback:{fallback_reason}"
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info(
            "[execute_exit_flow] DONE (fallback success) total: %s",
            _fmt_ms(t_flow_elapsed),
        )
        return ExitFlowResult(
            status=status,
            reason=reason,
            limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
            order_ids=_unique_values(placed_ids, transform=int),
            attempts=tuple(attempts),
            forced=forced,
        )

    # If we reach here, primary and fallback both failed
    # Try force-exit if enabled
    if forced:
        t_force_start = time.perf_counter()
        logger.info("[execute_exit_flow] primary and fallback failed, attempting force-exit...")
        force_attempts, force_ids, force_limits, force_error = _execute_force_exit(
            intent,
            active_dispatcher,
            error=primary_error,
        )
        t_force_elapsed = time.perf_counter() - t_force_start
        logger.info(
            "[execute_exit_flow] force-exit dispatch: %s (ids=%d)",
            _fmt_ms(t_force_elapsed),
            len(force_ids),
        )
        attempts.extend(force_attempts)
        limit_prices.extend(force_limits)
        placed_ids.extend(force_ids)

        if placed_ids:
            status = "success"
            reason = "force_exit"
            t_flow_elapsed = time.perf_counter() - t_flow_start
            logger.info(
                "[execute_exit_flow] DONE (force-exit success) total: %s",
                _fmt_ms(t_flow_elapsed),
            )
            return ExitFlowResult(
                status=status,
                reason=reason,
                limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
                order_ids=_unique_values(placed_ids, transform=int),
                attempts=tuple(attempts),
                forced=forced,
            )

        # All paths failed
        all_errors = [str(primary_error or "primary_failed")]
        if force_error:
            all_errors.append(str(force_error))
        status = "failed"
        reason = " | ".join(all_errors)
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info(
            "[execute_exit_flow] DONE (all failed) total: %s",
            _fmt_ms(t_flow_elapsed),
        )
        return ExitFlowResult(
            status=status,
            reason=reason,
            limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
            order_ids=tuple(),
            attempts=tuple(attempts),
            forced=forced,
        )

    # Force-exit not enabled, return failure
    status = "failed"
    reason = str(primary_error or "no_orders")
    t_flow_elapsed = time.perf_counter() - t_flow_start
    logger.info(
        "[execute_exit_flow] DONE (failed, no force) total: %s",
        _fmt_ms(t_flow_elapsed),
    )
    return ExitFlowResult(
        status=status,
        reason=reason,
        limit_prices=_unique_values(limit_prices, transform=float, skip_none=True),
        order_ids=tuple(),
        attempts=tuple(attempts),
        forced=forced,
    )


def _execute_force_exit(
    intent: ExitIntent,
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]],
    *,
    error: Exception | None,
) -> tuple[list[ExitAttemptResult], list[int], list[float], Exception | None]:
    """Execute force-exit as last resort after primary and fallback failures."""

    logger.debug("[force-exit] attempting force exit with aggressive pricing")

    attempts: list[ExitAttemptResult] = []
    order_ids: list[int] = []
    limit_prices: list[float] = []

    try:
        plan = build_exit_order_plan(intent)
    except ValueError as exc:
        logger.warning("[force-exit] build_exit_order_plan failed: %s", exc)
        attempts.append(
            ExitAttemptResult(
                stage="force",
                status="failed",
                limit_price=None,
                order_ids=tuple(),
                reason=str(exc),
            )
        )
        return attempts, order_ids, limit_prices, exc

    limit_value = safe_float(plan.limit_price)
    if limit_value is not None:
        limit_prices.append(limit_value)

    ids, dispatch_error = _call_dispatcher(dispatcher, plan)
    if dispatch_error is not None:
        logger.error("[force-exit] dispatcher raised an error", exc_info=dispatch_error)
        attempts.append(
            ExitAttemptResult(
                stage="force",
                status="failed",
                limit_price=limit_value,
                order_ids=tuple(),
                reason=str(dispatch_error),
            )
        )
        return attempts, order_ids, limit_prices, dispatch_error

    if ids:
        order_ids.extend(ids)
        attempts.append(
            ExitAttemptResult(
                stage="force",
                status="success",
                limit_price=limit_value,
                order_ids=ids,
            )
        )
        return attempts, order_ids, limit_prices, None

    failure_reason = "no_order_ids"
    attempts.append(
        ExitAttemptResult(
            stage="force",
            status="failed",
            limit_price=limit_value,
            order_ids=tuple(),
            reason=failure_reason,
        )
    )
    return attempts, order_ids, limit_prices, RuntimeError("force_exit_no_orders")


def _execute_fallback(
    intent: ExitIntent,
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]],
    *,
    error: Exception,
    repricer_steps: Mapping[str, str] | None,
) -> tuple[list[ExitAttemptResult], list[int], list[float], str]:
    """Trigger vertical fallbacks and collect attempt metadata."""

    reason = detect_fallback_reason(
        error,
        repricer_timeout=False,
        cancel_on_no_fill=False,
    )
    candidates = build_vertical_execution_candidates(intent)
    logger.debug(
        "[exit-fallback] executing %d verticals (reason=%s)",
        len(candidates),
        reason.value,
    )

    attempts: list[ExitAttemptResult] = []
    order_ids: list[int] = []
    limit_prices: list[float] = []
    step_lookup = {k: v for k, v in (repricer_steps or {}).items()}

    for candidate in candidates:
        stage = f"fallback:{candidate.wing}"
        repricer_state = step_lookup.get(candidate.wing)
        if repricer_state is None:
            for alias in ("all", "combo", "primary"):
                if alias in step_lookup:
                    repricer_state = step_lookup[alias]
                    break
        if repricer_state is None:
            repricer_state = "skip"
        if candidate.plan is None:
            logger.debug(
                "[exit-fallback][%s] gate=fail repricer=%s skip=%s",
                candidate.wing,
                repricer_state,
                candidate.skip_reason or "unknown",
            )
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="skipped",
                    limit_price=None,
                    order_ids=tuple(),
                    reason=candidate.skip_reason,
                )
            )
            continue

        limit_value = safe_float(candidate.plan.limit_price)
        if limit_value is not None:
            limit_prices.append(limit_value)

        logger.debug(
            "[exit-fallback][%s] gate=ok(%s) repricer=%s skip=-",
            candidate.wing,
            candidate.gate_message or "tradeability_ok",
            repricer_state,
        )
        ids, dispatch_error = _call_dispatcher(dispatcher, candidate.plan)
        if dispatch_error is not None:  # pragma: no cover - defensive logging
            logger.error(
                "[exit-fallback][%s] dispatcher raised an error",
                candidate.wing,
                exc_info=dispatch_error,
            )
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="failed",
                    limit_price=limit_value,
                    order_ids=tuple(),
                    reason=str(dispatch_error),
                )
            )
            continue

        if ids:
            order_ids.extend(ids)
        status = "success" if ids else "failed"
        attempt_reason = None if ids else "no_order_ids"
        attempts.append(
            ExitAttemptResult(
                stage=stage,
                status=status,
                limit_price=limit_value,
                order_ids=ids,
                reason=attempt_reason,
            )
        )

    return attempts, order_ids, limit_prices, reason.value


def _resolve_limit_cap(mid: float | None, config: Mapping[str, Any] | None) -> float | None:
    if mid is None or not isinstance(config, Mapping):
        return None
    cap_type = str(config.get("type") or "").strip().lower()
    cap_value = safe_float(config.get("value"))
    if cap_value is None or cap_value <= 0:
        return None
    if cap_type == "absolute":
        return cap_value
    if cap_type == "bps":
        return abs(mid) * cap_value / 10000.0
    return None


def _apply_price_offset(
    plan: ExitOrderPlan,
    offset: float,
    *,
    forced: bool,
    limit_cap: Mapping[str, Any] | None,
) -> ExitOrderPlan | None:
    try:
        delta = float(offset)
    except (TypeError, ValueError):
        return None

    nbbo = plan.nbbo
    mid = safe_float(nbbo.mid)
    if mid is None:
        return None

    candidate = mid + delta
    bid = safe_float(nbbo.bid)
    ask = safe_float(nbbo.ask)
    if bid is not None:
        candidate = max(candidate, bid)
    if ask is not None:
        candidate = min(candidate, ask)

    if forced and limit_cap:
        cap_value = _resolve_limit_cap(mid, limit_cap)
        if cap_value is not None:
            candidate = max(mid - cap_value, min(mid + cap_value, candidate))

    min_tick = safe_float(plan.min_tick)
    if min_tick and min_tick > 0:
        candidate = round(candidate / min_tick) * min_tick

    if bid is not None and candidate < bid:
        candidate = bid
    if ask is not None and candidate > ask:
        candidate = ask

    candidate = round(candidate + 1e-9, 4)
    if candidate <= 0:
        return None

    return replace(plan, limit_price=candidate)


def _dispatch_with_price_ladder(
    plan: ExitOrderPlan,
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]],
    *,
    ladder_cfg: Mapping[str, Any],
    forced: bool,
    limit_cap: Mapping[str, Any] | None,
) -> tuple[list[ExitAttemptResult], list[float], list[int], Exception | None]:
    steps: list[float] = [0.0]
    raw_steps = ladder_cfg.get("steps", []) or []
    for value in raw_steps:
        try:
            steps.append(float(value))
        except (TypeError, ValueError):
            continue

    wait_seconds = safe_float(ladder_cfg.get("step_wait_seconds")) or 0.0
    wait_seconds = max(wait_seconds, 0.0)
    max_duration = safe_float(ladder_cfg.get("max_duration_seconds")) or 0.0
    max_duration = max(max_duration, 0.0)

    logger.info(
        "[price_ladder] START: %d steps, wait=%ss, max_duration=%ss",
        len(steps),
        wait_seconds,
        max_duration,
    )

    attempts: list[ExitAttemptResult] = []
    limit_prices: list[float] = []
    placed_ids: list[int] = []
    seen_prices: set[float] = set()
    last_error: Exception | None = None
    start = time.monotonic()
    total_wait_time = 0.0

    for idx, offset in enumerate(steps):
        t_step_start = time.perf_counter()
        stage = "primary" if idx == 0 else f"ladder:{idx}"
        logger.info(
            "[price_ladder] step %d/%d: stage=%s, offset=%.4f",
            idx + 1,
            len(steps),
            stage,
            offset,
        )

        if idx == 0 and abs(offset) < 1e-9:
            candidate_plan = plan
        else:
            candidate_plan = _apply_price_offset(
                plan,
                offset,
                forced=forced,
                limit_cap=limit_cap,
            )
        if candidate_plan is None:
            logger.info("[price_ladder] step %d: SKIPPED (invalid_limit)", idx + 1)
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="skipped",
                    limit_price=None,
                    order_ids=tuple(),
                    reason="invalid_limit",
                )
            )
            continue

        price = safe_float(candidate_plan.limit_price)
        normalized_price = round(price, 4) if price is not None else None
        if normalized_price is not None:
            if normalized_price in seen_prices:
                logger.info(
                    "[price_ladder] step %d: SKIPPED (duplicate_price=%.4f)",
                    idx + 1,
                    price,
                )
                attempts.append(
                    ExitAttemptResult(
                        stage=stage,
                        status="skipped",
                        limit_price=price,
                        order_ids=tuple(),
                        reason="duplicate_price",
                    )
                )
                continue
            seen_prices.add(normalized_price)
            limit_prices.append(price)

        t_dispatch_start = time.perf_counter()
        ids, dispatch_error = _call_dispatcher(dispatcher, candidate_plan)
        t_dispatch_elapsed = time.perf_counter() - t_dispatch_start

        if dispatch_error is not None:
            last_error = dispatch_error
            logger.info(
                "[price_ladder] step %d: FAILED dispatch (%s) price=%.4f, took %s",
                idx + 1,
                dispatch_error,
                price or 0,
                _fmt_ms(t_dispatch_elapsed),
            )
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="failed",
                    limit_price=price,
                    order_ids=tuple(),
                    reason=str(dispatch_error),
                )
            )
            continue

        if ids:
            t_step_elapsed = time.perf_counter() - t_step_start
            logger.info(
                "[price_ladder] step %d: SUCCESS! price=%.4f, ids=%s, dispatch=%s, step=%s",
                idx + 1,
                price or 0,
                ids,
                _fmt_ms(t_dispatch_elapsed),
                _fmt_ms(t_step_elapsed),
            )
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="success",
                    limit_price=price,
                    order_ids=ids,
                )
            )
            placed_ids.extend(ids)
            total_elapsed = time.monotonic() - start
            logger.info(
                "[price_ladder] DONE (success at step %d) total=%s, waited=%ss",
                idx + 1,
                _fmt_ms(total_elapsed),
                total_wait_time,
            )
            return attempts, limit_prices, placed_ids, None

        logger.info(
            "[price_ladder] step %d: FAILED (no_order_ids) price=%.4f, dispatch=%s",
            idx + 1,
            price or 0,
            _fmt_ms(t_dispatch_elapsed),
        )
        attempts.append(
            ExitAttemptResult(
                stage=stage,
                status="failed",
                limit_price=price,
                order_ids=tuple(),
                reason="no_order_ids",
            )
        )

        if idx < len(steps) - 1:
            wait_time = wait_seconds
            if max_duration > 0:
                elapsed = time.monotonic() - start
                remaining = max_duration - elapsed
                if remaining <= 0:
                    logger.info(
                        "[price_ladder] max_duration reached (%.1fs), stopping early",
                        elapsed,
                    )
                    break
                if wait_time > 0:
                    wait_time = min(wait_time, remaining)
                else:
                    wait_time = max(0.0, remaining)
            if wait_time > 0:
                logger.info("[price_ladder] sleeping %.2fs before next step...", wait_time)
                time.sleep(wait_time)
                total_wait_time += wait_time

    if last_error is None:
        last_error = RuntimeError("price_ladder_failed")
    total_elapsed = time.monotonic() - start
    logger.info(
        "[price_ladder] DONE (failed all %d steps) total=%s, waited=%ss",
        len(steps),
        _fmt_ms(total_elapsed),
        total_wait_time,
    )
    return attempts, limit_prices, placed_ids, last_error


def store_exit_flow_result(
    intent: ExitIntent,
    result: ExitFlowResult,
    *,
    directory: Path | None = None,
    timestamp: datetime | None = None,
) -> Path:
    """Persist ``result`` to disk and return the created path."""

    base_dir = Path(directory) if directory is not None else ExitFlowConfig.from_app_config().log_directory
    moment = timestamp or datetime.utcnow()
    day_dir = base_dir / moment.strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    target = day_dir / f"exit_result_{moment.strftime('%H%M%S')}_{uuid4().hex[:8]}.json"

    payload = {
        "timestamp": moment.isoformat(),
        "status": result.status,
        "reason": result.reason,
        "order_ids": list(result.order_ids),
        "limit_prices": list(result.limit_prices),
        "forced": result.forced,
        "symbol": _intent_symbol(intent),
        "expiry": _intent_expiry(intent),
        "trade_id": _intent_trade_id(intent),
        "strategy": _intent_strategy_name(intent),
        "attempts": [
            {
                "stage": attempt.stage,
                "status": attempt.status,
                "reason": attempt.reason,
                "limit_price": attempt.limit_price,
                "order_ids": list(attempt.order_ids),
            }
            for attempt in result.attempts
        ],
    }

    save_json(payload, target)
    return target


def _normalize_order_ids(order_ids: Iterable[Any] | None) -> tuple[int, ...]:
    result: list[int] = []
    if order_ids is None:
        return tuple()
    for item in order_ids:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes, bytearray)):
            result.extend(_normalize_order_ids(item))
            continue
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        result.append(value)
    return tuple(result)


def _unique_values(
    values: Iterable[T],
    *,
    transform: Callable[[T], U] | None = None,
    skip_none: bool = False,
) -> tuple[U | T, ...]:
    result: list[U | T] = []
    for value in values:
        if skip_none and value is None:
            continue
        item: U | T
        item = transform(value) if transform else value
        if item in result:
            continue
        result.append(item)
    return tuple(result)


def _call_dispatcher(
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]],
    plan: ExitOrderPlan,
) -> tuple[tuple[int, ...], Exception | None]:
    try:
        ids = _normalize_order_ids(dispatcher(plan))
    except Exception as exc:  # pragma: no cover - dispatcher failures bubble up
        return tuple(), exc
    return ids, None
def _intent_strategy(intent: ExitIntent) -> Mapping[str, Any]:
    strategy = intent.strategy
    if isinstance(strategy, Mapping):
        return strategy
    return {}


def _intent_symbol(intent: ExitIntent) -> str | None:
    strategy = _intent_strategy(intent)
    symbol = strategy.get("symbol") or strategy.get("underlying")
    if symbol in (None, ""):
        for leg in intent.legs or []:
            if isinstance(leg, Mapping) and leg.get("symbol") not in (None, ""):
                symbol = leg.get("symbol")
                break
    if symbol in (None, ""):
        return None
    return str(symbol)


def _intent_expiry(intent: ExitIntent) -> str | None:
    strategy = _intent_strategy(intent)
    expiry = strategy.get("expiry")
    if expiry in (None, ""):
        for leg in intent.legs or []:
            if isinstance(leg, Mapping) and leg.get("expiry") not in (None, ""):
                expiry = leg.get("expiry")
                break
    if expiry in (None, ""):
        return None
    return str(expiry)


def _intent_trade_id(intent: ExitIntent) -> Any:
    strategy = _intent_strategy(intent)
    return strategy.get("trade_id") or strategy.get("TradeID")


def _intent_strategy_name(intent: ExitIntent) -> str | None:
    strategy = _intent_strategy(intent)
    name = strategy.get("type") or strategy.get("strategy")
    if name in (None, ""):
        return None
    return str(name)


def intent_symbol(intent: Any) -> str | None:
    """Return the canonical symbol for ``intent`` if available."""

    return _intent_symbol(intent)  # type: ignore[arg-type]


def intent_expiry(intent: Any) -> str | None:
    """Return the canonical expiry for ``intent`` if available."""

    return _intent_expiry(intent)  # type: ignore[arg-type]


def intent_strategy_name(intent: Any) -> str | None:
    """Return the configured strategy name for ``intent`` if available."""

    return _intent_strategy_name(intent)  # type: ignore[arg-type]


def intent_strategy_payload(intent: Any) -> Mapping[str, Any]:
    """Return the raw strategy mapping for ``intent``."""

    return _intent_strategy(intent)  # type: ignore[arg-type]


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def resolve_exit_intent_freshen_config() -> tuple[int, float]:
    """Return (attempts, wait_s) for exit intent quote freshening."""

    attempts_default = 3
    wait_default = 0.3
    attempts_cfg = cfg_get("EXIT_INTENT_FRESHEN_ATTEMPTS", attempts_default)
    wait_cfg = cfg_get("EXIT_INTENT_FRESHEN_WAIT_S", wait_default)
    attempts = max(_coerce_int(attempts_cfg, attempts_default), 0)
    wait_s = max(_coerce_float(wait_cfg, wait_default), 0.0)
    return attempts, wait_s


__all__ = [
    "ExitAttemptResult",
    "ExitFlowConfig",
    "ExitFlowResult",
    "execute_exit_flow",
    "intent_expiry",
    "intent_strategy_name",
    "intent_strategy_payload",
    "intent_symbol",
    "resolve_exit_intent_freshen_config",
    "store_exit_flow_result",
]
