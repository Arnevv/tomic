"""Portfolio level strategy suggestions backed by the strategy pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from tomic import config as cfg
from tomic.analysis.greeks import compute_greeks_by_symbol
from tomic.criteria import RULES
from tomic.helpers.numeric import safe_float
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.services.chain_processing import (
    ChainPreparationConfig,
    ChainPreparationError,
    PreparedChain,
    load_and_prepare_chain,
)
from tomic.services.pipeline_runner import PipelineRunContext, run_pipeline
from tomic.services.strategy_pipeline import PipelineRunError, StrategyPipeline
from tomic.strategy.models import StrategyProposal
from tomic.strategies import StrategyName


@dataclass(frozen=True)
class _StrategyContext:
    """Context passed to the pipeline runner."""

    pipeline: StrategyPipeline
    symbol: str
    chain: Sequence[MutableMapping[str, Any]]
    spot_price: float
    atr: float
    strategy_config: Mapping[str, Any]
    interest_rate: float
    next_earnings: Any | None = None


def _find_chain_file(directory: Path, symbol: str) -> Path | None:
    pattern = f"option_chain_{symbol}_"
    candidates = sorted(directory.glob(f"*{pattern}*.csv"))
    return candidates[-1] if candidates else None


def _load_chain_for_symbol(
    chain_dir: Path,
    symbol: str,
    config: ChainPreparationConfig,
) -> PreparedChain | None:
    """Return prepared option chain for ``symbol`` or ``None`` if unavailable."""

    chain_path = _find_chain_file(chain_dir, symbol)
    if not chain_path:
        logger.warning("Geen chain gevonden voor %s in %s", symbol, chain_dir)
        return None

    try:
        prepared = load_and_prepare_chain(chain_path, config)
    except ChainPreparationError as exc:
        logger.warning("Chain kan niet geladen worden voor %s: %s", symbol, exc)
        return None

    if prepared.quality < config.min_quality:
        logger.warning(
            "Chainkwaliteit %.1f%% lager dan drempel %.1f%% voor %s",
            prepared.quality,
            config.min_quality,
            symbol,
        )
        return None

    return prepared


def _extract_metric(metrics: Any | None, name: str) -> Any:
    if metrics is None:
        return None
    if isinstance(metrics, Mapping):
        return metrics.get(name)
    return getattr(metrics, name, None)


def _extract_float(metrics: Any | None, name: str) -> float | None:
    value = _extract_metric(metrics, name)
    return safe_float(value)


def _run_strategy_pipeline(
    ctx: _StrategyContext,
    strategy: StrategyName | str,
) -> list[StrategyProposal]:
    """Execute the shared strategy pipeline and return proposals."""

    strategy_name = strategy.value if isinstance(strategy, StrategyName) else strategy
    context = PipelineRunContext(
        pipeline=ctx.pipeline,
        symbol=ctx.symbol,
        strategy=strategy_name,
        option_chain=ctx.chain,
        spot_price=ctx.spot_price,
        atr=ctx.atr,
        config=ctx.strategy_config,
        interest_rate=ctx.interest_rate,
        next_earnings=ctx.next_earnings,
    )
    try:
        result = run_pipeline(context)
    except PipelineRunError as exc:
        logger.warning(
            "Pipeline mislukt voor %s/%s: %s", ctx.symbol, strategy_name, exc
        )
        return []
    return list(result.proposals)


def _leg_multiplier(leg: Mapping[str, Any]) -> float:
    for key in ("position", "qty", "quantity"):
        value = safe_float(leg.get(key))
        if value is not None:
            return value
    return 0.0


def _sum_greeks(legs: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for leg in legs:
        mult = _leg_multiplier(leg)
        for field, label in (
            ("delta", "Delta"),
            ("gamma", "Gamma"),
            ("vega", "Vega"),
            ("theta", "Theta"),
        ):
            value = safe_float(leg.get(field))
            if value is None:
                continue
            totals[label] += value * mult
    return totals


def _format_proposal(
    proposal: StrategyProposal,
    *,
    reason: str,
) -> dict[str, Any]:
    impact = _sum_greeks(proposal.legs)
    return {
        "strategy": proposal.strategy,
        "legs": [dict(leg) for leg in proposal.legs],
        "impact": impact,
        "score": proposal.score,
        "score_label": proposal.score_label,
        "reason": reason,
        "ROM": proposal.rom,
        "RR": proposal.risk_reward,
        "margin": proposal.margin,
        "max_profit": proposal.max_profit,
        "max_loss": proposal.max_loss,
        "credit": proposal.credit,
        "profit_estimated": proposal.profit_estimated,
        "scenario_info": dict(proposal.scenario_info or {}),
    }


def _select_best(proposals: Sequence[StrategyProposal]) -> StrategyProposal | None:
    candidates = [p for p in proposals if p.legs]
    if not candidates:
        return None

    def _score_key(proposal: StrategyProposal) -> tuple[bool, float, float]:
        score = proposal.score if proposal.score is not None else float("-inf")
        rom = proposal.rom if proposal.rom is not None else float("-inf")
        return (proposal.score is not None, score, rom)

    return max(candidates, key=_score_key)


def _condor_gate_allows(metrics: Any | None, vix: float | None) -> bool:
    gate = RULES.portfolio.condor_gates
    iv_rank = _extract_float(metrics, "iv_rank")
    iv_pct = _extract_float(metrics, "iv_percentile")

    if gate.iv_rank_min is not None and iv_rank is not None and iv_rank < gate.iv_rank_min:
        return False
    if gate.iv_rank_max is not None and iv_rank is not None and iv_rank > gate.iv_rank_max:
        return False
    if (
        gate.iv_percentile_min is not None
        and iv_pct is not None
        and iv_pct < gate.iv_percentile_min
    ):
        return False
    if (
        gate.iv_percentile_max is not None
        and iv_pct is not None
        and iv_pct > gate.iv_percentile_max
    ):
        return False
    if gate.vix_min is not None and vix is not None and vix < gate.vix_min:
        return False
    if gate.vix_max is not None and vix is not None and vix > gate.vix_max:
        return False
    return True


def _calendar_gate_allows(metrics: Any | None, vix: float | None) -> bool:
    gate = RULES.portfolio.calendar_gates
    iv_rank = _extract_float(metrics, "iv_rank")
    iv_pct = _extract_float(metrics, "iv_percentile")
    term = _extract_float(metrics, "term_m1_m3")

    if gate.iv_rank_min is not None and iv_rank is not None and iv_rank < gate.iv_rank_min:
        return False
    if gate.iv_rank_max is not None and iv_rank is not None and iv_rank > gate.iv_rank_max:
        return False
    if (
        gate.iv_percentile_min is not None
        and iv_pct is not None
        and iv_pct < gate.iv_percentile_min
    ):
        return False
    if (
        gate.iv_percentile_max is not None
        and iv_pct is not None
        and iv_pct > gate.iv_percentile_max
    ):
        return False
    if gate.term_m1_m3_min is not None and term is not None and term < gate.term_m1_m3_min:
        return False
    if gate.term_m1_m3_max is not None and term is not None and term > gate.term_m1_m3_max:
        return False
    if gate.vix_min is not None and vix is not None and vix < gate.vix_min:
        return False
    if gate.vix_max is not None and vix is not None and vix > gate.vix_max:
        return False
    return True


def suggest_strategies(
    symbol: str,
    chain: Sequence[MutableMapping[str, Any]],
    exposure: Mapping[str, float],
    *,
    pipeline: StrategyPipeline,
    spot_price: float,
    atr: float = 0.0,
    strategy_config: Mapping[str, Any] | None = None,
    interest_rate: float = 0.05,
    metrics: Any | None = None,
    vix: float | None = None,
    next_earnings: Any | None = None,
) -> list[dict[str, Any]]:
    """Return portfolio suggestions driven by the strategy pipeline."""

    ctx = _StrategyContext(
        pipeline=pipeline,
        symbol=symbol,
        chain=list(chain),
        spot_price=float(spot_price or 0.0),
        atr=float(atr or 0.0),
        strategy_config=dict(strategy_config or {}),
        interest_rate=float(interest_rate or 0.0),
        next_earnings=next_earnings,
    )

    suggestions: list[dict[str, Any]] = []
    delta = float(exposure.get("Delta", 0.0) or 0.0)
    vega = float(exposure.get("Vega", 0.0) or 0.0)

    if abs(delta) > 25:
        strategy = (
            StrategyName.SHORT_CALL_SPREAD if delta > 0 else StrategyName.SHORT_PUT_SPREAD
        )
        proposals = _run_strategy_pipeline(ctx, strategy)
        best = _select_best(proposals)
        if best:
            best.strategy = best.strategy or strategy.value
            suggestions.append(
                _format_proposal(best, reason="Delta-balancering")
            )

    if vega > RULES.portfolio.vega_to_condor and _condor_gate_allows(metrics, vix):
        proposals = _run_strategy_pipeline(ctx, StrategyName.IRON_CONDOR)
        best = _select_best(proposals)
        if best:
            best.strategy = best.strategy or StrategyName.IRON_CONDOR.value
            suggestions.append(
                _format_proposal(best, reason="Vega verlagen")
            )

    if vega < RULES.portfolio.vega_to_calendar and _calendar_gate_allows(metrics, vix):
        proposals = _run_strategy_pipeline(ctx, StrategyName.CALENDAR)
        best = _select_best(proposals)
        if best:
            best.strategy = best.strategy or StrategyName.CALENDAR.value
            suggestions.append(
                _format_proposal(best, reason="Vega verhogen")
            )

    return suggestions


def generate_proposals(
    positions_file: str,
    chain_dir: str,
    *,
    metrics: Mapping[str, Any] | None = None,
    vix: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Combine portfolio Greeks with chain data and return proposals."""

    positions = load_json(positions_file)
    open_positions = [p for p in positions if p.get("position")]
    exposures = compute_greeks_by_symbol(open_positions)

    pipeline = StrategyPipeline(config=cfg.get)
    chain_config = ChainPreparationConfig.from_app_config()
    strategy_config = cfg.get("STRATEGY_CONFIG", {}) or {}
    interest_rate = safe_float(cfg.get("INTEREST_RATE", 0.05)) or 0.05

    result: dict[str, list[dict[str, Any]]] = {}
    base_dir = Path(chain_dir)

    for sym, greeks in exposures.items():
        if sym == "TOTAL":
            continue

        prepared = _load_chain_for_symbol(base_dir, sym, chain_config)
        if prepared is None or not prepared.records:
            continue

        metrics_obj = metrics.get(sym) if metrics else None
        spot = _extract_float(metrics_obj, "spot_price")
        atr = _extract_float(metrics_obj, "atr")
        next_earnings = _extract_metric(metrics_obj, "next_earnings")

        proposals = suggest_strategies(
            sym,
            prepared.records,
            greeks,
            pipeline=pipeline,
            spot_price=spot or prepared.records[0].get("underlying_price", 0.0) or 0.0,
            atr=atr or 0.0,
            strategy_config=strategy_config,
            interest_rate=interest_rate,
            metrics=metrics_obj,
            vix=vix,
            next_earnings=next_earnings,
        )

        if proposals:
            result[sym] = proposals

    return result


__all__ = ["generate_proposals", "suggest_strategies"]

