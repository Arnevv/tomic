"""CLI helper for manually entering the VIX value."""

from __future__ import annotations

from typing import Optional


def prompt_manual_vix() -> Optional[float]:
    """Prompt the user for a VIX value and return it as a float."""

    print("VIX niet beschikbaar. Open snel: https://www.barchart.com/stocks/quotes/$VIX/overview")
    raw = input("Handmatige VIX (bijv. 18.42, enter voor overslaan): ").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print("Ongeldige waarde, invoer genegeerd.")
        return None


__all__ = ["prompt_manual_vix"]
