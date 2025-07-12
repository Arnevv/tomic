from __future__ import annotations


"""Utility functions for option metrics calculations."""

from math import inf
from typing import Optional, Iterable

from .utils import normalize_right
from .logutils import logger


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


def _max_loss(
    legs: Iterable[dict], *, net_cashflow: float = 0.0
) -> float:
    """Return worst-case loss for ``legs`` with given net cashflow."""

    strikes = sorted(float(leg.get("strike", 0)) for leg in legs)
    if not strikes:
        raise ValueError("Missing strike information")
    high = strikes[-1] * 10

    def payoff(price: float) -> float:
        total = net_cashflow * 100
        for leg in legs:
            qty = abs(
                float(leg.get("qty") or leg.get("quantity") or leg.get("position") or 1)
            )
            direction = _option_direction(leg)
            right = normalize_right(leg.get("type") or leg.get("right"))
            strike = float(leg.get("strike"))
            if right == "call":
                total += direction * qty * max(price - strike, 0) * 100
            else:
                total += direction * qty * max(strike - price, 0) * 100
        return total

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

    if strat in {"bull put spread", "bear call spread", "vertical spread"}:
        if len(legs) != 2:
            raise ValueError("Spread requires two legs")
        strikes = [float(legs[0].get("strike")), float(legs[1].get("strike"))]
        width = abs(strikes[0] - strikes[1])
        return max(width * 100 - net_cashflow * 100, 0.0)

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
    "calculate_margin",
]
