from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import date, datetime
import math

from .analysis.scoring import calculate_score, calculate_breakevens
from .helpers.dateutils import parse_date
from .utils import (
    get_option_mid_price,
    normalize_right,
    get_leg_right,
)
from .logutils import logger
from .criteria import CriteriaConfig, RULES, load_criteria
from .strategies import StrategyName
from .config import get as cfg_get
from .helpers.normalize import normalize_config
from .strategies.config_models import CONFIG_MODELS
from .config import _asdict
from .strategy.reasons import ReasonDetail, dedupe_reasons, normalize_reason


# Strategies that must yield a positive net credit are configured via RULES.
POSITIVE_CREDIT_STRATS = set(
    RULES.strategy.acceptance.require_positive_credit_for
)


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
    fallback_summary: Optional[Dict[str, int]] = None
    spread_rejects_n: int = 0


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




def _build_strike_map(chain: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[float]]]:
    """Return mapping of expiries and option types to available strikes."""

    strike_map: Dict[str, Dict[str, set[float]]] = {}
    for opt in chain:
        try:
            expiry = str(opt.get("expiry"))
            right = get_leg_right(opt)
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
            opt_right = get_leg_right(opt)
            if opt_right != norm_right:
                continue
            strike = float(opt.get("strike"))
            expiry = str(opt.get("expiry"))
        except Exception:
            continue
        mid, _ = get_option_mid_price(opt)
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
            opt_right = get_leg_right(opt)
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
    strategy: StrategyName | str,
    legs: List[Dict[str, Any]],
    spot: float | None = None,
    *,
    criteria: CriteriaConfig | None = None,
) -> tuple[Optional[Dict[str, Any]], list[str]]:
    proposal = StrategyProposal(legs=legs)
    score, reasons = calculate_score(
        strategy, proposal, spot, criteria=criteria
    )
    if score is None:
        return None, reasons
    result = {
        "pos": proposal.pos,
        "ev": proposal.ev,
        "ev_pct": proposal.ev_pct,
        "rom": proposal.rom,
        "edge": proposal.edge,
        "credit": proposal.credit,
        "margin": proposal.margin,
        "max_profit": proposal.max_profit,
        "max_loss": proposal.max_loss,
        "breakevens": proposal.breakevens,
        "score": proposal.score,
        "profit_estimated": proposal.profit_estimated,
        "scenario_info": proposal.scenario_info,
    }
    if proposal.fallback:
        result["fallback"] = proposal.fallback
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
    config: Dict[str, Any] | None = None,
    spot: float | None = None,
    *,
    interactive_mode: bool = False,
) -> tuple[List[StrategyProposal], list[str]]:
    """Load strategy module and generate candidates."""
    if spot is None:
        raise ValueError("spot price is required")
    try:
        mod = __import__(f"tomic.strategies.{strategy_type}", fromlist=["generate"])
    except Exception as e:
        raise ValueError(f"Unknown strategy {strategy_type}") from e
    cfg_data = config if config is not None else cfg_get("STRATEGY_CONFIG", {})
    base = cfg_data.get("default", {})
    strat_cfg = {**base, **cfg_data.get("strategies", {}).get(strategy_type, {})}
    strat_cfg = normalize_config(
        strat_cfg, {"strike_config": ("strike_to_strategy_config", None)}
    )
    if "min_risk_reward" not in strat_cfg or strat_cfg["min_risk_reward"] is None:
        strat_cfg["min_risk_reward"] = RULES.strategy.acceptance.min_risk_reward
    strat_cfg["strike_to_strategy_config"] = normalize_config(
        strat_cfg.get("strike_to_strategy_config", {}), strategy=strategy_type
    )
    model_cls = CONFIG_MODELS.get(strategy_type)
    if model_cls is not None:
        strat_cfg = _asdict(model_cls(**strat_cfg))
    result = mod.generate(symbol, option_chain, strat_cfg, spot, atr)
    if isinstance(result, tuple):
        proposals, reasons = result
    else:  # backward compatibility
        proposals, reasons = result, None
    if reasons is None:
        reason_list: List[ReasonDetail] = []
    else:
        reason_list = dedupe_reasons(reasons)
    return proposals, reason_list


__all__ = [
    "StrategyProposal",
    "select_expiry_pairs",
    "generate_strategy_candidates",
    "calculate_breakevens",
]
