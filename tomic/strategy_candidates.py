from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Dict, List, Optional
from datetime import date, datetime
import math

from .metrics import (
    calculate_margin,
    calculate_pos,
    calculate_rom,
    calculate_ev,
)
from .analysis.strategy import heuristic_risk_metrics, parse_date
from .utils import (
    get_option_mid_price,
    normalize_leg,
    normalize_right,
    prompt_user_for_price,
)
from .logutils import logger
from .config import get as cfg_get


@dataclass
class StrategyProposal:
    """Container for a generated option strategy."""

    legs: List[Dict[str, Any]] = field(default_factory=list)
    pos: Optional[float] = None
    ev: Optional[float] = None
    rom: Optional[float] = None
    edge: Optional[float] = None
    credit: Optional[float] = None
    margin: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: Optional[List[float]] = None
    score: Optional[float] = None


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
    strategy: str, legs: List[Dict[str, Any]], credit: float
) -> Optional[List[float]]:
    """Return simple breakeven estimates for supported strategies."""
    if not legs:
        return None
    if strategy in {"bull put spread", "bear call spread"}:
        short = [l for l in legs if l.get("position") < 0][0]
        strike = float(short.get("strike"))
        if strategy == "bull put spread":
            return [strike - credit]
        return [strike + credit]
    if strategy in {"iron_condor", "atm_iron_butterfly"}:
        short_put = [
            l
            for l in legs
            if l.get("position") < 0 and (l.get("type") or l.get("right")) == "P"
        ]
        short_call = [
            l
            for l in legs
            if l.get("position") < 0 and (l.get("type") or l.get("right")) == "C"
        ]
        if short_put and short_call:
            sp = float(short_put[0].get("strike"))
            sc = float(short_call[0].get("strike"))
            return [sp - credit, sc + credit]
    if strategy == "naked_put":
        short = legs[0]
        strike = float(short.get("strike"))
        return [strike - credit]
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


