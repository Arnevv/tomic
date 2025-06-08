"""Utility functions for option Greeks aggregation."""

from typing import Any, Dict, Iterable


def compute_portfolio_greeks(positions: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Return portfolio-level Greeks by summing legs."""
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for pos in positions:
        mult = float(pos.get("multiplier") or 1)
        qty = float(pos.get("position", 0) or 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is None:
                continue
            val_f = float(val)
            if greek == "delta":
                totals["Delta"] += val_f * qty
            else:
                totals[greek.capitalize()] += val_f * qty * mult
    return totals


def compute_greeks_by_symbol(
    positions: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Return aggregated Greeks per symbol including overall totals."""
    by_symbol: Dict[str, Dict[str, float]] = {}
    for pos in positions:
        sym = pos.get("symbol")
        if not sym:
            continue
        data = by_symbol.setdefault(
            sym, {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
        )
        mult = float(pos.get("multiplier") or 1)
        qty = float(pos.get("position", 0) or 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is None:
                continue
            val_f = float(val)
            key = "Delta" if greek == "delta" else greek.capitalize()
            if greek == "delta":
                data[key] += val_f * qty
            else:
                data[key] += val_f * qty * mult
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for vals in by_symbol.values():
        for g in totals:
            totals[g] += vals[g]
    by_symbol["TOTAL"] = totals
    return by_symbol
