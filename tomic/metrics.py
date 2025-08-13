from __future__ import annotations


"""Utility functions for option metrics calculations."""

from math import inf
from typing import Optional, Iterable, Any, Dict, List

from .utils import normalize_right
from .logutils import logger
from .config import get as cfg_get


def calculate_edge(theoretical: float, mid_price: float) -> float:
    """Return theoretical minus mid price."""
    return theoretical - mid_price


def calculate_rom(max_profit: float, margin: float) -> Optional[float]:
    """Return return on margin as percentage or ``None`` if margin is zero."""
    if not margin:
        return None
    return (max_profit / margin) * 100


def calculate_credit(legs: Iterable[dict]) -> float:
    """Return net credit in dollars for ``legs``."""

    credit = 0.0
    for leg in legs:
        try:
            price = float(leg.get("mid", 0) or 0)
        except Exception:
            continue
        qty = abs(
            float(
                leg.get("qty")
                or leg.get("quantity")
                or leg.get("position")
                or 1
            )
        )
        direction = 1 if leg.get("position", 0) > 0 else -1
        credit -= direction * price * qty
    return credit * 100


def calculate_pos(delta: float) -> float:
    """Approximate probability of success from delta (0-1 range)."""
    return (1 - abs(delta)) * 100


def calculate_ev(pos: float, max_profit: float, max_loss: float) -> float:
    """Return expected value given probability of success and payoff values."""
    prob = pos / 100
    return prob * max_profit + (1 - prob) * max_loss


def _option_direction(leg: dict) -> int:
    """Return +1 for long legs and -1 for short legs."""
    action = str(leg.get("action", "")).upper()
    if action in {"BUY", "LONG"}:
        return 1
    if action in {"SELL", "SHORT"}:
        return -1
    pos = leg.get("position")
    if pos is not None:
        return 1 if pos > 0 else -1
    return 1


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
            qty = abs(
                float(
                    leg.get("qty")
                    or leg.get("quantity")
                    or leg.get("position")
                    or 1
                )
            )
            net_cashflow += price * _option_direction(leg) * qty

    total = -net_cashflow * 100
    for leg in legs:
        qty = abs(
            float(
                leg.get("qty")
                or leg.get("quantity")
                or leg.get("position")
                or 1
            )
        )
        position = _option_direction(leg) * qty
        right = normalize_right(leg.get("type") or leg.get("right"))
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
        if normalize_right(leg.get("type") or leg.get("right")) == "call"
    )
    if slope_high < 0:
        return inf

    test_prices = [0.0] + strikes + [high]
    min_pnl = min(payoff(p) for p in test_prices)
    return max(0.0, -min_pnl)


def calculate_margin(
    strategy: str,
    legs: list[dict],
    net_cashflow: float = 0.0,
) -> float:
    """Return approximate initial margin for a multi-leg strategy."""

    strat = strategy.lower()

    if strat == "bull put spread":
        if len(legs) != 2:
            raise ValueError("Spread requires two legs")
        shorts = [l for l in legs if _option_direction(l) < 0]
        longs = [l for l in legs if _option_direction(l) > 0]
        if not shorts or not longs:
            raise ValueError("Invalid bull put spread structure")
        short_strike = float(shorts[0].get("strike"))
        long_strike = float(longs[0].get("strike"))
        width = short_strike - long_strike
        return max(width * 100 - net_cashflow * 100, 0.0)

    if strat == "short_call_spread":
        if len(legs) != 2:
            raise ValueError("Spread requires two legs")
        shorts = [l for l in legs if _option_direction(l) < 0]
        longs = [l for l in legs if _option_direction(l) > 0]
        if not shorts or not longs:
            raise ValueError("Invalid short_call_spread structure")
        short_strike = float(shorts[0].get("strike"))
        long_strike = float(longs[0].get("strike"))
        width = long_strike - short_strike
        return max(width * 100 - net_cashflow * 100, 0.0)

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
            if normalize_right(l.get("type") or l.get("right")) == "put"
        ]
        calls = [
            float(l.get("strike"))
            for l in legs
            if normalize_right(l.get("type") or l.get("right")) == "call"
        ]
        if len(puts) != 2 or len(calls) != 2:
            raise ValueError("Invalid iron_condor/atm_iron_butterfly structure")
        width_put = abs(puts[0] - puts[1])
        width_call = abs(calls[0] - calls[1])
        width = max(width_put, width_call)
        if width <= 0:
            logger.warning("iron_condor wing width is non-positive")
            return None
        return width * 100

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
    "calculate_payoff_at_spot",
    "estimate_scenario_profit",
    "calculate_margin",
]
