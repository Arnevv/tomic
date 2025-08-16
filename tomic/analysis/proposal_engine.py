"""Generate strategy proposals based on portfolio Greeks and option chain CSVs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tomic.analysis.greeks import compute_greeks_by_symbol
from tomic.analysis.strategy import heuristic_risk_metrics
from tomic.journal.utils import load_json
from tomic.utils import get_option_mid_price, normalize_right
from tomic.helpers.csv_utils import parse_euro_float
from tomic.metrics import calculate_margin, estimate_scenario_profit
from tomic.logutils import logger
from ..criteria import RULES
from ..config import _load_yaml
from ..loader import load_strike_config

_BASE = Path(__file__).resolve().parent.parent
_STRIKE_RULES = (
    _load_yaml(_BASE / "strike_selection_rules.yaml")
    if (_BASE / "strike_selection_rules.yaml").exists()
    else {}
)


@dataclass
class Leg:
    expiry: str
    type: str
    strike: float
    delta: float
    gamma: float
    vega: float
    theta: float
    bid: float = 0.0
    ask: float = 0.0
    position: int = 0


def _parse_float(value: str | None) -> Optional[float]:
    return parse_euro_float(value)


def load_chain_csv(path: str) -> List[Leg]:
    """Parse option chain CSV into a list of ``Leg`` records."""
    legs: List[Leg] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                option_type = normalize_right(row.get("Type", ""))
                legs.append(
                    Leg(
                        expiry=row.get("Expiry", ""),
                        type=option_type,
                        strike=float(row.get("Strike", 0) or 0),
                        delta=_parse_float(row.get("Delta")) or 0.0,
                        gamma=_parse_float(row.get("Gamma")) or 0.0,
                        vega=_parse_float(row.get("Vega")) or 0.0,
                        theta=_parse_float(row.get("Theta")) or 0.0,
                        bid=_parse_float(row.get("Bid")) or 0.0,
                        ask=_parse_float(row.get("Ask")) or 0.0,
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


def _dte(expiry: str) -> Optional[int]:
    """Return days to expiry for ``expiry`` in YYYYMMDD format."""
    try:
        exp = datetime.strptime(expiry, "%Y%m%d").date()
    except Exception:
        return None
    return (exp - datetime.now(timezone.utc).date()).days


def _mid_price(leg: Leg) -> float:
    return get_option_mid_price({"bid": leg.bid, "ask": leg.ask, "close": None}) or 0.0


def _cost_basis(legs: Iterable[Leg]) -> float:
    cost = 0.0
    for leg in legs:
        price = _mid_price(leg)
        cost += price if leg.position > 0 else -price
    return cost * 100


def _calc_metrics(strategy: str, legs: List[Leg], spot_price: float) -> Dict[str, Any]:
    """Return margin and risk metrics for ``strategy`` with ``legs``."""

    cb = _cost_basis(legs)
    legs_dict = [
        {
            "strike": leg.strike,
            "type": leg.type,
            "position": leg.position,
            "mid": _mid_price(leg),
        }
        for leg in legs
    ]

    credit = -cb if cb < 0 else 0.0
    debit = cb if cb > 0 else 0.0
    net_cashflow = credit / 100 if credit else -debit / 100
    try:
        margin = calculate_margin(
            strategy,
            legs_dict,
            net_cashflow=net_cashflow,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(f"calculate_margin failed for {strategy}: {exc}")
        margin = 350.0

    risk = heuristic_risk_metrics(legs_dict, cb)
    max_profit = risk.get("max_profit")
    max_loss = risk.get("max_loss")
    rr = risk.get("risk_reward")
    profit_estimated = False
    scenario_info: Optional[Dict[str, Any]] = None

    if max_profit is None or max_profit <= 0:
        scenarios, err = estimate_scenario_profit(legs_dict, spot_price, strategy)
        if scenarios:
            preferred = next(
                (s for s in scenarios if s.get("preferred_move")), scenarios[0]
            )
            pnl = preferred.get("pnl")
            max_profit = abs(pnl) if pnl is not None else None
            scenario_info = preferred
            profit_estimated = True
            label = preferred.get("scenario_label")
            logger.info(
                f"[SCENARIO] {strategy}: profit estimate at {label} {max_profit}"
            )
        else:
            scenario_info = {"error": err or "no scenario defined"}

    rom = None
    if max_profit is not None and margin:
        rom = (max_profit / margin) * 100

    return {
        "ROM": rom,
        "RR": rr,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "margin": margin,
        "profit_estimated": profit_estimated,
        "scenario_info": scenario_info,
    }


def _filter_chain_by_dte(chain: List[Leg], strategy: str) -> List[Leg]:
    """Return ``chain`` filtered to the strategy's DTE range."""

    try:
        rules = load_strike_config(strategy, _STRIKE_RULES)
    except Exception:
        rules = {}
    dte_range = rules.get("dte_range")
    if not dte_range:
        return chain
    min_dte, max_dte = dte_range
    filtered = [
        leg
        for leg in chain
        if (d := _dte(leg.expiry)) is not None and min_dte <= d <= max_dte
    ]
    return filtered or chain


