"""Compute theoretical option values with the Black-Scholes model."""
from __future__ import annotations

from typing import List

from ..bs_calculator import black_scholes
from .common import prompt, prompt_float


def _print_result(
    option_type: str,
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    r: float,
    q: float,
    midprice: float | None = None,
) -> None:
    value = black_scholes(option_type, spot, strike, dte, iv, r, q)
    intrinsic = max(spot - strike, 0.0) if option_type.upper() == "C" else max(strike - spot, 0.0)
    time_val = value - intrinsic
    print("\n⚙️  TOMIC Theoretical Value Calculator")
    print(f"Option type: {'Call' if option_type.upper() == 'C' else 'Put'}")
    print(f"Theoretical value: ${value:.2f}")
    print(f"Intrinsic value: ${intrinsic:.2f}")
    print(f"Time value: ${time_val:+.2f}")
    if midprice is not None:
        edge = value - midprice
        print(f"Edge op basis van {midprice}: ${edge:.2f}")
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
    mid = prompt_float("Midprice (optioneel): ")
    if None in (spot, strike, dte, iv):
        print("❌ Vereiste waarde ontbreekt")
        return
    _print_result(opt_type, spot, strike, int(dte), iv, r or 0.0, q or 0.0, mid)


def main(argv: List[str] | None = None) -> None:
    """CLI entry point for the calculator."""
    if argv:
        if len(argv) < 5:
            print("Usage: bs_calculator TYPE SPOT STRIKE DTE IV [R] [Q] [MID]")
            return
        opt_type = argv[0].upper()
        try:
            spot = float(argv[1])
            strike = float(argv[2])
            dte = int(argv[3])
            iv = float(argv[4])
            r = float(argv[5]) if len(argv) >= 6 else 0.045
            q = float(argv[6]) if len(argv) >= 7 else 0.0
            mid = float(argv[7]) if len(argv) >= 8 else None
        except ValueError:
            print("❌ Ongeldige numerieke waarde")
            return
        _print_result(opt_type, spot, strike, dte, iv, r, q, mid)
    else:
        run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
