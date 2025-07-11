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


def _metrics(
    strategy: str, legs: List[Dict[str, Any]]
) -> tuple[Optional[Dict[str, Any]], list[str]]:
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
            logger.debug(
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
    if any(leg.get("mid_fallback") == "close" for leg in legs):
        reasons.append("fallback naar close gebruikt voor midprijs")
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
    if any(leg.get("mid_fallback") == "close" for leg in legs):
        result["fallback"] = "close"
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

    if hasattr(pd, "DataFrame") and not isinstance(pd.DataFrame, type(object)):
        df_chain = pd.DataFrame(option_chain)
        if spot is not None and spot > 0:
            if "expiration" not in df_chain.columns and "expiry" in df_chain.columns:
                df_chain["expiration"] = df_chain["expiry"]
            df_chain = fill_missing_mid_with_parity(df_chain, spot=spot)
            option_chain = df_chain.to_dict(orient="records")
    proposals: List[StrategyProposal] = []
    missing_legs = 0
    invalid_metrics = 0
    num_pairs_tested = 0
    invalid_ratio = 0
    risk_rejected = 0
    skipped_mid: List[str] = []
    reasons: set[str] = set()
    best_candidate: Dict[str, Any] | None = None

    min_rr = 0.0
    try:
        min_rr = float(strat_cfg.get("min_risk_reward", 0.0))
    except Exception:
        min_rr = 0.0

    def make_leg(
        opt: Dict[str, Any], position: int, spot_price: float
    ) -> Dict[str, Any]:
        mid = opt.get("mid")
        try:
            mid_val = float(mid)
            if math.isnan(mid_val):
                mid = None
            else:
                mid = mid_val
        except Exception:
            mid = None
        if mid is None:
            mid = get_option_mid_price(opt)
        used_close_as_mid = False
        manual_override = False
        if mid is None:
            try:
                close_val = float(opt.get("close"))
                if close_val > 0:
                    mid = close_val
                    used_close_as_mid = True
                    right = normalize_right(opt.get("type") or opt.get("right"))
                    logger.info(
                        f"[fallback] Gebruik close als mid voor {opt.get('strike')}{right[0].upper() if right else ''}: {close_val}"
                    )
            except Exception:
                pass
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
        if mid is None:
            right = normalize_right(opt.get("type") or opt.get("right"))
            logger.info(
                f"[make_leg] Geen mid voor {opt.get('strike')}{right[0].upper() if right else ''} — geen bid/ask, geen close, geen handmatige invoer"
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
        if used_close_as_mid:
            leg["mid_fallback"] = "close"
        if manual_override:
            leg["manual_override"] = True
        if opt.get("mid_from_parity"):
            leg["mid_from_parity"] = True

        # Black-Scholes modelprijs berekening
        model_price = None
        try:
            opt_type = (opt.get("type") or opt.get("right") or "").upper()[0]
            strike = float(opt["strike"])
            iv = float(opt["iv"])
            expiry = str(opt["expiry"])
            if spot_price and iv > 0.0 and expiry:
                dte = dte_between_dates(today(), expiry)
                model_price = black_scholes(
                    opt_type,
                    spot_price,
                    strike,
                    dte,
                    iv,
                    r=0.045,
                    q=0.0,
                )
        except Exception as e:
            logger.warning(
                f"[model] Black-Scholes faalde voor {opt.get('strike')}: {e}"
            )

        if model_price is not None:
            leg["model"] = model_price
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

    def _log_candidate(desc: str, strategy: str, metrics: Optional[Dict[str, Any]], status: str) -> None:
        nonlocal best_candidate
        reward = risk = ev_val = rr = None
        score = None
        if metrics:
            reward = metrics.get("max_profit")
            ml = metrics.get("max_loss")
            risk = abs(ml) if ml is not None else None
            ev_val = metrics.get("ev")
            try:
                rr = reward / risk if reward is not None and risk else None
            except Exception:
                rr = None
            score = metrics.get("score") or (ev_val if ev_val is not None else 0)
        msg = f"[check] {strategy} {desc}"
        if reward is not None and risk is not None and ev_val is not None:
            msg += f" | reward={reward}, risk={risk}, EV={ev_val}"
        msg += f" | {status}"
        logger.info(msg)
        if metrics:
            if best_candidate is None or (score is not None and score > best_candidate.get("score", float("-inf"))):
                best_candidate = {
                    "desc": desc,
                    "strategy": strategy,
                    "ev": ev_val,
                    "rr": rr,
                    "score": score if score is not None else 0,
                    "reason": status.replace("afgekeurd: ", ""),
                }

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
                make_leg(sc_opt, -1, spot),
                make_leg(lc_opt, 1, spot),
                make_leg(sp_opt, -1, spot),
                make_leg(lp_opt, 1, spot),
            ]
            desc = (
                f"SC={sc.matched} SP={sp.matched} LC={lc.matched} LP={lp.matched}"
            )
            metrics, m_reasons = _metrics("iron_condor", legs)
            if metrics:
                if not _passes_risk(metrics):
                    risk_rejected += 1
                    _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                    continue
                proposals.append(StrategyProposal(legs=legs, **metrics))
                _log_candidate(desc, strategy_type, metrics, "OK")
            else:
                invalid_metrics += 1
                reasons.update(m_reasons)
                reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")

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
                legs = [make_leg(short_opt, -1, spot), make_leg(long_opt, 1, spot)]
                desc = f"SP={short_opt.get('strike')} LP={long_strike.matched}"
                metrics, m_reasons = _metrics("bull put spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                    _log_candidate(desc, strategy_type, metrics, "OK")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")

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
                legs = [make_leg(short_opt, -1, spot), make_leg(long_opt, 1, spot)]
                desc = f"SC={short_opt.get('strike')} LC={long_strike.matched}"
                metrics, m_reasons = _metrics("bear call spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                    _log_candidate(desc, strategy_type, metrics, "OK")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")

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
                    leg = make_leg(opt, -1, spot)
                    desc = f"SP={opt.get('strike')}"
                    metrics, m_reasons = _metrics("naked_put", [leg])
                    if metrics:
                        if not _passes_risk(metrics):
                            risk_rejected += 1
                            _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                            continue
                        proposals.append(StrategyProposal(legs=[leg], **metrics))
                        _log_candidate(desc, strategy_type, metrics, "OK")
                    else:
                        invalid_metrics += 1
                        reasons.update(m_reasons)
                        reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                        _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")
                    if len(proposals) >= 5:
                        break

    elif strategy_type == "calendar":
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        base_strikes = rules.get("base_strikes_relative_to_spot", [])
        by_strike = _options_by_strike(option_chain, "C")
        has_valid_pair = False

        for off in base_strikes:
            strike_target = spot + (off * atr if use_atr else off)
            if not by_strike:
                continue
            avail = sorted(by_strike)
            nearest = min(avail, key=lambda s: abs(s - strike_target))
            diff = abs(nearest - strike_target)
            pct = (diff / strike_target * 100) if strike_target else 0.0
            if pct > 1.0:
                logger.info(
                    f"[calendar] strike {strike_target} buiten tolerantie voor beschikbare {nearest}"
                )
                continue
            valid_exp = sorted(by_strike[nearest])
            pairs = select_expiry_pairs(valid_exp, min_gap)
            if not pairs:
                all_exp = [
                    exp
                    for exp, rights in strike_map.items()
                    if nearest in rights.get("call", [])
                ]
                for exp in all_exp:
                    if exp not in valid_exp:
                        logger.info(
                            f"[calendar] skip strike {nearest} {exp} – no mid price"
                        )
                        skipped_mid.append(f"{nearest}-{exp}")
                continue
            has_valid_pair = True
            for near, far in pairs[:3]:
                num_pairs_tested += 1
                short_opt = by_strike[nearest].get(near)
                long_opt = by_strike[nearest].get(far)
                if not short_opt:
                    logger.info(
                        f"[calendar] skip strike {nearest} {near} – no mid price"
                    )
                    skipped_mid.append(f"{nearest}-{near}")
                if not long_opt:
                    logger.info(
                        f"[calendar] skip strike {nearest} {far} – no mid price"
                    )
                    skipped_mid.append(f"{nearest}-{far}")
                if not short_opt or not long_opt:
                    missing_legs += 1
                    continue
                legs = [make_leg(short_opt, -1, spot), make_leg(long_opt, 1, spot)]
                desc = f"strike={nearest} near={near} far={far}"
                metrics, m_reasons = _metrics("calendar", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                    _log_candidate(desc, strategy_type, metrics, "OK")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")
                if len(proposals) >= 5:
                    break

        if not has_valid_pair:
            reasons.add("Geen geldige expiry-combinaties gevonden voor calendar spread")

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
                    make_leg(sc_opt, -1, spot),
                    make_leg(lc_opt, 1, spot),
                    make_leg(sp_opt, -1, spot),
                    make_leg(lp_opt, 1, spot),
                ]
                desc = (
                    f"SC={sc_strike} SP={sp_strike} LC={lc_strike} LP={lp_strike}"
                )
                metrics, m_reasons = _metrics("atm_iron_butterfly", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                    _log_candidate(desc, strategy_type, metrics, "OK")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")
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
                legs = [make_leg(short_opt, -1, spot), make_leg(long_opt, 2, spot)]
                desc = f"SC={short_opt.get('strike')} LC={long_strike.matched}"
                metrics, m_reasons = _metrics("ratio_spread", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    if _validate_ratio(
                        "ratio_spread", legs, metrics.get("credit", 0.0)
                    ):
                        proposals.append(StrategyProposal(legs=legs, **metrics))
                        _log_candidate(desc, strategy_type, metrics, "OK")
                    else:
                        invalid_ratio += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: verhouding ongeldig")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")

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
                legs = [make_leg(short_opt, -1, spot), make_leg(long_opt, 2, spot)]
                desc = f"near={near} far={far} SP={short_opt.get('strike')} LP={long_strike.matched}"
                metrics, m_reasons = _metrics("backspread_put", legs)
                if metrics:
                    if not _passes_risk(metrics):
                        risk_rejected += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: R/R te laag")
                        continue
                    if _validate_ratio(
                        "backspread_put", legs, metrics.get("credit", 0.0)
                    ):
                        proposals.append(StrategyProposal(legs=legs, **metrics))
                        _log_candidate(desc, strategy_type, metrics, "OK")
                    else:
                        invalid_ratio += 1
                        _log_candidate(desc, strategy_type, metrics, "afgekeurd: verhouding ongeldig")
                else:
                    invalid_metrics += 1
                    reasons.update(m_reasons)
                    reason = ", ".join(m_reasons) if m_reasons else "onbekend"
                    _log_candidate(desc, strategy_type, None, f"afgekeurd: {reason}")

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if proposals:
        return proposals[:5], []

    if best_candidate:
        ev_val = best_candidate.get("ev")
        rr_val = best_candidate.get("rr")
        desc = f"{best_candidate['strategy']} {best_candidate['desc']}"
        reason = best_candidate.get("reason", "onbekend")
        logger.info(
            f"[fallback] Beste combinatie was {desc} met EV={ev_val} en R/R={rr_val} — afgewezen vanwege {reason}"
        )

    if skipped_mid:
        reasons.add(f"{len(skipped_mid)} legs overgeslagen door ontbrekende midprijs")
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
