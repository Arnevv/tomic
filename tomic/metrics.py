from __future__ import annotations


"""Utility functions for option metrics calculations."""

from math import inf
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Protocol, Tuple

from .core import LegView
from .helpers.numeric import safe_float
from .utils import get_leg_right, get_leg_qty, get_option_mid_price
from .logutils import logger
from .config import get as cfg_get


ResolverReturn = Tuple[float | None, str | None, float | None]


class PriceResolver(Protocol):
    """Protocol describing callables capable of resolving leg mid prices."""

    def __call__(self, leg: Mapping[str, Any]) -> ResolverReturn:
        ...


PriceResolverLike = PriceResolver | type[PriceResolver] | None
LegLike = LegView | Mapping[str, Any]


def _ensure_resolver(resolver: PriceResolverLike) -> PriceResolver:
    if resolver is None:
        return MidPriceResolver()
    if isinstance(resolver, type):
        return resolver()
    return resolver


def _normalized_mid_source(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if not value:
        return None
    if value == "parity":
        return "parity_true"
    return value


class MidPriceResolver:
    """Resolve mid price data using leg quotes and fallbacks."""

    def __call__(self, leg: Mapping[str, Any]) -> ResolverReturn:
        return self.resolve(leg)

    def resolve(self, leg: Mapping[str, Any]) -> ResolverReturn:
        price, used_close = get_option_mid_price(leg)
        leg_source = _normalized_mid_source(leg.get("mid_source"))
        fallback_source = _normalized_mid_source(leg.get("mid_fallback"))
        source = leg_source or fallback_source
        if used_close and source in {None, "true"}:
            source = "close"
        quote_age = safe_float(leg.get("quote_age_sec"))
        return price, source, quote_age


def _option_direction(leg: Mapping[str, Any]) -> int:
    """Return +1 for long legs and -1 for short legs."""

    action = str(leg.get("action", "")).upper()
    if action in {"BUY", "LONG"}:
        return 1
    if action in {"SELL", "SHORT"}:
        return -1
    pos = leg.get("position")
    if pos is not None:
        try:
            return 1 if float(pos) > 0 else -1
        except Exception:
            return 1
    return 1


def get_signed_position(leg: Mapping[str, Any]) -> float:
    """Return signed quantity for ``leg`` using best available signals."""

    position = leg.get("position")
    if position not in (None, ""):
        try:
            return float(position)
        except (TypeError, ValueError):
            logger.debug("[metrics] Ignoring non-numeric position %r", position)

    for key in ("qty", "quantity"):
        raw_qty = leg.get(key)
        if raw_qty in (None, ""):
            continue
        try:
            qty_val = abs(float(raw_qty))
        except (TypeError, ValueError):
            logger.debug("[metrics] Ignoring non-numeric %s value %r", key, raw_qty)
            continue
        direction = _option_direction(leg)
        return direction * qty_val

    try:
        qty = get_leg_qty(leg)
    except Exception:
        qty = 1.0
    direction = _option_direction(leg)
    return direction * qty


def iter_leg_views(
    legs: Iterable[LegLike], *, price_resolver: PriceResolverLike = MidPriceResolver
) -> Iterator[LegView]:
    """Yield :class:`LegView` objects for ``legs`` using ``price_resolver``."""

    resolver = _ensure_resolver(price_resolver)
    for leg in legs:
        if isinstance(leg, LegView):
            yield leg
            continue
        if not isinstance(leg, Mapping):
            continue

        strike = safe_float(leg.get("strike"))
        right = get_leg_right(leg) or None
        expiry_raw = leg.get("expiry") or leg.get("expiration")
        expiry = str(expiry_raw).strip() if isinstance(expiry_raw, str) else None
        if expiry == "":
            expiry = None

        signed_position = get_signed_position(leg)
        abs_qty = abs(signed_position) if signed_position else 0.0
        if abs_qty == 0:
            try:
                abs_qty = float(get_leg_qty(leg))
            except Exception:
                abs_qty = 0.0

        mid, resolved_source, resolved_quote_age = resolver(leg)
        quote_age = resolved_quote_age
        if quote_age is None:
            quote_age = safe_float(leg.get("quote_age"))

        leg_source = _normalized_mid_source(leg.get("mid_source"))
        fallback_source = _normalized_mid_source(leg.get("mid_fallback"))
        mid_source = resolved_source or leg_source or fallback_source

        yield LegView(
            strike=strike,
            right=right,
            expiry=expiry,
            signed_position=signed_position,
            abs_qty=abs_qty,
            mid=mid,
            mid_source=mid_source,
            quote_age=quote_age,
        )


def calculate_edge(theoretical: float, mid_price: float) -> float:
    """Return theoretical minus mid price."""
    return theoretical - mid_price


def calculate_rom(max_profit: float, margin: float) -> Optional[float]:
    """Return return on margin as percentage or ``None`` if margin is zero."""
    if not margin:
        return None
    return (max_profit / margin) * 100


def calculate_credit(
    legs: Iterable[LegLike], *, price_resolver: PriceResolverLike = MidPriceResolver
) -> float:
    """Return net credit in dollars for ``legs`` using consistent pricing."""

    credit = 0.0
    for view in iter_leg_views(legs, price_resolver=price_resolver):
        if view.mid is None or view.abs_qty <= 0 or view.signed_position == 0:
            continue
        direction = 1 if view.signed_position > 0 else -1
        credit -= direction * view.mid * view.abs_qty
    return credit * 100


def calculate_pos(delta: float) -> float:
    """Approximate probability of success from delta (0-1 range)."""
    return (1 - abs(delta)) * 100


def calculate_ev(pos: float, max_profit: float, max_loss: float) -> float:
    """Return expected value given probability of success and payoff values."""
    prob = pos / 100
    return prob * max_profit + (1 - prob) * max_loss


def calculate_payoff_at_spot(
    legs: Iterable[dict],
    spot_price: float,
    net_cashflow: Optional[float] = None,
) -> float:
    """Return total P&L in dollars for ``legs`` at ``spot_price``.

    ``net_cashflow`` represents the initial debit or credit of the strategy in
    per-share terms. If omitted, it is computed as ``sum(mid * position)`` for
    all legs, where ``position`` reflects signed quantity (positive for long,
    negative for short).
    """

    if net_cashflow is None:
        net_cashflow = 0.0
        for leg in legs:
            price = float(leg.get("mid", 0) or 0)
            qty = get_leg_qty(leg)
            net_cashflow += price * _option_direction(leg) * qty

    total = -net_cashflow * 100
    for leg in legs:
        qty = get_leg_qty(leg)
        position = _option_direction(leg) * qty
        right = get_leg_right(leg)
        strike = float(leg.get("strike"))
        if right == "call":
            intrinsic = max(spot_price - strike, 0)
        else:
            intrinsic = max(strike - spot_price, 0)
        total += position * intrinsic * 100
    return total


def estimate_scenario_profit(
    legs: Iterable[dict],
    spot_price: float,
    strategy_type: str,
) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Estimate P&L for configured scenario moves.

    Returns a tuple of (results, error). ``results`` is a list of dictionaries
    each containing ``pnl`` along with ``scenario_spot``, ``scenario_label`` and
    ``preferred_move``. If no scenario configuration exists for the provided
    strategy, ``results`` is ``None`` and ``error`` contains the string
    ``"no scenario defined"``.
    """

    scenarios_cfg = cfg_get("STRATEGY_SCENARIOS") or {}
    strat_key = strategy_type.lower().replace(" ", "_")
    strat_scenarios = scenarios_cfg.get(strat_key)
    if not strat_scenarios:
        return None, "no scenario defined"

    results: List[Dict[str, Any]] = []
    for scenario in strat_scenarios:
        move_pct = float(getattr(scenario, "scenario_move_pct", 0) or 0)
        scenario_spot = spot_price * (1 + move_pct / 100)
        pnl = calculate_payoff_at_spot(legs, scenario_spot)
        results.append(
            {
                "pnl": pnl,
                "scenario_spot": scenario_spot,
                "scenario_label": getattr(scenario, "scenario_label", None),
                "preferred_move": getattr(scenario, "preferred_move", None),
            }
        )

    return results, None


def _max_loss(
    legs: Iterable[dict], *, net_cashflow: float = 0.0
) -> float:
    """Return worst-case loss for ``legs`` with given net cashflow."""

    strikes = sorted(float(leg.get("strike", 0)) for leg in legs)
    if not strikes:
        raise ValueError("Missing strike information")
    high = strikes[-1] * 10

    def payoff(price: float) -> float:
        # ``net_cashflow`` here follows the convention of being positive for a
        # credit. ``calculate_payoff_at_spot`` expects the opposite sign.
        return calculate_payoff_at_spot(legs, price, net_cashflow=-net_cashflow)

    slope_high = sum(
        _option_direction(leg)
        * abs(float(leg.get("qty") or leg.get("quantity") or leg.get("position") or 1))
        for leg in legs
        if get_leg_right(leg) == "call"
    )
    if slope_high < 0:
        return inf

    test_prices = [0.0] + strikes + [high]
    min_pnl = min(payoff(p) for p in test_prices)
    return max(0.0, -min_pnl)


def _vertical_spread_margin(
    legs: list[dict], right: str, net_cashflow: float = 0.0
) -> float:
    """Return margin for a short vertical spread.

    ``right`` specifies the option type (``"put"`` or ``"call"``). The
    function expects exactly two legs: one short and one long with the
    specified right. The strikes must be ordered such that the spread
    width is positive, otherwise a :class:`ValueError` is raised.
    """
    if len(legs) != 2:
        raise ValueError("Spread requires two legs")
    shorts = [l for l in legs if _option_direction(l) < 0]
    longs = [l for l in legs if _option_direction(l) > 0]
    if len(shorts) != 1 or len(longs) != 1:
        raise ValueError(f"Invalid short_{right}_spread structure")
    if any(get_leg_right(l) != right for l in legs):
        raise ValueError(f"Invalid short_{right}_spread structure")

    short_strike = float(shorts[0].get("strike"))
    long_strike = float(longs[0].get("strike"))
    width = short_strike - long_strike if right == "put" else long_strike - short_strike
    if width <= 0:
        raise ValueError(f"Invalid short_{right}_spread structure")
    return max(width * 100 - net_cashflow * 100, 0.0)


def calculate_margin(
    strategy: str,
    legs: list[dict],
    net_cashflow: float = 0.0,
) -> float:
    """Return approximate initial margin for a multi-leg strategy."""

    strat = strategy.lower()

    if strat == "short_put_spread":
        return _vertical_spread_margin(legs, "put", net_cashflow)

    if strat == "short_call_spread":
        return _vertical_spread_margin(legs, "call", net_cashflow)

    if strat == "naked_put":
        if len(legs) != 1:
            raise ValueError("naked_put requires one leg")
        short = legs[0]
        strike = float(short.get("strike"))
        return max(strike * 100 - net_cashflow * 100, 0.0)

    if strat in {"iron_condor", "atm_iron_butterfly"}:
        if len(legs) != 4:
            raise ValueError("iron_condor/atm_iron_butterfly requires four legs")
        puts = [
            float(l.get("strike"))
            for l in legs
            if get_leg_right(l) == "put"
        ]
        calls = [
            float(l.get("strike"))
            for l in legs
            if get_leg_right(l) == "call"
        ]
        if len(puts) != 2 or len(calls) != 2:
            raise ValueError("Invalid iron_condor/atm_iron_butterfly structure")
        width_put = abs(puts[0] - puts[1])
        width_call = abs(calls[0] - calls[1])
        width = max(width_put, width_call)
        if width <= 0:
            logger.warning("iron_condor wing width is non-positive")
            return None
        return max(width * 100 - net_cashflow * 100, 0.0)

    if strat in {"calendar"}:
        if len(legs) != 2:
            raise ValueError("calendar requires two legs")
        return abs(net_cashflow) * 100

    if strat in {"ratio_spread", "backspread_put"}:
        loss = _max_loss(legs, net_cashflow=net_cashflow)
        if loss is inf:
            raise ValueError("Ratio spread has unlimited risk")
        return loss

    raise ValueError(f"Unsupported strategy: {strategy}")


__all__ = [
    "calculate_edge",
    "calculate_rom",
    "calculate_pos",
    "calculate_ev",
    "calculate_credit",
    "get_signed_position",
    "iter_leg_views",
    "MidPriceResolver",
    "calculate_payoff_at_spot",
    "estimate_scenario_profit",
    "calculate_margin",
]
