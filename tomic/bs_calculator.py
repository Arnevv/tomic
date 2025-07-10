"""Black-Scholes pricing utilities."""
from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    """Return the standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


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

