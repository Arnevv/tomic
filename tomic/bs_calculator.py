"""Black-Scholes pricing utilities."""
from __future__ import annotations

import math
from dataclasses import dataclass


def _norm_cdf(x: float) -> float:
    """Return the standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Return the standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


@dataclass
class OptionGreeks:
    """Greeks for a single option leg."""
    price: float
    delta: float      # Change in price per $1 spot move
    gamma: float      # Change in delta per $1 spot move
    vega: float       # Change in price per 1% IV move (per contract = vega / 100)
    theta: float      # Change in price per day to expiration


def black_scholes(
    option_type: str,
    spot_price: float,
    strike_price: float,
    dte: int,
    iv: float,
    r: float = 0.045,
    q: float = 0.0,
) -> float:
    """Return Black-Scholes price for a European option."""
    T = dte / 365.0
    if T <= 0 or iv <= 0:
        intrinsic = (
            max(spot_price - strike_price, 0.0)
            if option_type.upper() == "C"
            else max(strike_price - spot_price, 0.0)
        )
        return intrinsic
    d1 = (
        math.log(spot_price / strike_price)
        + (r - q + 0.5 * iv * iv) * T
    ) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    if option_type.upper() == "C":
        return spot_price * math.exp(-q * T) * _norm_cdf(d1) - strike_price * math.exp(-r * T) * _norm_cdf(d2)
    return strike_price * math.exp(-r * T) * _norm_cdf(-d2) - spot_price * math.exp(-q * T) * _norm_cdf(-d1)


def calculate_greeks(
    option_type: str,
    spot_price: float,
    strike_price: float,
    dte: int,
    iv: float,
    r: float = 0.045,
    q: float = 0.0,
) -> OptionGreeks:
    """Calculate Black-Scholes price and Greeks for an option.

    Args:
        option_type: 'C' for call, 'P' for put
        spot_price: Current spot price
        strike_price: Strike price
        dte: Days to expiration
        iv: Implied volatility (as decimal, e.g., 0.20 for 20%)
        r: Risk-free rate (default 4.5%)
        q: Dividend yield (default 0.0%)

    Returns:
        OptionGreeks with price and all Greeks
    """
    T = dte / 365.0

    # Handle edge cases
    if T <= 0:
        intrinsic = (
            max(spot_price - strike_price, 0.0)
            if option_type.upper() == "C"
            else max(strike_price - spot_price, 0.0)
        )
        return OptionGreeks(price=intrinsic, delta=(1.0 if intrinsic > 0 else 0.0), gamma=0.0, vega=0.0, theta=0.0)

    if iv <= 0:
        intrinsic = (
            max(spot_price - strike_price, 0.0)
            if option_type.upper() == "C"
            else max(strike_price - spot_price, 0.0)
        )
        return OptionGreeks(price=intrinsic, delta=(1.0 if intrinsic > 0 else 0.0), gamma=0.0, vega=0.0, theta=0.0)

    # Calculate d1 and d2
    d1 = (
        math.log(spot_price / strike_price)
        + (r - q + 0.5 * iv * iv) * T
    ) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)

    # Price
    if option_type.upper() == "C":
        price = spot_price * math.exp(-q * T) * _norm_cdf(d1) - strike_price * math.exp(-r * T) * _norm_cdf(d2)
    else:
        price = strike_price * math.exp(-r * T) * _norm_cdf(-d2) - spot_price * math.exp(-q * T) * _norm_cdf(-d1)

    # Delta
    if option_type.upper() == "C":
        delta = math.exp(-q * T) * _norm_cdf(d1)
    else:
        delta = -math.exp(-q * T) * _norm_cdf(-d1)

    # Gamma (same for calls and puts)
    gamma = math.exp(-q * T) * _norm_pdf(d1) / (spot_price * iv * math.sqrt(T))

    # Vega (per 1% IV change, not per 0.01 IV change)
    vega = spot_price * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T) / 100.0

    # Theta (per day)
    if option_type.upper() == "C":
        theta = (
            -spot_price * math.exp(-q * T) * _norm_pdf(d1) * iv / (2 * math.sqrt(T))
            + q * spot_price * math.exp(-q * T) * _norm_cdf(d1)
            - r * strike_price * math.exp(-r * T) * _norm_cdf(d2)
        ) / 365.0
    else:
        theta = (
            -spot_price * math.exp(-q * T) * _norm_pdf(d1) * iv / (2 * math.sqrt(T))
            - q * spot_price * math.exp(-q * T) * _norm_cdf(-d1)
            + r * strike_price * math.exp(-r * T) * _norm_cdf(-d2)
        ) / 365.0

    return OptionGreeks(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta)