def _make_vertical(chain: List[Leg], bullish: bool) -> Optional[List[Leg]]:
    calls = [c for c in chain if c.type == "call"]
    puts = [p for p in chain if p.type == "put"]
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
    calls = [c for c in chain if c.type == "call"]
    puts = [p for p in chain if p.type == "put"]
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
    other = next(
        (
            leg
            for leg in chain[1:]
            if leg.strike == first.strike and leg.expiry != first.expiry
        ),
        None,
    )
    if other is None:
        return None
    legs = [
        Leg(**{**first.__dict__, "position": -1}),
        Leg(**{**other.__dict__, "position": 1}),
    ]
    return legs


def _tomic_score(after: Dict[str, float]) -> float:
    score = 100.0
    score -= abs(after.get("Delta", 0.0)) * 0.5
    score -= abs(after.get("Vega", 0.0)) * 0.2
    if after.get("Theta", 0.0) < 0:
        score += after["Theta"] * 1.0
    score -= abs(after.get("Gamma", 0.0)) * 0.1
    return round(max(score, 0.0), 1)


def suggest_strategies(
    symbol: str,
    chain: List[Leg],
    exposure: Dict[str, float],
    *,
    spot_price: float,
    metrics: Optional[Any] = None,
    vix: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Return a list of strategy proposals for ``symbol``."""
    suggestions: List[Dict[str, Any]] = []
    iv_rank = getattr(metrics, "iv_rank", None) if metrics else None
    iv_pct = getattr(metrics, "iv_percentile", None) if metrics else None
    term_m1_m3 = getattr(metrics, "term_m1_m3", None)

    port = RULES.portfolio
    condor_gate = port.condor_gates
    calendar_gate = port.calendar_gates

    if abs(exposure.get("Delta", 0.0)) > 25:
        bullish = exposure["Delta"] < 0
        legs = _make_vertical(chain, bullish)
        if legs:
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            risk = _calc_metrics("vertical spread", legs, spot_price)
            suggestions.append(
                {
                    "strategy": "Vertical",
                    "legs": [leg.__dict__ for leg in legs],
                    "impact": impact,
                    "score": _tomic_score(after),
                    "reason": "Delta-balancering",
                    "ROM": risk.get("ROM"),
                    "RR": risk.get("RR"),
                    "margin": risk.get("margin"),
                    "max_profit": risk.get("max_profit"),
                    "max_loss": risk.get("max_loss"),
                    "profit_estimated": risk.get("profit_estimated"),
                    "scenario_info": risk.get("scenario_info"),
                }
            )
    if exposure.get("Vega", 0.0) > port.vega_to_condor:
        legs = _make_condor(_filter_chain_by_dte(chain, "iron_condor"))
        if legs and not (
            (condor_gate.iv_rank_min is not None and iv_rank is not None and iv_rank < condor_gate.iv_rank_min)
            or (condor_gate.iv_percentile_min is not None and iv_pct is not None and iv_pct < condor_gate.iv_percentile_min)
            or (condor_gate.vix_max is not None and vix is not None and vix > condor_gate.vix_max)
        ):
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            risk = _calc_metrics("iron_condor", legs, spot_price)
            rom = risk.get("ROM")
            rr = risk.get("RR")
            if metrics or vix is not None:
                if rom is not None and rom < 10:
                    risk_ok = False
                elif rr is not None and rr < 1.0:
                    risk_ok = False
                else:
                    risk_ok = True
            else:
                risk_ok = True
            if risk_ok:
                suggestions.append(
                    {
                        "strategy": "iron_condor",
                        "legs": [leg.__dict__ for leg in legs],
                        "impact": impact,
                        "score": _tomic_score(after),
                        "reason": "Vega verlagen",
                        "ROM": rom,
                        "RR": rr,
                        "margin": risk.get("margin"),
                        "max_profit": risk.get("max_profit"),
                        "max_loss": risk.get("max_loss"),
                        "profit_estimated": risk.get("profit_estimated"),
                        "scenario_info": risk.get("scenario_info"),
                    }
                )
    if exposure.get("Vega", 0.0) < port.vega_to_calendar:
        legs = _make_calendar(_filter_chain_by_dte(chain, "calendar"))
        if legs and not (
            (calendar_gate.iv_rank_max is not None and iv_rank is not None and iv_rank > calendar_gate.iv_rank_max)
            or (calendar_gate.iv_percentile_max is not None and iv_pct is not None and iv_pct > calendar_gate.iv_percentile_max)
            or (calendar_gate.term_m1_m3_min is not None and term_m1_m3 is not None and term_m1_m3 <= calendar_gate.term_m1_m3_min)
            or (calendar_gate.vix_min is not None and vix is not None and vix < calendar_gate.vix_min)
        ):
            impact = _sum_greeks(legs)
            after = {k: exposure.get(k, 0.0) + impact[k] for k in impact}
            risk = _calc_metrics("calendar", legs, spot_price)
            rom = risk.get("ROM")
            if metrics or vix is not None:
                risk_ok = rom is None or rom >= 10
            else:
                risk_ok = True
            if risk_ok:
                suggestions.append(
                    {
                        "strategy": "calendar",
                        "legs": [leg.__dict__ for leg in legs],
                        "impact": impact,
                        "score": _tomic_score(after),
                        "reason": "Vega verhogen",
                        "ROM": rom,
                        "RR": risk.get("RR"),
                        "margin": risk.get("margin"),
                        "max_profit": risk.get("max_profit"),
                        "max_loss": risk.get("max_loss"),
                        "profit_estimated": risk.get("profit_estimated"),
                        "scenario_info": risk.get("scenario_info"),
                    }
                )
    return suggestions


def generate_proposals(
    positions_file: str,
    chain_dir: str,
    *,
    metrics: Optional[Dict[str, Any]] = None,
    vix: Optional[float] = None,
) -> Dict[str, List[Dict[str, Any]]]:
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
        m = metrics.get(sym) if metrics else None
        spot = None
        if m is not None:
            spot = getattr(m, "spot_price", None)
            if spot is None and isinstance(m, dict):
                spot = m.get("spot_price")
        props = suggest_strategies(
            sym,
            chain,
            greeks,
            spot_price=spot if spot is not None else 0.0,
            metrics=m,
            vix=vix,
        )
        if props:
            result[sym] = props
    return result


__all__ = [
    "load_chain_csv",
    "suggest_strategies",
    "generate_proposals",
]
