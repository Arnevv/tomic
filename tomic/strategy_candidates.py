from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Dict, List, Optional
from datetime import date, datetime
import math
import pandas as pd

from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity

from .metrics import (
    calculate_margin,
    calculate_pos,
    calculate_rom,
    calculate_ev,
    estimate_scenario_profit,
)
from .analysis.strategy import heuristic_risk_metrics, parse_date
from .utils import (
    get_option_mid_price,
    normalize_leg,
    normalize_right,
    prompt_user_for_price,
)
from .logutils import logger, log_combo_evaluation
from .criteria import CriteriaConfig, load_criteria
from .strategies import StrategyName


# Strategies that must yield a positive net credit. Calendar spreads are
# intentionally omitted because they are debit strategies.
STRATEGIES_THAT_REQUIRE_POSITIVE_CREDIT = {
    StrategyName.SHORT_PUT_SPREAD,
    StrategyName.SHORT_CALL_SPREAD,
    StrategyName.IRON_CONDOR,
    StrategyName.ATM_IRON_BUTTERFLY,
    StrategyName.NAKED_PUT,
}


@dataclass
class StrategyProposal:
    """Container for a generated option strategy."""

    legs: List[Dict[str, Any]] = field(default_factory=list)
    pos: Optional[float] = None
    ev: Optional[float] = None
    ev_pct: Optional[float] = None
    rom: Optional[float] = None
    edge: Optional[float] = None
    credit: Optional[float] = None
    margin: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: Optional[List[float]] = None
    score: Optional[float] = None
    fallback: Optional[str] = None
    profit_estimated: bool = False
    scenario_info: Optional[Dict[str, Any]] = None


@dataclass
class StrikeMatch:
    """Result of nearest strike lookup."""

    target: float
    matched: float | None = None
    diff: float | None = None


def select_expiry_pairs(expiries: List[str], min_gap: int) -> List[tuple[str, str]]:
    """Return pairs of expiries separated by at least ``min_gap`` days."""
    parsed = []
    for exp in expiries:
        d = parse_date(str(exp))
        if d:
            parsed.append((exp, d))
    parsed.sort(key=lambda t: t[1])
    pairs: List[tuple[str, str]] = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            if (parsed[j][1] - parsed[i][1]).days >= min_gap:
                pairs.append((parsed[i][0], parsed[j][0]))
    return pairs


def _breakevens(
    strategy: StrategyName | str, legs: List[Dict[str, Any]], credit: float
) -> Optional[List[float]]:
    """Return simple breakeven estimates for supported strategies.

    ``credit`` should be the net credit per contract. Breakevens are offset
    using the per-share value (``credit / 100``).
    """
    if not legs:
        return None
    strategy = getattr(strategy, "value", strategy)
    credit_ps = credit / 100.0
    if strategy in {StrategyName.SHORT_PUT_SPREAD, StrategyName.SHORT_CALL_SPREAD}:
        short = [l for l in legs if l.get("position") < 0][0]
        strike = float(short.get("strike"))
        if strategy == StrategyName.SHORT_PUT_SPREAD:
            return [strike - credit_ps]
        return [strike + credit_ps]
    if strategy in {StrategyName.IRON_CONDOR, StrategyName.ATM_IRON_BUTTERFLY}:
        short_put = [
            l
            for l in legs
            if l.get("position") < 0
            and normalize_right(l.get("type") or l.get("right")) == "put"
        ]
        short_call = [
            l
            for l in legs
            if l.get("position") < 0
            and normalize_right(l.get("type") or l.get("right")) == "call"
        ]
        if short_put and short_call:
            sp = float(short_put[0].get("strike"))
            sc = float(short_call[0].get("strike"))
            return [sp - credit_ps, sc + credit_ps]
    if strategy == "naked_put":
        short = legs[0]
        strike = float(short.get("strike"))
        return [strike - credit_ps]
    if strategy == "calendar":
        return [float(legs[0].get("strike"))]
    return None


def _build_strike_map(chain: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[float]]]:
    """Return mapping of expiries and option types to available strikes."""

    strike_map: Dict[str, Dict[str, set[float]]] = {}
    for opt in chain:
        try:
            expiry = str(opt.get("expiry"))
            right = normalize_right(opt.get("type") or opt.get("right", ""))
            strike = float(opt.get("strike"))
        except Exception:
            continue
        strike_map.setdefault(expiry, {}).setdefault(right, set()).add(strike)

    # convert sets to sorted lists for deterministic behaviour
    return {
        exp: {r: sorted(strikes) for r, strikes in rights.items()}
        for exp, rights in strike_map.items()
    }


