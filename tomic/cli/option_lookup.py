"""Interactively fetch option metrics for a symbol."""

from __future__ import annotations

from tomic.logging import setup_logging
from tomic.api.option_metrics import fetch_option_metrics


def run() -> None:
    """Prompt user for parameters and display selected metrics."""
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
    if right not in {"C", "P"}:
        print("Ongeldig type")
        return

    data = fetch_option_metrics(symbol, expiry, strike, right)
    if not data:
        print("❌ Ophalen mislukt")
        return

    while True:
        print("\n1. Spotprice")
        print("2. Volume")
        print("3. Open interest")
        print("4. Terug")
        choice = input("Maak je keuze: ").strip()
        if choice == "1":
            print(f"Spotprice: {data['spot_price']}")
        elif choice == "2":
            print(f"Volume: {data['volume']}")
        elif choice == "3":
            print(f"Open interest: {data['open_interest']}")
        elif choice == "4":
            break
        else:
            print("❌ Ongeldige keuze")


if __name__ == "__main__":
    run()
