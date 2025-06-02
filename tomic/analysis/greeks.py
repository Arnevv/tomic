"""Utility functions for option Greeks aggregation."""

from typing import Any, Dict, Iterable


def compute_portfolio_greeks(positions: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Return portfolio-level Greeks by summing legs."""
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for pos in positions:
        mult = float(pos.get("multiplier") or 1)
        qty = pos.get("position", 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is None:
                continue
            if greek == "delta":
                totals["Delta"] += val * qty
            else:
                totals[greek.capitalize()] += val * qty * mult
    return totals
