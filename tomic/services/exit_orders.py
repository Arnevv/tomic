"""Build actionable exit order plans from exit intents."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from tomic.logutils import logger
from tomic.metrics import calculate_credit
from tomic.utils import get_leg_qty

from .order_submission import (
    ComboQuote,
    _collect_min_tick,
    _compute_combo_nbbo,
    _evaluate_tradeability,
    _guard_limit_price_scale,
    _normalize_leg_summary,
)
from ._config import exit_fallback_config, exit_force_exit_config, exit_spread_config
from .trade_management_service import StrategyExitIntent


ExitIntent = StrategyExitIntent


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ExitOrderPlan:
    """Actionable combo order parameters for closing a strategy."""

    intent: ExitIntent
    legs: tuple[Mapping[str, Any], ...]
    quantity: int
    action: str
    limit_price: float
    nbbo: ComboQuote
    tradeability: str
    per_combo_credit: float
    min_tick: float | None


def _ensure_leg_metadata(
    leg: dict[str, Any],
    *,
    fallback_symbol: str | None,
    fallback_expiry: str | None,
) -> None:
    if fallback_symbol and not leg.get("symbol"):
        leg["symbol"] = fallback_symbol
    if not leg.get("expiry"):
        for key in ("expiry", "lastTradeDate", "lastTradeDateOrContractMonth", "expiration"):
            value = leg.get(key)
            if value:
                leg["expiry"] = value
                break
        else:
            if fallback_expiry:
                leg["expiry"] = fallback_expiry


def _infer_combo_quantity(legs: Iterable[Mapping[str, Any]]) -> int:
    gcd_value = 0
    for leg in legs:
        try:
            qty = int(round(get_leg_qty(dict(leg))))
        except Exception:
            qty = 1
        qty = abs(qty)
        if qty <= 0:
            continue
        if gcd_value == 0:
            gcd_value = qty
        else:
            gcd_value = math.gcd(gcd_value, qty)
    return max(gcd_value, 1)


def _normalize_legs(
    legs: Sequence[Mapping[str, Any]],
    *,
    symbol: str | None,
    expiry: str | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for leg in legs:
        leg_copy = dict(leg)
        _ensure_leg_metadata(leg_copy, fallback_symbol=symbol, fallback_expiry=expiry)
        normalized.append(leg_copy)
    if not normalized:
        raise ValueError("exit intent mist legs")
    return normalized


def build_exit_order_plan(intent: ExitIntent) -> ExitOrderPlan:
    """Return an :class:`ExitOrderPlan` for ``intent`` based on combo NBBO data."""

    strategy = intent.strategy or {}
    symbol = strategy.get("symbol") if isinstance(strategy, Mapping) else None
    expiry = strategy.get("expiry") if isinstance(strategy, Mapping) else None

    source_legs: Sequence[Mapping[str, Any]]
    if intent.legs:
        source_legs = intent.legs
    elif isinstance(strategy, Mapping):
        source_legs = strategy.get("legs", []) or []
    else:
        source_legs = []

    legs = _normalize_legs(source_legs, symbol=symbol, expiry=expiry)

    summaries = [_normalize_leg_summary(leg) for leg in legs]
    combo_quantity = _infer_combo_quantity(legs)
    min_tick = _collect_min_tick(summaries)
    combo_quote = _compute_combo_nbbo(summaries, combo_quantity, min_tick=min_tick)
    if combo_quote is None:
        raise ValueError("combo mist betrouwbare NBBO")

    spread_cfg = exit_spread_config()
    fallback_cfg = exit_fallback_config()
    force_cfg = exit_force_exit_config()

    tradeable, tradeability_message = _evaluate_tradeability(
        summaries,
        combo_quote,
        spread=spread_cfg,
        max_quote_age=spread_cfg.get("max_quote_age"),
        allow_fallback=bool(fallback_cfg.get("allow_preview", False)),
        allowed_fallback_sources=fallback_cfg.get("allowed_sources"),
        force=bool(force_cfg.get("enabled", False)),
    )
    if not tradeable:
        combo_mid = _safe_float(getattr(combo_quote, "mid", None)) or 0.0
        combo_spread = _safe_float(getattr(combo_quote, "width", None)) or 0.0
        allow_abs = _safe_float(spread_cfg.get("absolute")) or 0.0
        rel_cfg = spread_cfg.get("relative")
        rel_value = _safe_float(rel_cfg) or 0.0
        allow_rel = rel_value * combo_mid
        allow = max(allow_abs, allow_rel)
        logger.info(
            "[exit-policy] mid=%.2f spread=%.2f abs_limit=%.2f rel_cfg=%s rel_limit=%.2f "
            "used_allow=%.2f source=EXIT_ORDER_OPTIONS.spread",
            combo_mid,
            combo_spread,
            allow_abs,
            rel_cfg,
            allow_rel,
            allow,
        )
        raise ValueError(f"combo niet verhandelbaar: {tradeability_message}")

    net_credit = calculate_credit(legs)
    per_combo_credit = net_credit / combo_quantity if combo_quantity else net_credit

    limit_price = combo_quote.mid
    if limit_price <= 0:
        raise ValueError("limit price ongeldig")
    if not (combo_quote.bid - 1e-9 <= limit_price <= combo_quote.ask + 1e-9):
        raise ValueError("limit price valt buiten NBBO")

    _guard_limit_price_scale(SimpleNamespace(lmtPrice=limit_price), credit_for_scale=per_combo_credit)

    action = "BUY" if net_credit > 0 else "SELL"
    if math.isclose(net_credit, 0.0, abs_tol=1e-9):
        action = "SELL"

    return ExitOrderPlan(
        intent=intent,
        legs=tuple(legs),
        quantity=combo_quantity,
        action=action,
        limit_price=limit_price,
        nbbo=combo_quote,
        tradeability=tradeability_message,
        per_combo_credit=per_combo_credit,
        min_tick=min_tick,
    )


__all__ = ["ExitIntent", "ExitOrderPlan", "build_exit_order_plan"]
