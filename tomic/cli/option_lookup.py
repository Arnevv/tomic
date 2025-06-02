"""Interactively fetch option metrics for a symbol."""

from __future__ import annotations

from tomic.logging import setup_logging
from tomic.api.open_interest import fetch_open_interest


def run() -> None:
    """Prompt user for parameters and display open interest."""
    setup_logging()
    symbol = input("Ticker symbool: ").strip().upper()
    if not symbol:
        print("Geen symbool opgegeven")
        return

    expiry = input("Expiry (YYYY-MM-DD): ").strip()
    strike_str = input("Strike: ").strip()
    try:
        strike = float(strike_str)
    except ValueError:
        print("Ongeldige strike")
        return

    right = input("Type (C/P): ").strip().upper()
    if right not in ("C", "P"):
        print("Ongeldig type")
        return

    open_interest = fetch_open_interest(symbol, expiry, strike, right)
    if open_interest is None:
        print("❌ Ophalen mislukt")
        return

    print(f"Open interest voor {symbol} {expiry} {strike}{right}: {open_interest}")


if __name__ == "__main__":
    run()