def _nearest_strike(
    strike_map: Dict[str, Dict[str, List[float]]],
    expiry: str,
    right: str,
    target: float,
    *,
    tolerance_percent: float = 1.0,
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


def _metrics(strategy: str, legs: List[Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], list[str]]:
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
    credit_short = 0.0
    debit_long = 0.0
    missing_mid: List[str] = []
    for leg in legs:
        mid = leg.get("mid")
        try:
            mid_val = float(mid) if mid is not None else math.nan
        except Exception:
            mid_val = math.nan
        if math.isnan(mid_val):
            missing_mid.append(str(leg.get("strike")))
            continue
        if leg.get("position", 0) < 0:
            credit_short += mid_val
        else:
            debit_long += mid_val
    if missing_mid:
        logger.info(
            f"[{strategy}] Ontbrekende bid/ask-data voor strikes {','.join(missing_mid)}"
        )
        reasons.append("ontbrekende bid/ask-data")
    net_credit = credit_short - debit_long
    strikes = "/".join(str(l.get("strike")) for l in legs)
    if strategy not in {"ratio_spread", "backspread_put"} and net_credit <= 0:
        reasons.append("negatieve credit")
        return None, reasons

    risk = heuristic_risk_metrics(legs, (debit_long - credit_short) * 100)
    margin = None
    net_cashflow = net_credit
    try:
        margin = calculate_margin(
            strategy,
            legs,
            net_cashflow=net_cashflow,
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
    rom_w = float(cfg_get("SCORE_WEIGHT_ROM", 0.5))
    pos_w = float(cfg_get("SCORE_WEIGHT_POS", 0.3))
    ev_w = float(cfg_get("SCORE_WEIGHT_EV", 0.2))

    score = 0.0
    if rom is not None:
        score += rom * rom_w
    if pos_val is not None:
        score += pos_val * pos_w
    if ev is not None:
        score += ev * ev_w

    breakevens = _breakevens(strategy, legs, net_credit * 100)

    result = {
        "pos": pos_val,
        "ev": ev,
        "rom": rom,
        "edge": edge_avg,
        "credit": net_credit * 100,
        "margin": margin,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "score": round(score, 2),
    }
    return result, reasons

def _validate_ratio(strategy: str, legs: List[Dict[str, Any]], credit: float) -> bool:
    shorts = [l for l in legs if l.get("position", 0) < 0]
    longs = [l for l in legs if l.get("position", 0) > 0]
    if not (len(shorts) == 1 and len(longs) == 2):
        logger.info(
            f"[{strategy}] Verhouding klopt niet: gevonden {len(shorts)} short en {len(longs)} long"
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
    """Return top strategy proposals for ``strategy_type`` with optional reason."""

    strat_cfg = config.get("strategies", {}).get(strategy_type, {})
    rules = strat_cfg.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    if spot is None:
        raise ValueError("spot price is required")

    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["Geen expiries beschikbaar in de optiechain"]
    expiry = expiries[0]
    strike_map = _build_strike_map(option_chain)
    proposals: List[StrategyProposal] = []
    missing_legs = 0
    invalid_metrics = 0
    num_pairs_tested = 0
    invalid_ratio = 0
    risk_rejected = 0
    reasons: set[str] = set()

    min_rr = 0.0
    try:
        min_rr = float(strat_cfg.get("min_risk_reward", 0.0))
    except Exception:
        min_rr = 0.0

    def make_leg(opt: Dict[str, Any], position: int) -> Dict[str, Any]:
        mid = get_option_mid_price(opt)
        manual_override = False
        if mid is None and interactive_mode:
            mid = prompt_user_for_price(
                opt.get("strike"),
                str(opt.get("expiry")),
                opt.get("type") or opt.get("right"),
                position,
            )
            if mid is not None:
                manual_override = True
                right = normalize_right(opt.get("type") or opt.get("right"))
                logger.info(
                    f"[override] Handmatige prijsinvoer voor {opt.get('strike')}{right[0].upper() if right else ''}: mid = {mid}"
                )
        leg = {
            "expiry": opt.get("expiry"),
            "type": opt.get("type") or opt.get("right"),
            "strike": opt.get("strike"),
            "delta": opt.get("delta"),
            "bid": opt.get("bid"),
            "ask": opt.get("ask"),
            "mid": mid,
            "edge": opt.get("edge"),
            "model": opt.get("model"),
            "position": position,
        }
        if manual_override:
            leg["manual_override"] = True
        return normalize_leg(leg)

    def _passes_risk(metrics: Dict[str, Any]) -> bool:
        if not metrics or min_rr <= 0:
            return True
        mp = metrics.get("max_profit")
        ml = metrics.get("max_loss")
        if mp is None or ml is None or not ml:
            return True
        try:
            rr = mp / abs(ml)
        except Exception:
            return True
        return rr >= min_rr

    if strategy_type == "iron_condor":
        calls = rules.get("short_call_multiplier", [])
        puts = rules.get("short_put_multiplier", [])
        width = float(rules.get("wing_width", 0))
        for c_mult, p_mult in islice(zip(calls, puts), 5):
            num_pairs_tested += 1
            sc_target = spot + (c_mult * atr if use_atr else c_mult)
            sp_target = spot - (p_mult * atr if use_atr else p_mult)
            lc_target = sc_target + width
            lp_target = sp_target - width
            sc = _nearest_strike(strike_map, expiry, "C", sc_target)
            sp = _nearest_strike(strike_map, expiry, "P", sp_target)
            lc = _nearest_strike(strike_map, expiry, "C", lc_target)
            lp = _nearest_strike(strike_map, expiry, "P", lp_target)
            logger.info(
                f"[iron_condor] probeer SC {sc.matched} SP {sp.matched} LC {lc.matched} LP {lp.matched}"
            )
            if not all([sc.matched, sp.matched, lc.matched, lp.matched]):
                missing_legs += 1
                continue
            sc_opt = _find_option(
                option_chain,
                expiry,
                sc.matched,
                "C",
                strategy=strategy_type,
                leg_desc="Short call",
                target=sc.target,
            )
            sp_opt = _find_option(
                option_chain,
                expiry,
                sp.matched,
                "P",
                strategy=strategy_type,
                leg_desc="Short put",
                target=sp.target,
            )
            lc_opt = _find_option(
                option_chain,
                expiry,
                lc.matched,
                "C",
                strategy=strategy_type,
                leg_desc="Long call",
                target=lc.target,
            )
            lp_opt = _find_option(
                option_chain,
                expiry,
                lp.matched,
                "P",
                strategy=strategy_type,
                leg_desc="Long put",
                target=lp.target,
            )
            if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
                missing_legs += 1
                continue
            legs = [
                make_leg(sc_opt, -1),
                make_leg(lc_opt, 1),
                make_leg(sp_opt, -1),
                make_leg(lp_opt, 1),
            ]
            metrics, m_reasons = _metrics("iron_condor", legs)
            if metrics:
                if not _passes_risk(metrics):
                    risk_rejected += 1
                    continue
                proposals.append(StrategyProposal(legs=legs, **metrics))
            else:
                invalid_metrics += 1
                reasons.update(m_reasons)

    elif strategy_type == "short_put_spread":
        delta_range = rules.get("short_put_delta_range", [])
        widths = rules.get("long_put_distance_points", [])
        if len(delta_range) == 2:
            for width in widths[:5]:
                num_pairs_tested += 1
                short_opt = None
                for opt in option_chain:
                    if (
                        str(opt.get("expiry")) == expiry
                        and (opt.get("type") or opt.get("right")) == "P"
                        and opt.get("delta") is not None
                        and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                    ):
                        short_opt = opt
                        break
                if not short_opt:
                    continue
                long_strike_target = float(short_opt.get("strike")) - width
                long_strike = _nearest_strike(
                    strike_map, expiry, "P", long_strike_target
                )
                logger.info(
                    f"[short_put_spread] probeer short {short_opt.get('strike')} long {long_strike.matched}"
                )
                if not long_strike.matched:
                    missing_legs += 1
                    continue
                long_opt = _find_option(
                    option_chain,
                    expiry,
                    long_strike.matched,
                    "P",
                    strategy=strategy_type,
                    leg_desc="Long put",
                    target=long_strike.target,
                )
                if not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics, m_reasons = _metrics("bull put spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)

    elif strategy_type == "short_call_spread":
        delta_range = rules.get("short_call_delta_range", [])
        widths = rules.get("long_call_distance_points", [])
        if len(delta_range) == 2:
            for width in widths[:5]:
                num_pairs_tested += 1
                short_opt = None
                for opt in option_chain:
                    if (
                        str(opt.get("expiry")) == expiry
                        and (opt.get("type") or opt.get("right")) == "C"
                        and opt.get("delta") is not None
                        and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                    ):
                        short_opt = opt
                        break
                if not short_opt:
                    continue
                long_strike_target = float(short_opt.get("strike")) + width
                long_strike = _nearest_strike(
                    strike_map, expiry, "C", long_strike_target
                )
                logger.info(
                    f"[short_call_spread] probeer short {short_opt.get('strike')} long {long_strike.matched}"
                )
                if not long_strike.matched:
                    missing_legs += 1
                    continue
                long_opt = _find_option(
                    option_chain,
                    expiry,
                    long_strike.matched,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Long call",
                    target=long_strike.target,
                )
                if not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics, m_reasons = _metrics("bear call spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)

    elif strategy_type == "naked_put":
        delta_range = rules.get("short_put_delta_range", [])
        if len(delta_range) == 2:
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == expiry
                    and (opt.get("type") or opt.get("right")) == "P"
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    logger.info(f"[naked_put] probeer strike {opt.get('strike')}")
                    leg = make_leg(opt, -1)
                    metrics, m_reasons = _metrics("naked_put", [leg])
                    if metrics:
                        if not _passes_risk(metrics):
                            risk_rejected += 1
                            continue
                        proposals.append(StrategyProposal(legs=[leg], **metrics))
                    else:
                        invalid_metrics += 1
                        reasons.update(m_reasons)
                    if len(proposals) >= 5:
                        break

    elif strategy_type == "calendar":
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        pairs = select_expiry_pairs(expiries, min_gap)
        strikes = rules.get("base_strikes_relative_to_spot", [])
        if not pairs:
            reasons.add("Geen geldige expiry-combinaties gevonden voor calendar spread")
            return [], sorted(reasons)
        for near, far in pairs[:3]:
            for off in strikes:
                num_pairs_tested += 1
                strike_target = spot + (off * atr if use_atr else off)
                strike = _nearest_strike(strike_map, near, "C", strike_target)
                logger.info(
                    f"[calendar] probeer near {near} far {far} strike {strike.matched}"
                )
                if not strike.matched:
                    missing_legs += 1
                    continue
                short_opt = _find_option(
                    option_chain,
                    near,
                    strike.matched,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Short call",
                    target=strike.target,
                )
                long_strike = _nearest_strike(strike_map, far, "C", strike_target)
                logger.info(
                    f"[calendar] long leg strike {long_strike.matched} voor far {far}"
                )
                if not long_strike.matched:
                    missing_legs += 1
                    continue
                long_opt = _find_option(
                    option_chain,
                    far,
                    long_strike.matched,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Long call",
                    target=long_strike.target,
                )
                if not short_opt or not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics, m_reasons = _metrics("calendar", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                if len(proposals) >= 5:
                    break

    elif strategy_type == "atm_iron_butterfly":
        centers = rules.get("center_strike_relative_to_spot", [0])
        widths = rules.get("wing_width_points", [])
        for c_off in centers:
            center = spot + (c_off * atr if use_atr else c_off)
            center = _nearest_strike(strike_map, expiry, "C", center)
            for width in widths:
                sc_strike = _nearest_strike(strike_map, expiry, "C", center)
                sp_strike = _nearest_strike(strike_map, expiry, "P", center)
                lc_strike = _nearest_strike(strike_map, expiry, "C", center + width)
                lp_strike = _nearest_strike(strike_map, expiry, "P", center - width)
                logger.info(
                    f"[atm_iron_butterfly] probeer center {center} width {width}"
                )
                sc_opt = _find_option(
                    option_chain,
                    expiry,
                    sc_strike,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Short call",
                )
                sp_opt = _find_option(
                    option_chain,
                    expiry,
                    sp_strike,
                    "P",
                    strategy=strategy_type,
                    leg_desc="Short put",
                )
                lc_opt = _find_option(
                    option_chain,
                    expiry,
                    lc_strike,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Long call",
                )
                lp_opt = _find_option(
                    option_chain,
                    expiry,
                    lp_strike,
                    "P",
                    strategy=strategy_type,
                    leg_desc="Long put",
                )
                if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
                    missing_legs += 1
                    continue
                legs = [
                    make_leg(sc_opt, -1),
                    make_leg(lc_opt, 1),
                    make_leg(sp_opt, -1),
                    make_leg(lp_opt, 1),
                ]
                metrics, m_reasons = _metrics("atm_iron_butterfly", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                if len(proposals) >= 5:
                    break

    elif strategy_type == "ratio_spread":
        delta_range = rules.get("short_leg_delta_range", [])
        widths = rules.get("long_leg_distance_points", [])
        if len(delta_range) == 2:
            for width in widths[:5]:
                num_pairs_tested += 1
                short_opt = None
                for opt in option_chain:
                    if (
                        str(opt.get("expiry")) == expiry
                        and (opt.get("type") or opt.get("right")) == "C"
                        and opt.get("delta") is not None
                        and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                    ):
                        short_opt = opt
                        break
                if not short_opt:
                    continue
                long_strike_target = float(short_opt.get("strike")) + width
                long_strike = _nearest_strike(
                    strike_map, expiry, "C", long_strike_target
                )
                logger.info(
                    f"[ratio_spread] probeer short {short_opt.get('strike')} long {long_strike.matched}"
                )
                if not long_strike.matched:
                    missing_legs += 1
                    continue
                long_opt = _find_option(
                    option_chain,
                    expiry,
                    long_strike.matched,
                    "C",
                    strategy=strategy_type,
                    leg_desc="Long call",
                    target=long_strike.target,
                )
                if not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 2)]
                metrics, m_reasons = _metrics("ratio_spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    if _validate_ratio("ratio_spread", legs, metrics.get("credit", 0.0)):
                        proposals.append(StrategyProposal(legs=legs, **metrics))
                    else:
                        invalid_ratio += 1
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)

    elif strategy_type == "backspread_put":
        delta_range = rules.get("short_put_delta_range", [])
        widths = rules.get("long_put_distance_points", [])
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        pairs = select_expiry_pairs(expiries, min_gap)
        if len(delta_range) == 2:
            for near, far in pairs[:3]:
                for width in widths:
                    num_pairs_tested += 1
                    short_opt = None
                    for opt in option_chain:
                        if (
                            str(opt.get("expiry")) == near
                            and (opt.get("type") or opt.get("right")) == "P"
                            and opt.get("delta") is not None
                            and delta_range[0]
                            <= float(opt.get("delta"))
                            <= delta_range[1]
                        ):
                            short_opt = opt
                            break
                if not short_opt:
                    continue
                long_strike_target = float(short_opt.get("strike")) - width
                long_strike = _nearest_strike(strike_map, far, "P", long_strike_target)
                logger.info(
                    f"[backspread_put] probeer near {near} far {far} short {short_opt.get('strike')} long {long_strike.matched}"
                )
                if not long_strike.matched:
                    missing_legs += 1
                    continue
                long_opt = _find_option(
                    option_chain,
                    far,
                    long_strike.matched,
                    "P",
                    strategy=strategy_type,
                    leg_desc="Long put",
                    target=long_strike.target,
                )
                if not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 2)]
                metrics, m_reasons = _metrics("backspread_put", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        continue
                    if _validate_ratio("backspread_put", legs, metrics.get("credit", 0.0)):
                        proposals.append(StrategyProposal(legs=legs, **metrics))
                    else:
                        invalid_ratio += 1
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if proposals:
        return proposals[:5], []

    if missing_legs > 0:
        reasons.add("Benodigde strikes ontbreken in de optiechain")
    if invalid_metrics > 0:
        reasons.add("Ongeldige of onvolledige metrics")
    if num_pairs_tested == 0:
        reasons.add("Er konden geen combinaties getest worden")
    if invalid_ratio > 0:
        reasons.add("Verhouding legs ongeldig")
    if risk_rejected > 0:
        reasons.add("Risk/Reward-ratio onvoldoende")

    if not reasons:
        reasons.add("Onbekende reden")
    return [], sorted(reasons)


__all__ = [
    "StrategyProposal",
    "select_expiry_pairs",
    "generate_strategy_candidates",
]