def _options_by_strike(
    chain: List[Dict[str, Any]], right: str
) -> Dict[float, Dict[str, Dict[str, Any]]]:
    """Return mapping ``{strike: {expiry: option}}`` with valid mid prices."""

    result: Dict[float, Dict[str, Dict[str, Any]]] = {}
    norm_right = normalize_right(right)
    for opt in chain:
        try:
            opt_right = normalize_right(opt.get("type") or opt.get("right"))
            if opt_right != norm_right:
                continue
            strike = float(opt.get("strike"))
            expiry = str(opt.get("expiry"))
        except Exception:
            continue
        mid = get_option_mid_price(opt)
        try:
            mid_val = float(mid) if mid is not None else math.nan
        except Exception:
            mid_val = math.nan
        if math.isnan(mid_val):
            continue
        result.setdefault(strike, {})[expiry] = opt
    return result


def _nearest_strike(
    strike_map: Dict[str, Dict[str, List[float]]],
    expiry: str,
    right: str,
    target: float,
    *,
    tolerance_percent: float | None = None,
    criteria: CriteriaConfig | None = None,
) -> StrikeMatch:
    """Return closest strike information for ``target``.

    If no strike falls within ``tolerance_percent`` deviation of ``target``,
    ``matched`` will be ``None``.
    """

    right = normalize_right(right)
    strikes = strike_map.get(str(expiry), {}).get(right)
    if not strikes:
        logger.info(
            f"[nearest_strike] geen strikes voor expiry {expiry} (type={right})"
        )
        return StrikeMatch(target)

    if tolerance_percent is None:
        crit = criteria or load_criteria()
        tolerance_percent = crit.alerts.nearest_strike_tolerance_percent

    nearest = min(strikes, key=lambda s: abs(s - target))
    diff = abs(nearest - target)
    pct = (diff / target * 100) if target else 0.0
    if pct > tolerance_percent:
        logger.info(
            f"[nearest_strike] Geen geschikte strike gevonden binnen tolerantie ±{tolerance_percent:.1f}% — fallback geannuleerd"
        )
        return StrikeMatch(target)

    logger.info(
        f"[nearest_strike] target {target} → matched {nearest} for expiry {expiry} (type={right})"
    )
    return StrikeMatch(target, nearest, nearest - target)


def _find_option(
    chain: List[Dict[str, Any]],
    expiry: str,
    strike: float,
    right: str,
    *,
    strategy: str = "",
    leg_desc: str | None = None,
    target: float | None = None,
) -> Optional[Dict[str, Any]]:
    def _norm_exp(val: Any) -> str:
        if isinstance(val, (datetime, date)):
            return val.strftime("%Y-%m-%d")
        s = str(val)
        d = parse_date(s)
        return d.strftime("%Y-%m-%d") if d else s

    def _norm_right(val: Any) -> str:
        return normalize_right(str(val))

    target_exp = _norm_exp(expiry)
    target_right = _norm_right(right)
    target_strike = float(strike)

    for opt in chain:
        try:
            opt_exp = _norm_exp(opt.get("expiry"))
            opt_right = _norm_right(opt.get("type") or opt.get("right"))
            opt_strike = float(opt.get("strike"))
            if (
                opt_exp == target_exp
                and opt_right == target_right
                and math.isclose(opt_strike, target_strike, abs_tol=0.01)
            ):
                return opt
        except Exception:
            continue
    if strategy:
        attempted = (
            f"{strike}"
            if target is None or math.isclose(strike, target, abs_tol=0.001)
            else f"{strike} (origineel {target})"
        )
        if leg_desc:
            logger.info(
                f"[{strategy}] {leg_desc} {attempted} niet gevonden voor expiry {expiry}"
            )
        else:
            logger.info(
                f"[{strategy}] Strike {attempted}{right} {expiry} niet gevonden"
            )
    return None


def _bs_estimate_missing(legs: List[Dict[str, Any]]) -> None:
    """Fill missing model price and delta using Black-Scholes."""
    for leg in legs:
        need_model = leg.get("model") in (None, 0, "0", "")
        need_delta = leg.get("delta") in (None, 0, "0", "")
        if not (need_model or need_delta):
            continue
        try:
            opt_type = (leg.get("type") or leg.get("right") or "").upper()[0]
            strike = float(leg.get("strike"))
            spot = float(
                leg.get("spot")
                or leg.get("underlying_price")
                or leg.get("underlying")
            )
            iv = float(leg.get("iv"))
            exp = leg.get("expiry") or leg.get("expiration")
            if not exp:
                continue
            dte = dte_between_dates(today(), exp)
            if dte is None or dte <= 0 or iv <= 0 or spot <= 0:
                continue
        except Exception:
            continue
        try:
            price = black_scholes(opt_type, spot, strike, dte, iv)
            T = dte / 365.0
            d1 = (
                math.log(spot / strike)
                + (0.045 - 0.0 + 0.5 * iv * iv) * T
            ) / (iv * math.sqrt(T))
            nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
            if opt_type == "C":
                delta = nd1
            else:
                delta = nd1 - 1
            if need_model:
                leg["model"] = price
            if need_delta:
                leg["delta"] = delta
        except Exception:
            continue


