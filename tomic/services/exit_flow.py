"""High-level orchestration helpers for executing exit orders."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from tomic.config import get as cfg_get
from tomic.helpers.numeric import safe_float
from tomic.logutils import logger

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


def execute_exit_flow(
    intent: ExitIntent,
    *,
    config: ExitFlowConfig | None = None,
    dispatcher: Callable[[ExitOrderPlan], Iterable[int]] | None = None,
    repricer_steps: Mapping[str, str] | None = None,
    force_exit: bool | None = None,
) -> ExitFlowResult:
    """Execute the exit workflow for ``intent`` and return a structured result."""

    cfg = config or ExitFlowConfig.from_app_config()
    forced = cfg.force_exit_enabled if force_exit is None else bool(force_exit)
    force_policy = exit_force_exit_config()
    limit_cap_cfg = force_policy.get("limit_cap") if forced else None
    active_dispatcher = dispatcher
    if active_dispatcher is None:
        active_dispatcher = cfg.create_dispatcher(force_exit=forced)

    attempts: list[ExitAttemptResult] = []
    limit_prices: list[float] = []
    placed_ids: list[int] = []

    try:
        plan = build_exit_order_plan(intent)
    except ValueError as exc:
        return ExitFlowResult(
            status="failed",
            reason=str(exc),
            limit_prices=tuple(),
            order_ids=tuple(),
            attempts=tuple(),
            forced=forced,
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
        return ExitFlowResult(
            status="fetch_only",
            reason="fetch_only_mode",
            limit_prices=_unique_non_null(limit_prices),
            order_ids=tuple(),
            attempts=tuple(attempts),
            forced=forced,
        )

    ladder_cfg = exit_price_ladder_config()
    use_ladder = bool(ladder_cfg.get("enabled"))
    primary_error: Exception | None = None

    if use_ladder:
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
        attempts.extend(ladder_attempts)
        limit_prices.extend(ladder_limits)
        if ladder_ids:
            placed_ids.extend(ladder_ids)
            final_stage = ladder_attempts[-1].stage if ladder_attempts else "primary"
            return ExitFlowResult(
                status="success",
                reason=final_stage,
                limit_prices=_unique_non_null(limit_prices),
                order_ids=_unique_ints(placed_ids),
                attempts=tuple(attempts),
                forced=forced,
            )
        primary_error = ladder_error or RuntimeError("price_ladder_failed")
    else:
        if base_limit is not None:
            limit_prices.append(base_limit)
        try:
            order_ids = _normalize_order_ids(active_dispatcher(plan))
        except Exception as exc:  # main bag failed → fallback
            primary_error = exc
            attempts.append(
                ExitAttemptResult(
                    stage="primary",
                    status="failed",
                    limit_price=base_limit,
                    order_ids=tuple(),
                    reason=str(exc),
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
                return ExitFlowResult(
                    status="success",
                    reason="primary",
                    limit_prices=_unique_non_null(limit_prices),
                    order_ids=_unique_ints(placed_ids),
                    attempts=tuple(attempts),
                    forced=forced,
                )
            primary_error = RuntimeError("no_orders")

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
    attempts.extend(fallback_attempts)
    limit_prices.extend(fallback_limits)
    placed_ids.extend(fallback_ids)
    status = "success" if placed_ids else "failed"
    reason = f"fallback:{fallback_reason}" if placed_ids else str(primary_error or "no_orders")
    return ExitFlowResult(
        status=status,
        reason=reason,
        limit_prices=_unique_non_null(limit_prices),
        order_ids=_unique_ints(placed_ids),
        attempts=tuple(attempts),
        forced=forced,
    )


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
        repricer_state = step_lookup.get(candidate.wing, "skip")
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
        try:
            ids = _normalize_order_ids(dispatcher(candidate.plan))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "[exit-fallback][%s] dispatcher raised an error",
                candidate.wing,
            )
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="failed",
                    limit_price=limit_value,
                    order_ids=tuple(),
                    reason=str(exc),
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

    attempts: list[ExitAttemptResult] = []
    limit_prices: list[float] = []
    placed_ids: list[int] = []
    seen_prices: set[float] = set()
    last_error: Exception | None = None
    start = time.monotonic()

    for idx, offset in enumerate(steps):
        stage = "primary" if idx == 0 else f"ladder:{idx}"
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

        try:
            ids = _normalize_order_ids(dispatcher(candidate_plan))
        except Exception as exc:  # pragma: no cover - dispatcher failure
            last_error = exc
            attempts.append(
                ExitAttemptResult(
                    stage=stage,
                    status="failed",
                    limit_price=price,
                    order_ids=tuple(),
                    reason=str(exc),
                )
            )
        else:
            if ids:
                attempts.append(
                    ExitAttemptResult(
                        stage=stage,
                        status="success",
                        limit_price=price,
                        order_ids=ids,
                    )
                )
                placed_ids.extend(ids)
                return attempts, limit_prices, placed_ids, None

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
                    break
                if wait_time > 0:
                    wait_time = min(wait_time, remaining)
                else:
                    wait_time = max(0.0, remaining)
            if wait_time > 0:
                time.sleep(wait_time)

    if last_error is None:
        last_error = RuntimeError("price_ladder_failed")
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

    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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


def _unique_non_null(values: Iterable[float | None]) -> tuple[float, ...]:
    seen: list[float] = []
    for value in values:
        if value is None:
            continue
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def _unique_ints(values: Iterable[int]) -> tuple[int, ...]:
    seen: list[int] = []
    for value in values:
        ivalue = int(value)
        if ivalue not in seen:
            seen.append(ivalue)
    return tuple(seen)
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


__all__ = [
    "ExitAttemptResult",
    "ExitFlowConfig",
    "ExitFlowResult",
    "execute_exit_flow",
    "store_exit_flow_result",
]
