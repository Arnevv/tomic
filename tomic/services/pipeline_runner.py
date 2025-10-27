"""Shared helper for executing the strategy pipeline with consistent context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    StrategyPipeline,
    run as run_strategy_pipeline,
)


@dataclass(frozen=True)
class PipelineRunContext:
    """Normalized input passed to :func:`run_pipeline`."""

    pipeline: StrategyPipeline
    symbol: str
    strategy: str
    option_chain: Sequence[Mapping[str, Any]] | Sequence[MutableMapping[str, Any]]
    spot_price: float
    atr: float = 0.0
    config: Mapping[str, Any] | None = None
    interest_rate: float = 0.05
    dte_range: tuple[int, int] | None = None
    interactive_mode: bool = False
    criteria: Any | None = None
    next_earnings: date | None = None
    debug_path: Path | None = None


def run_pipeline(context: PipelineRunContext) -> PipelineRunResult:
    """Execute the strategy pipeline for ``context`` and normalize the result."""

    strategy_name = str(context.strategy)

    try:
        result = run_strategy_pipeline(
            context.pipeline,
            symbol=context.symbol,
            strategy=strategy_name,
            option_chain=list(context.option_chain),
            spot_price=float(context.spot_price or 0.0),
            atr=float(context.atr or 0.0),
            config=context.config,
            interest_rate=float(context.interest_rate),
            dte_range=context.dte_range,
            interactive_mode=bool(context.interactive_mode),
            criteria=context.criteria,
            next_earnings=context.next_earnings,
            debug_path=context.debug_path,
        )
    except PipelineRunError:
        raise
    except Exception as exc:  # pragma: no cover - defensive normalization
        raise PipelineRunError(
            f"pipeline execution failed for {context.symbol}/{strategy_name}"
        ) from exc

    return PipelineRunResult(
        context=result.context,
        proposals=list(result.proposals),
        summary=result.summary,
        filtered_chain=list(result.filtered_chain),
    )


__all__ = ["PipelineRunContext", "run_pipeline"]

