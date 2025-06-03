"""Interactively fetch option metrics for a symbol."""

from __future__ import annotations

from datetime import date

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
    try:
        date.fromisoformat(expiry)
    except ValueError:
        print("❌ Ongeldige datum. Gebruik het formaat YYYY-MM-DD.")
        return
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


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for fetching option open interest."""
    if argv:
        if len(argv) != 4:
            print("Usage: option_lookup SYMBOL EXPIRY STRIKE TYPE")
            return
        symbol, expiry, strike_str, right = argv
        try:
            strike = float(strike_str)
        except ValueError:
            print("Ongeldige strike")
            return
        setup_logging()
        try:
            date.fromisoformat(expiry)
        except ValueError:
            print("❌ Ongeldige datum. Gebruik het formaat YYYY-MM-DD.")
            return
        if right.upper() not in ("C", "P"):
            print("Ongeldig type")
            return
        open_interest = fetch_open_interest(
            symbol.upper(), expiry, strike, right.upper()
        )
        if open_interest is None:
            print("❌ Ophalen mislukt")
            return
        print(
            f"Open interest voor {symbol.upper()} {expiry} {strike}{right.upper()}: {open_interest}"
        )
    else:
        run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