def _metrics(
    strategy: StrategyName | str,
    legs: List[Dict[str, Any]],
    spot: float | None = None,
    *,
    criteria: CriteriaConfig | None = None,
) -> tuple[Optional[Dict[str, Any]], list[str]]:
    strategy = getattr(strategy, "value", strategy)
    _bs_estimate_missing(legs)
    missing_fields = False
    for leg in legs:
        missing: List[str] = []
        if not leg.get("mid"):
            missing.append("mid")
        if not leg.get("model"):
            missing.append("model")
        if not leg.get("delta"):
            missing.append("delta")
        if missing:
            logger.info(
                f"[leg-missing] {leg['type']} {leg['strike']} {leg['expiry']}: {', '.join(missing)}"
            )
            missing_fields = True
    if missing_fields:
        logger.info(
            f"[❌ voorstel afgewezen] {strategy} — reason: ontbrekende metrics (details in debug)"
        )
        return None, [
            "Edge, model of delta ontbreekt — metrics kunnen niet worden berekend"
        ]
    for leg in legs:
        normalize_leg(leg)
    short_deltas = [
        abs(leg.get("delta", 0))
        for leg in legs
        if leg.get("position", 0) < 0 and leg.get("delta") is not None
    ]
    pos_val = (
        calculate_pos(sum(short_deltas) / len(short_deltas)) if short_deltas else None
    )

    short_edges: List[float] = []
    for leg in legs:
        if leg.get("position", 0) < 0:
            try:
                edge_val = float(leg.get("edge"))
            except Exception:
                edge_val = math.nan
            if not math.isnan(edge_val):
                short_edges.append(edge_val)
    edge_avg = round(sum(short_edges) / len(short_edges), 2) if short_edges else None

    reasons: list[str] = []

    crit = criteria or load_criteria()
    min_vol = float(crit.market_data.min_option_volume)
    min_oi = float(crit.market_data.min_option_open_interest)
    if min_vol > 0 or min_oi > 0:
        low_liq: List[str] = []
        for leg in legs:
            vol_raw = leg.get("volume")
            try:
                vol = float(vol_raw) if vol_raw not in (None, "") else None
            except Exception:
                vol = None
            oi_raw = leg.get("open_interest")
            try:
                oi = float(oi_raw) if oi_raw not in (None, "") else None
            except Exception:
                oi = None
            exp = leg.get("expiry") or leg.get("expiration")
            strike = leg.get("strike")
            if isinstance(strike, float) and strike.is_integer():
                strike = int(strike)
            if (
                (min_vol > 0 and vol is not None and vol < min_vol)
                or (min_oi > 0 and oi is not None and oi < min_oi)
            ):
                low_liq.append(f"{strike} [{vol or 0}, {oi or 0}, {exp}]")
        if low_liq:
            logger.info(
                f"[{strategy}] Onvoldoende volume/open interest voor strikes {', '.join(low_liq)}"
            )
            reasons.append("onvoldoende volume/open interest")
            return None, reasons

    missing_mid: List[str] = []
    credits: List[float] = []
    debits: List[float] = []
    for leg in legs:
        mid = leg.get("mid")
        try:
            mid_val = float(mid) if mid is not None else math.nan
        except Exception:
            mid_val = math.nan
        if math.isnan(mid_val):
            missing_mid.append(str(leg.get("strike")))
            continue
        qty = abs(
            float(
                leg.get("qty")
                or leg.get("quantity")
                or leg.get("position")
                or 1
            )
        )
        pos = float(leg.get("position") or 0)
        if pos < 0:
            credits.append(mid_val * qty)
        elif pos > 0:
            debits.append(mid_val * qty)
    credit_short = sum(credits)
    debit_long = sum(debits)
    if missing_mid:
        logger.info(
            f"[{strategy}] Ontbrekende bid/ask-data voor strikes {','.join(missing_mid)}"
        )
        reasons.append("ontbrekende bid/ask-data")
    fallbacks = {leg.get("mid_fallback") for leg in legs if leg.get("mid_fallback")}
    if "close" in fallbacks:
        reasons.append("fallback naar close gebruikt voor midprijs")
    net_credit = credit_short - debit_long
    strikes = "/".join(str(l.get("strike")) for l in legs)
    if strategy in STRATEGIES_THAT_REQUIRE_POSITIVE_CREDIT and net_credit <= 0:
        reasons.append("negatieve credit")
        return None, reasons

    cost_basis = -net_credit * 100
    risk = heuristic_risk_metrics(legs, cost_basis)
    margin = None
    try:
        margin = calculate_margin(
            strategy,
            legs,
            net_cashflow=net_credit,
        )
    except Exception:
        margin = None
    if margin is None or (isinstance(margin, float) and math.isnan(margin)):
        reasons.append("margin kon niet worden berekend")
        return None, reasons
    for leg in legs:
        leg["margin"] = margin

    max_profit = risk.get("max_profit")
    max_loss = risk.get("max_loss")
    profit_estimated = False
    scenario_info: Optional[Dict[str, Any]] = None
    if strategy == "naked_put":
        max_profit = net_credit * 100
        max_loss = -margin
    elif strategy in {"ratio_spread", "backspread_put", "calendar"}:
        max_loss = -margin
    if ((max_profit is None or max_profit <= 0) or strategy == "ratio_spread") and spot is not None:
        scenarios, err = estimate_scenario_profit(legs, spot, strategy)
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
    rom = (
        calculate_rom(max_profit, margin) if max_profit is not None and margin else None
    )
    if rom is None:
        reasons.append("ROM kon niet worden berekend omdat margin ontbreekt")
    ev = (
        calculate_ev(pos_val or 0.0, max_profit or 0.0, max_loss or 0.0)
        if pos_val is not None and max_profit is not None and max_loss is not None
        else None
    )
    ev_pct = (ev / margin) * 100 if ev is not None and margin else None
    rom_w = float(crit.strategy.score_weight_rom)
    pos_w = float(crit.strategy.score_weight_pos)
    ev_w = float(crit.strategy.score_weight_ev)

    score = 0.0
    if rom is not None:
        score += rom * rom_w
    if pos_val is not None:
        score += pos_val * pos_w
    if ev_pct is not None:
        score += ev_pct * ev_w

    breakevens = _breakevens(strategy, legs, net_credit * 100)

    if (ev_pct is not None and ev_pct <= 0 and not profit_estimated) or score < 0:
        reasons.append("negatieve EV of score")
        logger.info(
            f"[❌ voorstel afgewezen] {strategy} — reason: EV/score te laag"
        )
        return None, reasons

    result = {
        "pos": pos_val,
        "ev": ev,
        "ev_pct": ev_pct,
        "rom": rom,
        "edge": edge_avg,
        "credit": net_credit * 100,
        "margin": margin,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "score": round(score, 2),
        "profit_estimated": profit_estimated,
        "scenario_info": scenario_info,
    }
    if fallbacks:
        result["fallback"] = ",".join(sorted(fallbacks))
    return result, reasons


