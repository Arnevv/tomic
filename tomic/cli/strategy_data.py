# Strategy descriptions and alert profiles for strategy_dashboard

from __future__ import annotations

from typing import Callable, Dict, Optional

# Description functions keyed by strategy type
STRATEGY_DESCRIPTION_MAP: Dict[str, Callable[[Optional[float]], str]] = {
    "iron_condor": lambda _: "Inzet op range bij hoge IV, gericht op premie-inname en daling van IV",
    "calendar": lambda _: "Inzet op zijwaartse markt met lage IV, gericht op stijging in IV of term structure voordeel",
    "Put calendar": lambda _: "Inzet op lichte daling bij lage IV, speelt in op stijging IV of termijnstructuur",
    "Call calendar": lambda _: "Inzet op lichte stijging bij lage IV, speelt in op stijging IV of termijnstructuur",
    "Ratio Put Backspread": lambda _: "Inzet op forse daling én stijgende IV – asymmetrisch long gamma/vega",
    "Ratio Call Backspread": lambda _: "Inzet op forse stijging én stijgende IV – asymmetrisch long gamma/vega",
    "Vertical": lambda delta: (
        "Bullish vertical – inzet op stijging" if (delta or 0) > 0 else "Bearish vertical – inzet op daling"
    ),
    "Straddle": lambda _: "Inzet op forse beweging, ongeacht richting – long gamma, long vega",
    "Strangle": lambda _: "Inzet op forse beweging met bredere marges – long gamma, long vega",
    "ATM Iron Butterfly": lambda _: "Inzet op stilstand bij gemiddelde IV – hoge premie dichtbij ATM",
    "Long Call": lambda _: "Speculatie op forse stijging – hoog risico, hoog potentieel",
    "Long Put": lambda _: "Speculatie op forse daling – hoog risico, hoog potentieel",
    "Short Call": lambda _: "Inzet op stabiliteit of daling – premie-inname met beperkt potentieel",
    "Short Put": lambda _: "Inzet op stabiliteit of stijging – premie-inname met beperkt potentieel",
}


def get_strategy_description(strategy_type: str, delta: Optional[float] = None) -> Optional[str]:
    """Return description for ``strategy_type`` if available."""
    func = STRATEGY_DESCRIPTION_MAP.get(strategy_type)
    if func is None:
        return None
    return func(delta)


# Alert filtering per strategy type
ALERT_PROFILE = {
    "iron_condor": ["theta", "vega", "iv", "skew", "rom", "dte"],
    "calendar": ["iv", "term", "vega", "dte"],
    "Put calendar": ["iv", "term", "vega", "dte"],
    "Call calendar": ["iv", "term", "vega", "dte"],
    "Ratio Put Backspread": ["delta", "vega", "iv", "dte"],
    "Ratio Call Backspread": ["delta", "vega", "iv", "dte"],
    "Vertical": ["delta", "pnl", "dte"],
    "Straddle": ["delta", "vega", "iv", "dte"],
    "Strangle": ["delta", "vega", "iv", "dte"],
    "ATM Iron Butterfly": ["theta", "vega", "iv", "dte"],
    "Long Call": ["delta", "pnl", "dte"],
    "Long Put": ["delta", "pnl", "dte"],
    "Short Call": ["delta", "pnl", "dte"],
    "Short Put": ["delta", "pnl", "dte"],
}

__all__ = ["get_strategy_description", "ALERT_PROFILE"]
