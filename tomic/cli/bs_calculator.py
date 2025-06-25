"""Compute theoretical option values with the Black-Scholes model."""
from __future__ import annotations

import math
from typing import List

from .common import prompt, prompt_float


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
        intrinsic = max(spot_price - strike_price, 0.0) if option_type.upper() == "C" else max(strike_price - spot_price, 0.0)
        return intrinsic
    d1 = (
        math.log(spot_price / strike_price)
        + (r - q + 0.5 * iv * iv) * T
    ) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    if option_type.upper() == "C":
        return spot_price * math.exp(-q * T) * _norm_cdf(d1) - strike_price * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return strike_price * math.exp(-r * T) * _norm_cdf(-d2) - spot_price * math.exp(-q * T) * _norm_cdf(-d1)


def _print_result(option_type: str, spot: float, strike: float, dte: int, iv: float, r: float, q: float) -> None:
    value = black_scholes(option_type, spot, strike, dte, iv, r, q)
    intrinsic = max(spot - strike, 0.0) if option_type.upper() == "C" else max(strike - spot, 0.0)
    time_val = value - intrinsic
    print("\n⚙️  TOMIC Theoretical Value Calculator")
    print(f"Option type: {'Call' if option_type.upper() == 'C' else 'Put'}")
    print(f"Theoretical value: ${value:.2f}")
    print(f"Intrinsic value: ${intrinsic:.2f}")
    print(f"Time value: ${time_val:+.2f}")
    if time_val < 0:
        print("⚠️  Optie lijkt ondergewaardeerd t.o.v. intrinsic value")


def run() -> None:
    """Interactively ask for parameters and print the option value."""
    opt_type = prompt("Option type (C/P): ").upper()
    if opt_type not in {"C", "P"}:
        print("❌ Ongeldig type")
        return
    spot = prompt_float("Spot price: ")
    strike = prompt_float("Strike price: ")
    dte = prompt_float("Days to expiry: ")
    iv = prompt_float("Implied volatility (0-1): ")
    r = prompt_float("Risk free rate [0.045]: ", 0.045)
    q = prompt_float("Dividend yield [0.0]: ", 0.0)
    if None in (spot, strike, dte, iv):
        print("❌ Vereiste waarde ontbreekt")
        return
    _print_result(opt_type, spot, strike, int(dte), iv, r or 0.0, q or 0.0)


def main(argv: List[str] | None = None) -> None:
    """CLI entry point for the calculator."""
    if argv:
        if len(argv) < 5:
            print("Usage: bs_calculator TYPE SPOT STRIKE DTE IV [R] [Q]")
            return
        opt_type = argv[0].upper()
        try:
            spot = float(argv[1])
            strike = float(argv[2])
            dte = int(argv[3])
            iv = float(argv[4])
            r = float(argv[5]) if len(argv) >= 6 else 0.045
            q = float(argv[6]) if len(argv) >= 7 else 0.0
        except ValueError:
            print("❌ Ongeldige numerieke waarde")
            return
        _print_result(opt_type, spot, strike, dte, iv, r, q)
    else:
        run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