def _validate_ratio(strategy: str, legs: List[Dict[str, Any]], credit: float) -> bool:
    shorts = [l for l in legs if l.get("position", 0) < 0]
    longs = [l for l in legs if l.get("position", 0) > 0]

    short_qty = sum(abs(float(l.get("position", 0))) for l in shorts)
    long_qty = sum(float(l.get("position", 0)) for l in longs)

    if not (len(shorts) == 1 and short_qty == 1 and long_qty == 2):
        logger.info(
            f"[{strategy}] Verhouding klopt niet: {len(shorts)} short (qty {short_qty}) en {len(longs)} long (qty {long_qty})"
        )
        return False
    if credit <= 0:
        logger.info(f"[{strategy}] Credit niet positief: {credit}")
        return False

    short_strike = float(shorts[0].get("strike", 0))
    long_strikes = [float(l.get("strike", 0)) for l in longs]
    if strategy == "ratio_spread" and not all(ls > short_strike for ls in long_strikes):
        logger.info(f"[{strategy}] Long strikes niet hoger dan short strike")
        return False
    if strategy == "backspread_put" and not all(
        ls < short_strike for ls in long_strikes
    ):
        logger.info(f"[{strategy}] Long strikes niet lager dan short strike")
        return False
    return True




def generate_strategy_candidates(
    symbol: str,
    strategy_type: str,
    option_chain: List[Dict[str, Any]],
    atr: float,
    config: Dict[str, Any],
    spot: float | None,
    *,
    interactive_mode: bool = False,
) -> tuple[List[StrategyProposal], str | None]:
    """Load strategy module and generate candidates."""
    if spot is None:
        raise ValueError("spot price is required")
    try:
        mod = __import__(f"tomic.strategies.{strategy_type}", fromlist=["generate"])
    except Exception as e:
        raise ValueError(f"Unknown strategy {strategy_type}") from e
    return mod.generate(symbol, option_chain, config, spot, atr), None


__all__ = [
    "StrategyProposal",
    "select_expiry_pairs",
    "generate_strategy_candidates",
]
