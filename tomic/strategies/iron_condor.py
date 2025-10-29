from __future__ import annotations

from typing import Any, Dict, List

from . import StrategyName
from .utils import ShortLegSpec, WingSpreadSpec, generate_wing_spread
from ..analysis.scoring import calculate_score


def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List["StrategyProposal"], list[str]]:
    """Generate iron condor proposals using :func:`generate_wing_spread`."""

    return generate_wing_spread(
        symbol,
        option_chain,
        config,
        spot,
        atr,
        strategy_name=StrategyName.IRON_CONDOR,
        spec=WingSpreadSpec(
            call_leg=ShortLegSpec(option_type="C", delta_range_key="short_call_delta_range"),
            put_leg=ShortLegSpec(option_type="P", delta_range_key="short_put_delta_range"),
        ),
        score_func=calculate_score,
    )


__all__ = ["generate"]

