"""Generate strategy proposals based on portfolio Greeks and option chain CSVs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tomic.analysis.greeks import compute_greeks_by_symbol
from tomic.journal.utils import load_json


@dataclass
class Leg:
    expiry: str
    type: str
    strike: float
    delta: float
    gamma: float
    vega: float
    theta: float
    position: int = 0


def _parse_float(value: str | None) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_chain_csv(path: str) -> List[Leg]:
    """Parse option chain CSV into a list of ``Leg`` records."""
    legs: List[Leg] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                legs.append(
                    Leg(
                        expiry=row.get("Expiry", ""),
                        type=row.get("Type", ""),
                        strike=float(row.get("Strike", 0) or 0),
                        delta=_parse_float(row.get("Delta")) or 0.0,
                        gamma=_parse_float(row.get("Gamma")) or 0.0,
                        vega=_parse_float(row.get("Vega")) or 0.0,
                        theta=_parse_float(row.get("Theta")) or 0.0,
                    )
                )
            except Exception:
                continue
    return legs


def _sum_greeks(legs: Iterable[Leg]) -> Dict[str, float]:
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for leg in legs:
        mult = leg.position or 0
        totals["Delta"] += leg.delta * mult
        totals["Gamma"] += leg.gamma * mult
        totals["Vega"] += leg.vega * mult
        totals["Theta"] += leg.theta * mult
    return totals


def _find_chain_file(directory: Path, symbol: str) -> Optional[Path]:
    pattern = f"option_chain_{symbol}_"
    candidates = sorted(directory.glob(f"*{pattern}*.csv"))
    return candidates[-1] if candidates else None


def _make_vertical(chain: List[Leg], bullish: bool) -> Optional[List[Leg]]:
    calls = [c for c in chain if c.type == "C"]
    puts = [p for p in chain if p.type == "P"]
    if bullish:
        group = calls
    else:
        group = puts
    if len(group) < 2:
        return None
    group.sort(key=lambda x: x.strike)
    short = group[0]
    long = group[1]
    return [
        Leg(**{**short.__dict__, "position": -1}),
        Leg(**{**long.__dict__, "position": 1}),
    ]


def _make_condor(chain: List[Leg]) -> Optional[List[Leg]]:
    calls = [c for c in chain if c.type == "C"]
    puts = [p for p in chain if p.type == "P"]
    if len(calls) < 2 or len(puts) < 2:
        return None
    calls.sort(key=lambda x: x.strike)
    puts.sort(key=lambda x: x.strike)
    legs = [
        Leg(**{**calls[0].__dict__, "position": -1}),
        Leg(**{**calls[1].__dict__, "position": 1}),
        Leg(**{**puts[-1].__dict__, "position": -1}),
        Leg(**{**puts[-2].__dict__, "position": 1}),
    ]
    return legs


def _make_calendar(chain: List[Leg]) -> Optional[List[Leg]]:
    if len(chain) < 2:
        return None
    chain.sort(key=lambda x: (x.strike, x.expiry))
    first = chain[0]
    other = next((l for l in chain[1:] if l.strike == first.strike and l.expiry != first.expiry), None)
    if other is None:
        return None
    return [
        Leg(**{**first.__dict__, "position": -1}),
        Leg(**{**other.__dict__, "position": 1}),
    ]


def _tomic_score(after: Dict[str, float]) -> float:
    score = 100.0
    score -= abs(after.get("Delta", 0.0)) * 0.5
    score -= abs(after.get("Vega", 0.0)) * 0.2
    if after.get("Theta", 0.0) < 0:
        score += after["Theta"] * 1.0
    score -= abs(after.get("Gamma", 0.0)) * 0.1
    return round(max(score, 0.0), 1)


def suggest_strategies(symbol: str, chain: List[Leg], exposure: Dict[str, float]) -> List[Dict[str, Any]]:
    """Return a list of strategy proposals for ``symbol``."""
    suggestions: List[Dict[str, Any]] = []
    if abs(exposure.get("Delta", 0.0)) > 25:
        bullish = exposure["Delta"] < 0
        legs = _make_vertical(chain, bullish)
        if legs:
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            suggestions.append(
                {
                    "strategy": "Vertical",
                    "legs": [leg.__dict__ for leg in legs],
                    "impact": impact,
                    "score": _tomic_score(after),
                    "reason": "Delta-balancering",
                }
            )
    if exposure.get("Vega", 0.0) > 50:
        legs = _make_condor(chain)
        if legs:
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            suggestions.append(
                {
                    "strategy": "Iron Condor",
                    "legs": [leg.__dict__ for leg in legs],
                    "impact": impact,
                    "score": _tomic_score(after),
                    "reason": "Vega verlagen",
                }
            )
    if exposure.get("Vega", 0.0) < -50:
        legs = _make_calendar(chain)
        if legs:
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            suggestions.append(
                {
                    "strategy": "Calendar Spread",
                    "legs": [leg.__dict__ for leg in legs],
                    "impact": impact,
                    "score": _tomic_score(after),
                    "reason": "Vega verhogen",
                }
            )
    return suggestions


def generate_proposals(positions_file: str, chain_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """Combine portfolio Greeks with chain data and return proposals."""
    positions = load_json(positions_file)
    open_positions = [p for p in positions if p.get("position")]
    exposures = compute_greeks_by_symbol(open_positions)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for sym, greeks in exposures.items():
        if sym == "TOTAL":
            continue
        dir_path = Path(chain_dir)
        chain_path = _find_chain_file(dir_path, sym)
        if not chain_path:
            continue
        chain = load_chain_csv(str(chain_path))
        props = suggest_strategies(sym, chain, greeks)
        if props:
            result[sym] = props
    return result


__all__ = [
    "load_chain_csv",
    "suggest_strategies",
    "generate_proposals",
]
